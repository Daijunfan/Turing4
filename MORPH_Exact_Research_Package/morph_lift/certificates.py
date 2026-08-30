from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Dict, Mapping, Sequence

import z3

from .predicate_closure import PredicateClosureResult
from .symbolic import _equiv, bdd_xor


@dataclass
class CertificateReport:
    bdd_conditions: Dict[str, bool]
    smt_conditions: Dict[str, str]
    smt_seconds: Dict[str, float]
    verified: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _mapping_relation(result: PredicateClosureResult):
    bdd = result.source.bdd
    relation = bdd.true
    for name, predicate in zip(result.macro_machine.state_variables, result.predicates):
        relation &= _equiv(bdd.var(name), predicate)
    return relation


def certificate_error_predicates(result: PredicateClosureResult) -> dict[str, object]:
    """Construct all bad conditions directly from the source/macro functions."""
    source = result.source
    macro = result.macro_machine
    bdd = source.bdd
    assert source.reachable_predicate is not None
    mapping = _mapping_relation(result)
    z_substitution = dict(zip(macro.state_variables, result.predicates))
    source_state = set(source.state_variables)
    output_functionality = bdd.false
    for output in source.output_functions.values():
        can_be_one = bdd.exist(
            source_state, source.reachable_predicate & mapping & output
        )
        can_be_zero = bdd.exist(
            source_state, source.reachable_predicate & mapping & ~output
        )
        output_functionality |= can_be_one & can_be_zero

    transition_functionality = result.closure_error

    output_preservation = bdd.false
    for port, output in source.output_functions.items():
        macro_output = bdd.let(z_substitution, macro.output_functions[port])
        output_preservation |= bdd_xor(output, macro_output)
    output_preservation &= source.reachable_predicate

    transition_commutation = bdd.false
    for successor, macro_next in zip(
        result.successor_predicates, macro.next_state_functions
    ):
        lifted_next = bdd.let(z_substitution, macro_next)
        transition_commutation |= bdd_xor(successor, lifted_next)
    transition_commutation &= source.reachable_predicate

    next_reachable = bdd.let(
        dict(zip(source.state_variables, source.next_state_functions)),
        source.reachable_predicate,
    )
    completeness = source.reachable_predicate & ~next_reachable
    macro_reachable_at_source = bdd.let(
        z_substitution, macro.reachable_predicate
    )
    coverage = source.reachable_predicate & ~macro_reachable_at_source
    macro_initial_at_source = bdd.let(z_substitution, macro.initial_predicate)
    initial_preservation = source.initial_predicate & ~macro_initial_at_source

    # Every macro initial valuation must have an original initial preimage.
    initial_preimage = bdd.exist(
        source_state, source.initial_predicate & mapping
    )
    initial_surjectivity = macro.initial_predicate & ~initial_preimage
    return {
        "same_macro_same_output": output_functionality,
        "same_macro_input_same_next": transition_functionality,
        "output_preservation": output_preservation,
        "initial_preservation": initial_preservation,
        "initial_surjectivity": initial_surjectivity,
        "transition_commutation": transition_commutation,
        "transition_completeness": completeness,
        "reachable_coverage": coverage,
    }


def _bdd_to_z3(bdd, function, variables: Mapping[str, z3.BoolRef]):
    memo: dict[int, z3.BoolRef] = {}
    stack = [(function, False)]
    while stack:
        node, exiting = stack.pop()
        key = int(node)
        if key in memo:
            continue
        if node == bdd.true:
            memo[key] = z3.BoolVal(True)
            continue
        if node == bdd.false:
            memo[key] = z3.BoolVal(False)
            continue
        level, low, high = bdd.succ(node)
        if not exiting:
            stack.append((node, True))
            stack.append((high, False))
            stack.append((low, False))
            continue
        name = bdd.var_at_level(level)
        variable = variables[name] if name in variables else z3.Bool(name)
        regular = z3.If(variable, memo[int(high)], memo[int(low)])
        value = z3.Not(regular) if node.negated else regular
        memo[key] = value
    return memo[int(function)]


def _or(expressions: Sequence[z3.BoolRef]):
    return z3.Or(*expressions) if expressions else z3.BoolVal(False)


def smt_error_formulas(result: PredicateClosureResult) -> dict[str, z3.BoolRef]:
    """Independently assemble the bad conditions from individual BDD functions."""
    source = result.source
    macro = result.macro_machine
    bdd = source.bdd
    x1 = {name: z3.Bool(f"x1_{i}") for i, name in enumerate(source.state_variables)}
    x2 = {name: z3.Bool(f"x2_{i}") for i, name in enumerate(source.state_variables)}
    inputs = {name: z3.Bool(f"input_{i}") for i, name in enumerate(source.inputs)}
    map1 = {**x1, **inputs}
    map2 = {**x2, **inputs}
    reachable1 = _bdd_to_z3(bdd, source.reachable_predicate, map1)
    reachable2 = _bdd_to_z3(bdd, source.reachable_predicate, map2)
    predicates1 = [_bdd_to_z3(bdd, p, map1) for p in result.predicates]
    predicates2 = [_bdd_to_z3(bdd, p, map2) for p in result.predicates]
    same_macro = z3.And(*[a == b for a, b in zip(predicates1, predicates2)])
    outputs1 = [_bdd_to_z3(bdd, f, map1) for f in source.output_functions.values()]
    outputs2 = [_bdd_to_z3(bdd, f, map2) for f in source.output_functions.values()]
    successors1 = [_bdd_to_z3(bdd, f, map1) for f in result.successor_predicates]
    successors2 = [_bdd_to_z3(bdd, f, map2) for f in result.successor_predicates]

    z_at_source = {
        name: predicate for name, predicate in zip(macro.state_variables, predicates1)
    }
    macro_map = {**z_at_source, **inputs}
    macro_outputs = [
        _bdd_to_z3(bdd, macro.output_functions[port], macro_map)
        for port in source.output_functions
    ]
    macro_next = [
        _bdd_to_z3(bdd, function, macro_map)
        for function in macro.next_state_functions
    ]
    source_initial = _bdd_to_z3(bdd, source.initial_predicate, map1)
    macro_initial = _bdd_to_z3(bdd, macro.initial_predicate, macro_map)
    macro_reachable = _bdd_to_z3(bdd, macro.reachable_predicate, macro_map)
    next_mapping = {
        **inputs,
        **dict(zip(source.state_variables, [
            _bdd_to_z3(bdd, function, map1)
            for function in source.next_state_functions
        ])),
    }
    source_next_reachable = _bdd_to_z3(
        bdd, source.reachable_predicate, next_mapping
    )
    return {
        "same_macro_same_output": z3.And(
            reachable1, reachable2, same_macro,
            _or([a != b for a, b in zip(outputs1, outputs2)]),
        ),
        "same_macro_input_same_next": z3.And(
            reachable1, reachable2, same_macro,
            _or([a != b for a, b in zip(successors1, successors2)]),
        ),
        "output_preservation": z3.And(
            reachable1, _or([a != b for a, b in zip(outputs1, macro_outputs)])
        ),
        "initial_preservation": z3.And(source_initial, z3.Not(macro_initial)),
        "transition_commutation": z3.And(
            reachable1,
            _or([a != b for a, b in zip(successors1, macro_next)]),
        ),
        "transition_completeness": z3.And(
            reachable1, z3.Not(source_next_reachable)
        ),
        "reachable_coverage": z3.And(reachable1, z3.Not(macro_reachable)),
    }


def verify_certificate(result: PredicateClosureResult) -> CertificateReport:
    errors = certificate_error_predicates(result)
    bdd_conditions = {
        name: error == result.source.bdd.false for name, error in errors.items()
    }
    smt_conditions: dict[str, str] = {}
    smt_seconds: dict[str, float] = {}
    for name, formula in smt_error_formulas(result).items():
        solver = z3.Solver()
        solver.add(formula)
        start = perf_counter()
        status = solver.check()
        smt_seconds[name] = perf_counter() - start
        smt_conditions[name] = str(status).upper()
    verified = all(bdd_conditions.values()) and all(
        status == "UNSAT" for status in smt_conditions.values()
    )
    return CertificateReport(
        bdd_conditions, smt_conditions, smt_seconds, verified
    )
