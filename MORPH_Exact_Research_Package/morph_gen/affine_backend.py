from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from .aig import AIG, AffineForm
from .generator_basis import GeneratorBasis
from .spec import CircuitSystem


def _solve_coordinates(row: int, basis: list[int]) -> int | None:
    pivots: dict[int, tuple[int, int]] = {}
    for index, vector in enumerate(basis):
        value = vector
        coefficients = 1 << index
        while value:
            pivot = value.bit_length() - 1
            existing = pivots.get(pivot)
            if existing is None:
                pivots[pivot] = (value, coefficients)
                break
            value ^= existing[0]
            coefficients ^= existing[1]
    value = row
    coefficients = 0
    while value:
        pivot = value.bit_length() - 1
        existing = pivots.get(pivot)
        if existing is None:
            return None
        value ^= existing[0]
        coefficients ^= existing[1]
    return coefficients


def _add_independent(row: int, basis: list[int]) -> bool:
    if row == 0 or _solve_coordinates(row, basis) is not None:
        return False
    basis.append(row)
    return True


def _xor_forms(forms: tuple[AffineForm, ...], selector: int) -> AffineForm:
    result = AffineForm(0, 0)
    bits = selector
    while bits:
        low = bits & -bits
        result ^= forms[low.bit_length() - 1]
        bits ^= low
    return result


@dataclass
class AffineSynthesisResult:
    basis: GeneratorBasis | None
    reason: str


def synthesize_affine(system: CircuitSystem) -> AffineSynthesisResult:
    """Recover the minimal observable affine quotient without state enumeration."""
    start = perf_counter()
    names = (*system.state_names, *system.input_names)
    forms = system.aig.to_affine(
        (*system.next_functions, *system.output_functions), names
    )
    if forms is None:
        return AffineSynthesisResult(None, "transition or output is not affine")
    n = system.micro_bits
    next_forms = forms[:n]
    output_forms = forms[n:]
    basis_rows: list[int] = []
    for output in output_forms:
        _add_independent(output.mask & ((1 << n) - 1), basis_rows)
    cursor = 0
    while cursor < len(basis_rows):
        preimage = _xor_forms(next_forms, basis_rows[cursor])
        _add_independent(preimage.mask & ((1 << n) - 1), basis_rows)
        cursor += 1
    if not basis_rows:
        return AffineSynthesisResult(None, "constant-output affine system")

    f = tuple(system.aig.xor_many(
        system.state_variables[index]
        for index in range(n) if (row >> index) & 1
    ) for row in basis_rows)
    macro = AIG()
    zvars = tuple(macro.input(f"z{i}") for i in range(len(basis_rows)))
    uvars = tuple(macro.input(f"u{i}") for i in range(len(system.input_variables)))
    g = []
    for row in basis_rows:
        preimage = _xor_forms(next_forms, row)
        state_part = preimage.mask & ((1 << n) - 1)
        coordinates = _solve_coordinates(state_part, basis_rows)
        if coordinates is None:
            raise AssertionError("affine observable space is not closed")
        terms = [zvars[index] for index in range(len(zvars)) if (coordinates >> index) & 1]
        terms.extend(
            uvars[index] for index in range(len(uvars))
            if (preimage.mask >> (n + index)) & 1
        )
        if preimage.constant:
            terms.append(macro.true)
        g.append(macro.xor_many(terms))
    h = []
    for output in output_forms:
        coordinates = _solve_coordinates(
            output.mask & ((1 << n) - 1), basis_rows
        )
        if coordinates is None:
            raise AssertionError("output row is outside observable space")
        terms = [zvars[index] for index in range(len(zvars)) if (coordinates >> index) & 1]
        if output.constant:
            terms.append(macro.true)
        h.append(macro.xor_many(terms))

    def and_leaves(root: int) -> list[int]:
        gate = system.aig.nodes[root]
        if gate.op == "AND":
            return and_leaves(gate.args[0]) + and_leaves(gate.args[1])
        return [root]

    initial_forms = system.aig.to_affine(and_leaves(system.initial_predicate), names)
    if initial_forms is None:
        return AffineSynthesisResult(None, "initial predicate is not affine-conjunctive")

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

    assumptions = [(form, True) for form in initial_forms]
    if not consistent(assumptions):
        return AffineSynthesisResult(None, "initial predicate is unsatisfiable")
    initial = 0
    for bit, row in enumerate(basis_rows):
        form = AffineForm(row, 0)
        can_be_zero = consistent([*assumptions, (form, False)])
        can_be_one = consistent([*assumptions, (form, True)])
        if can_be_zero and can_be_one:
            return AffineSynthesisResult(None, "initial predicate maps to multiple macro states")
        initial |= int(can_be_one) << bit

    reachable = tuple(range(1 << len(basis_rows)))
    candidate = GeneratorBasis(
        system,
        f,
        macro,
        zvars,
        uvars,
        tuple(g),
        tuple(h),
        initial,
        reachable,
        "affine",
        {
            "affine_generator_matrix": basis_rows,
            "affine_rank": len(basis_rows),
            "sat_calls": 0,
            "gf2_initial_checks": 2 * len(f),
            "cegis_iterations": len(basis_rows),
            "counterexample_count": max(0, len(basis_rows) - len(output_forms)),
            "wall_seconds": perf_counter() - start,
            "enumerated_micro_states": False,
        },
        minimality_status="minimal observable affine row space",
    )
    return AffineSynthesisResult(candidate, "success")
