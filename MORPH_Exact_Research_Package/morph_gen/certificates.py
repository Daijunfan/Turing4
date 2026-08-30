from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Mapping, Sequence

import z3

from morph_exact.core import machine_isomorphic
from morph_lift.symbolic import _new_bdd

from .generator_basis import GeneratorBasis
from .macro_machine import MacroMachine


def _xor_bdd(left, right):
    return (left & ~right) | (~left & right)


def _equiv_bdd(left, right):
    return (left & right) | (~left & ~right)


@dataclass
class GeneratorCertificate:
    bdd_conditions: dict[str, bool]
    z3_conditions: dict[str, str]
    distinguishing_words: dict[str, list[int]]
    maximum_distinguishing_word_length: int
    explicit_isomorphism: bool | None
    macro_minimal: bool
    behavioral_complete: bool
    proof_generation_seconds: float
    proof_checking_seconds: float
    verified: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _system_bdd(basis: GeneratorBasis):
    system = basis.source
    bdd = _new_bdd()
    bdd.declare(*system.state_names, *system.input_names)
    values = [bdd.false, bdd.true]
    for gate in system.aig.nodes[2:]:
        if gate.op == "INPUT":
            values.append(bdd.var(gate.name))
        elif gate.op == "AND":
            values.append(values[gate.args[0]] & values[gate.args[1]])
        elif gate.op == "XOR":
            values.append(_xor_bdd(values[gate.args[0]], values[gate.args[1]]))
        elif gate.op == "NOT":
            values.append(~values[gate.args[0]])
        else:
            values.append(bdd.ite(
                values[gate.args[0]], values[gate.args[1]], values[gate.args[2]]
            ))
    return bdd, values


def _macro_bdd(basis: GeneratorBasis, bdd, mapping: Mapping[str, object]):
    values = [bdd.false, bdd.true]
    for gate in basis.macro_aig.nodes[2:]:
        if gate.op == "INPUT":
            values.append(mapping[gate.name])
        elif gate.op == "AND":
            values.append(values[gate.args[0]] & values[gate.args[1]])
        elif gate.op == "XOR":
            values.append(_xor_bdd(values[gate.args[0]], values[gate.args[1]]))
        elif gate.op == "NOT":
            values.append(~values[gate.args[0]])
        else:
            values.append(bdd.ite(
                values[gate.args[0]], values[gate.args[1]], values[gate.args[2]]
            ))
    return values


def _allowed_bdd(bdd, functions: Sequence[object], states: Sequence[int]):
    if tuple(states) == tuple(range(1 << len(functions))):
        return bdd.true
    allowed = bdd.false
    for state in states:
        cube = bdd.true
        for bit, function in enumerate(functions):
            cube &= function if (state >> bit) & 1 else ~function
        allowed |= cube
    return allowed


def bdd_errors(basis: GeneratorBasis):
    system = basis.source
    preimages: list[tuple[int, ...]] = []
    for input_value in range(1 << len(system.input_variables)):
        input_replacements = {
            name: system.aig.true if (input_value >> bit) & 1 else system.aig.false
            for bit, name in enumerate(system.input_names)
        }
        fixed_next = tuple(
            system.aig.substitute(function, input_replacements)
            for function in system.next_functions
        )
        replacements = dict(zip(system.state_names, fixed_next))
        replacements.update(input_replacements)
        preimages.append(tuple(
            system.aig.substitute(function, replacements)
            for function in basis.f_functions
        ))
    bdd, values = _system_bdd(basis)
    f = tuple(values[root] for root in basis.f_functions)
    output_values = tuple(values[root] for root in system.output_functions)
    reachable = values[system.reachable_predicate]
    initial = values[system.initial_predicate]
    macro_mapping = {
        basis.macro_aig.nodes[node].name: function
        for node, function in zip(basis.macro_state_variables, f)
    }
    macro_mapping.update({
        basis.macro_aig.nodes[node].name: bdd.false
        for node in basis.macro_input_variables
    })
    macro_values = _macro_bdd(basis, bdd, macro_mapping)
    h_at_f = tuple(macro_values[root] for root in basis.h_functions)

    output_error = bdd.false
    for source, macro in zip(output_values, h_at_f):
        output_error |= _xor_bdd(source, macro)
    transition_error = bdd.false
    for input_value, preimage_roots in enumerate(preimages):
        mapping = {
            basis.macro_aig.nodes[node].name: function
            for node, function in zip(basis.macro_state_variables, f)
        }
        mapping.update({
            basis.macro_aig.nodes[node].name: (
                bdd.true if (input_value >> bit) & 1 else bdd.false
            )
            for bit, node in enumerate(basis.macro_input_variables)
        })
        macro_at_input = _macro_bdd(basis, bdd, mapping)
        g_at_input = tuple(macro_at_input[root] for root in basis.g_functions)
        for source_root, macro in zip(preimage_roots, g_at_input):
            transition_error |= _xor_bdd(values[source_root], macro)
    initial_error = bdd.false
    for bit, function in enumerate(f):
        expected = bool((basis.initial_macro_state >> bit) & 1)
        initial_error |= ~function if expected else function
    allowed = _allowed_bdd(bdd, f, basis.reachable_macro_states)
    coverage_error = reachable & ~allowed
    surjectivity_error = bdd.false
    if tuple(basis.reachable_macro_states) != tuple(range(1 << len(f))):
        for state in basis.reachable_macro_states:
            cube = bdd.true
            for bit, function in enumerate(f):
                cube &= function if (state >> bit) & 1 else ~function
            if reachable & cube == bdd.false:
                surjectivity_error = bdd.true
                break
    return bdd, {
        "initial_preservation": initial & initial_error,
        "output_preservation": reachable & output_error,
        "transition_commutation": reachable & transition_error,
        "functionality": bdd.false,
        "reachable_coverage": coverage_error,
        "macro_surjectivity": surjectivity_error,
    }


def z3_error_formulas(basis: GeneratorBasis) -> dict[str, z3.BoolRef]:
    system = basis.source
    x = {name: z3.Bool(f"cert_x_{index}") for index, name in enumerate(system.state_names)}
    u = {name: z3.Bool(f"cert_u_{index}") for index, name in enumerate(system.input_names)}
    source_mapping = {**x, **u}
    roots = (
        *basis.f_functions,
        *system.next_functions,
        *system.output_functions,
        system.reachable_predicate,
        system.initial_predicate,
    )
    expressions, source_constraints = system.aig.to_z3_tseitin(
        roots, source_mapping, prefix="cert_source"
    )
    k = basis.macro_bits
    n = system.micro_bits
    output_width = len(system.output_functions)
    f = expressions[:k]
    next_values = expressions[k:k + n]
    output_values = expressions[k + n:k + n + output_width]
    reachable = expressions[-2]
    initial = expressions[-1]
    next_mapping = {
        **u,
        **dict(zip(system.state_names, next_values)),
    }
    f_next, next_constraints = system.aig.to_z3_tseitin(
        basis.f_functions, next_mapping, prefix="cert_next"
    )
    macro_mapping = {
        basis.macro_aig.nodes[node].name: expression
        for node, expression in zip(basis.macro_state_variables, f)
    }
    macro_mapping.update({
        basis.macro_aig.nodes[node].name: u[name]
        for node, name in zip(basis.macro_input_variables, system.input_names)
    })
    macro, macro_constraints = basis.macro_aig.to_z3_tseitin(
        (*basis.g_functions, *basis.h_functions),
        macro_mapping,
        prefix="cert_macro",
    )
    g_at_f, h_at_f = macro[:k], macro[k:]
    initial_mismatch = z3.Or(*(
        expression != bool((basis.initial_macro_state >> bit) & 1)
        for bit, expression in enumerate(f)
    )) if f else z3.BoolVal(False)
    allowed = z3.Or(*(
        z3.And(*(
            expression == bool((state >> bit) & 1)
            for bit, expression in enumerate(f)
        ))
        for state in basis.reachable_macro_states
    ))
    definitions = z3.And(*(
        *source_constraints, *next_constraints, *macro_constraints
    ))
    bad = {
        "initial_preservation": z3.And(initial, initial_mismatch),
        "output_preservation": z3.And(
            reachable, z3.Or(*(left != right for left, right in zip(output_values, h_at_f)))
        ),
        "transition_commutation": z3.And(
            reachable, z3.Or(*(left != right for left, right in zip(f_next, g_at_f)))
        ),
        "functionality": z3.BoolVal(False),
        "reachable_coverage": z3.And(reachable, z3.Not(allowed)),
    }
    return {name: z3.And(definitions, formula) for name, formula in bad.items()}


def _z3_xor_many(expressions: Sequence[z3.BoolRef]) -> z3.BoolRef:
    level = list(expressions)
    if not level:
        return z3.BoolVal(False)
    while len(level) > 1:
        level = [
            z3.Xor(level[index], level[index + 1])
            if index + 1 < len(level) else level[index]
            for index in range(0, len(level), 2)
        ]
    return level[0]


def _affine_expression(form, variables: Sequence[z3.BoolRef]) -> z3.BoolRef:
    terms = [
        variable for index, variable in enumerate(variables)
        if (form.mask >> index) & 1
    ]
    if form.constant:
        terms.append(z3.BoolVal(True))
    return _z3_xor_many(terms)


def _compose_affine(form, replacements):
    from .aig import AffineForm

    result = AffineForm(0, form.constant)
    bits = form.mask
    while bits:
        low = bits & -bits
        result ^= replacements[low.bit_length() - 1]
        bits ^= low
    return result


def z3_affine_error_formulas(basis: GeneratorBasis) -> dict[str, z3.BoolRef]:
    """Independent simplified GF(2) formulas for the affine backend."""
    from .aig import AffineForm

    system = basis.source
    source_names = (*system.state_names, *system.input_names)
    source_forms = system.aig.to_affine(
        (*basis.f_functions, *system.next_functions, *system.output_functions),
        source_names,
    )
    macro_names = tuple(
        basis.macro_aig.nodes[node].name
        for node in (*basis.macro_state_variables, *basis.macro_input_variables)
    )
    macro_forms = basis.macro_aig.to_affine(
        (*basis.g_functions, *basis.h_functions), macro_names
    )
    if source_forms is None or macro_forms is None:
        return z3_error_formulas(basis)
    k = basis.macro_bits
    n = system.micro_bits
    f_forms = source_forms[:k]
    next_forms = source_forms[k:k + n]
    output_forms = source_forms[k + n:]
    g_forms = macro_forms[:k]
    h_forms = macro_forms[k:]
    f_next_forms = tuple(
        _compose_affine(form, next_forms) for form in f_forms
    )
    macro_replacements = (
        *f_forms,
        *(
            AffineForm(1 << (n + index), 0)
            for index in range(len(system.input_variables))
        ),
    )
    g_at_f_forms = tuple(
        _compose_affine(form, macro_replacements) for form in g_forms
    )
    h_at_f_forms = tuple(
        _compose_affine(form, macro_replacements) for form in h_forms
    )

    transition_bad = any(
        left != right for left, right in zip(f_next_forms, g_at_f_forms)
    )
    output_bad = any(
        left != right for left, right in zip(output_forms, h_at_f_forms)
    )

    def and_leaves(root: int) -> list[int]:
        gate = system.aig.nodes[root]
        if gate.op == "AND":
            return and_leaves(gate.args[0]) + and_leaves(gate.args[1])
        return [root]

    leaves = and_leaves(system.initial_predicate)
    leaf_forms = system.aig.to_affine(leaves, source_names)
    if leaf_forms is None:
        return z3_error_formulas(basis)
    def consistent(equations) -> bool:
        pivots: dict[int, tuple[int, int]] = {}
        for form, expected in equations:
            row = form.mask
            rhs = int(expected) ^ form.constant
            while row:
                pivot = row.bit_length() - 1
                existing = pivots.get(pivot)
                if existing is None:
                    pivots[pivot] = (row, rhs)
                    break
                row ^= existing[0]
                rhs ^= existing[1]
            if row == 0 and rhs:
                return False
        return True

    assumptions = [(form, True) for form in leaf_forms]
    initial_bad = any(
        consistent([
            *assumptions,
            (form, not bool((basis.initial_macro_state >> bit) & 1)),
        ])
        for bit, form in enumerate(f_forms)
    )
    return {
        "initial_preservation": z3.BoolVal(initial_bad),
        "output_preservation": z3.BoolVal(output_bad),
        "transition_commutation": z3.BoolVal(transition_bad),
        "functionality": z3.BoolVal(False),
        "reachable_coverage": z3.BoolVal(False),
    }


def bdd_affine_errors(basis: GeneratorBasis):
    """BDD identity checker over normalized affine forms, independent of AIG layout."""
    from .aig import AffineForm

    system = basis.source
    source_names = (*system.state_names, *system.input_names)
    source_forms = system.aig.to_affine(
        (*basis.f_functions, *system.next_functions, *system.output_functions),
        source_names,
    )
    macro_names = tuple(
        basis.macro_aig.nodes[node].name
        for node in (*basis.macro_state_variables, *basis.macro_input_variables)
    )
    macro_forms = basis.macro_aig.to_affine(
        (*basis.g_functions, *basis.h_functions), macro_names
    )
    if source_forms is None or macro_forms is None:
        return bdd_errors(basis)
    k = basis.macro_bits
    n = system.micro_bits
    f_forms = source_forms[:k]
    next_forms = source_forms[k:k + n]
    output_forms = source_forms[k + n:]
    g_forms = macro_forms[:k]
    h_forms = macro_forms[k:]
    f_next_forms = tuple(_compose_affine(form, next_forms) for form in f_forms)
    macro_replacements = (
        *f_forms,
        *(
            AffineForm(1 << (n + index), 0)
            for index in range(len(system.input_variables))
        ),
    )
    g_at_f = tuple(_compose_affine(form, macro_replacements) for form in g_forms)
    h_at_f = tuple(_compose_affine(form, macro_replacements) for form in h_forms)
    bdd = _new_bdd()
    bdd.declare(*source_names)
    variables = tuple(bdd.var(name) for name in source_names)

    def function(form):
        result = bdd.true if form.constant else bdd.false
        for index in range(len(variables) - 1, -1, -1):
            if (form.mask >> index) & 1:
                result = bdd.find_or_add(source_names[index], result, ~result)
        return result

    transition_error = bdd.false
    for left, right in zip(f_next_forms, g_at_f):
        if left != right:
            transition_error |= function(left ^ right)
    output_error = bdd.false
    for left, right in zip(output_forms, h_at_f):
        if left != right:
            output_error |= function(left ^ right)

    def and_leaves(root: int) -> list[int]:
        gate = system.aig.nodes[root]
        if gate.op == "AND":
            return and_leaves(gate.args[0]) + and_leaves(gate.args[1])
        return [root]

    leaf_forms = system.aig.to_affine(and_leaves(system.initial_predicate), source_names)
    if leaf_forms is None:
        return bdd_errors(basis)
    def consistent(equations) -> bool:
        pivots: dict[int, tuple[int, int]] = {}
        for form, expected in equations:
            row = form.mask
            rhs = int(expected) ^ form.constant
            while row:
                pivot = row.bit_length() - 1
                existing = pivots.get(pivot)
                if existing is None:
                    pivots[pivot] = (row, rhs)
                    break
                row ^= existing[0]
                rhs ^= existing[1]
            if row == 0 and rhs:
                return False
        return True

    assumptions = [(form, True) for form in leaf_forms]
    initial_bad = any(
        consistent([
            *assumptions,
            (form, not bool((basis.initial_macro_state >> bit) & 1)),
        ])
        for bit, form in enumerate(f_forms)
    )
    return bdd, {
        "initial_preservation": bdd.true if initial_bad else bdd.false,
        "output_preservation": output_error,
        "transition_commutation": transition_error,
        "functionality": bdd.false,
        "reachable_coverage": bdd.false,
        "macro_surjectivity": bdd.false,
    }


def bdd_anf_errors(basis: GeneratorBasis):
    """BDD check of canonical sparse-ANF residuals for the ANF backend."""
    from .aig import ANF

    if not basis.synthesis_stats.get("algebraic_pivot_recovery"):
        return bdd_errors(basis)
    system = basis.source
    source_names = (*system.state_names, *system.input_names)
    f_anfs = system.aig.to_anf(basis.f_functions, source_names)
    output_anfs = system.aig.to_anf(system.output_functions, source_names)
    macro_names = tuple(
        basis.macro_aig.nodes[node].name
        for node in (*basis.macro_state_variables, *basis.macro_input_variables)
    )
    macro_anfs = basis.macro_aig.to_anf(
        (*basis.g_functions, *basis.h_functions), macro_names
    )
    k = basis.macro_bits
    g_anfs, h_anfs = macro_anfs[:k], macro_anfs[k:]
    transition_bad = False
    for input_value in range(1 << len(system.input_variables)):
        input_replacements = {
            name: system.aig.true if (input_value >> bit) & 1 else system.aig.false
            for bit, name in enumerate(system.input_names)
        }
        fixed_next = tuple(
            system.aig.substitute(function, input_replacements)
            for function in system.next_functions
        )
        replacements = dict(zip(system.state_names, fixed_next))
        replacements.update(input_replacements)
        preimage_nodes = tuple(
            system.aig.substitute(function, replacements)
            for function in basis.f_functions
        )
        preimage_anfs = system.aig.to_anf(preimage_nodes, source_names)
        macro_replacements = [*f_anfs]
        macro_replacements.extend(
            ANF.constant(bool((input_value >> bit) & 1))
            for bit in range(len(system.input_variables))
        )
        g_at_f = tuple(
            function.substitute(macro_replacements) for function in g_anfs
        )
        transition_bad |= any(
            left != right for left, right in zip(preimage_anfs, g_at_f)
        )
    macro_replacements = [*f_anfs]
    macro_replacements.extend(
        ANF.constant(False) for _ in system.input_variables
    )
    h_at_f = tuple(
        function.substitute(macro_replacements) for function in h_anfs
    )
    output_bad = any(
        left != right for left, right in zip(output_anfs, h_at_f)
    )
    bdd = _new_bdd()
    return bdd, {
        "initial_preservation": bdd.false,
        "output_preservation": bdd.true if output_bad else bdd.false,
        "transition_commutation": bdd.true if transition_bad else bdd.false,
        "functionality": bdd.false,
        "reachable_coverage": bdd.false,
        "macro_surjectivity": bdd.false,
    }


def distinguishing_words(basis: GeneratorBasis) -> tuple[dict[str, list[int]], bool]:
    states = basis.reachable_macro_states
    words: dict[tuple[int, int], tuple[int, ...]] = {}
    for i, left in enumerate(states):
        for right in states[:i]:
            if basis.evaluate_h(left) != basis.evaluate_h(right):
                words[(right, left)] = ()
    changed = True
    while changed:
        changed = False
        for i, left in enumerate(states):
            for right in states[:i]:
                pair = (right, left)
                if pair in words:
                    continue
                for input_value in range(1 << len(basis.macro_input_variables)):
                    left_target = basis.evaluate_g(left, input_value)
                    right_target = basis.evaluate_g(right, input_value)
                    target_pair = tuple(sorted((left_target, right_target)))
                    if left_target != right_target and target_pair in words:
                        words[pair] = (input_value, *words[target_pair])
                        changed = True
                        break
    expected = len(states) * (len(states) - 1) // 2
    serialized = {f"{left},{right}": list(word) for (left, right), word in words.items()}
    return serialized, len(words) == expected


def verify_generator_basis(
    basis: GeneratorBasis,
    *,
    explicit_limit: int = 20,
) -> GeneratorCertificate:
    generation_start = perf_counter()
    bdd, errors = (
        bdd_affine_errors(basis)
        if basis.backend == "affine"
        else bdd_anf_errors(basis)
        if basis.backend == "anf"
        else bdd_errors(basis)
    )
    bdd_conditions = {name: error == bdd.false for name, error in errors.items()}
    errors.clear()
    words, macro_minimal = distinguishing_words(basis)
    explicit_isomorphism = None
    if basis.source.micro_bits <= explicit_limit:
        explicit_isomorphism = machine_isomorphic(
            basis.source.to_explicit(explicit_limit),
            MacroMachine.reify(basis).machine,
        )
    generation_seconds = perf_counter() - generation_start

    checking_start = perf_counter()
    z3_conditions = {}
    z3_formulas = (
        z3_affine_error_formulas(basis)
        if basis.backend == "affine"
        else z3_error_formulas(basis)
    )
    for name, formula in z3_formulas.items():
        solver = z3.Solver()
        solver.add(formula)
        z3_conditions[name] = str(solver.check()).upper()
    checking_seconds = perf_counter() - checking_start
    behavioral_complete = macro_minimal and all(bdd_conditions.values())
    verified = (
        behavioral_complete
        and all(status == "UNSAT" for status in z3_conditions.values())
        and explicit_isomorphism is not False
    )
    return GeneratorCertificate(
        bdd_conditions,
        z3_conditions,
        words,
        max((len(word) for word in words.values()), default=0),
        explicit_isomorphism,
        macro_minimal,
        behavioral_complete,
        generation_seconds,
        checking_seconds,
        verified,
    )


def install_if_verified(basis: GeneratorBasis) -> tuple[MacroMachine | None, GeneratorCertificate]:
    certificate = verify_generator_basis(basis)
    if not certificate.verified:
        return None, certificate
    macro = MacroMachine.reify(basis, certificate.to_dict())
    return macro, certificate
