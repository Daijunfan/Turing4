from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import ceil, log2
from time import perf_counter

from .generator_basis import GeneratorBasis
from .predicate_pool import (
    basis_from_predicates,
    enumerate_signatures,
    future_predicate_pool,
    minimum_separating_subset,
)
from .spec import CircuitSystem


def _algebraic_signatures(system: CircuitSystem, pool, eligible):
    """Recover triangular sparse coordinates by exact ANF pivot elimination."""
    # Future predicates often occur in complement pairs. One representative of
    # each pair is sufficient and supplies the information-theoretic bit count.
    representatives: list[int] = []
    used: set[int] = set()
    constant_one = frozenset({0})
    for index in eligible:
        if index in used:
            continue
        representatives.append(index)
        used.add(index)
        for other in eligible:
            if other not in used and (
                pool.anfs[index] ^ pool.anfs[other]
            ).monomials == constant_one:
                used.add(other)
                break
    selected = tuple(representatives)
    if not selected or len(selected) > 12:
        return None
    selected_anfs = [pool.anfs[index] for index in selected]
    supports = [anf.support_mask for anf in selected_anfs]
    pivots = []
    for index, anf in enumerate(selected_anfs):
        candidates = [
            monomial.bit_length() - 1
            for monomial in anf.monomials
            if monomial and monomial.bit_count() == 1
            and all(
                not (supports[other] >> (monomial.bit_length() - 1)) & 1
                for other in range(len(selected_anfs)) if other != index
            )
        ]
        if not candidates:
            return None
        pivots.append(candidates[0])
    if len(set(pivots)) != len(pivots):
        return None
    total_variables = len(system.state_names) + len(system.input_names)
    nonpivots = [index for index in range(total_variables) if index not in pivots]
    replacements = [None] * total_variables
    for offset, variable in enumerate(nonpivots, start=len(selected)):
        replacements[variable] = type(selected_anfs[0]).variable(offset)
    for macro_bit, (pivot, anf) in enumerate(zip(pivots, selected_anfs)):
        rest = anf ^ type(anf).variable(pivot)
        replacements[pivot] = type(anf).variable(macro_bit) ^ rest.substitute(replacements)
    transformed = tuple(
        anf.substitute(replacements) for anf in pool.anfs
    )
    macro_mask = (1 << len(selected)) - 1
    if any(anf.support_mask & ~macro_mask for anf in transformed):
        return None
    signatures = tuple(
        tuple(anf.evaluate(code) for anf in transformed)
        for code in range(1 << len(selected))
    )
    if len(set(signatures)) != len(signatures):
        return None
    return selected, signatures


@dataclass
class ANFSynthesisResult:
    basis: GeneratorBasis | None
    reason: str


def synthesize_anf(
    system: CircuitSystem,
    *,
    max_degree: int = 3,
    max_monomials: int = 64,
) -> ANFSynthesisResult:
    """Exact bounded-degree sparse-ANF predicate-algebra synthesis."""
    start = perf_counter()
    try:
        pool = future_predicate_pool(system, max_terms=max_monomials)
    except (OverflowError, RuntimeError) as error:
        return ANFSynthesisResult(None, str(error))
    eligible = [
        index for index, anf in enumerate(pool.anfs)
        if anf is not None and anf.degree <= max_degree and len(anf.monomials) <= max_monomials
    ]
    if not eligible:
        return ANFSynthesisResult(
            None, "no predicate satisfies the requested ANF degree/term bound"
        )
    algebraic = (
        _algebraic_signatures(system, pool, eligible)
        if system.reachable_predicate == system.aig.true
        else None
    )
    if algebraic is not None:
        selected, signatures = algebraic
        algebraic_recovery = True
    else:
        if system.micro_bits > 20:
            return ANFSynthesisResult(
                None,
                "algebraic bounded-degree recovery inconclusive above explicit limit",
            )
        signatures = enumerate_signatures(system, pool)
        selected = minimum_separating_subset(signatures, eligible)
        algebraic_recovery = False
    if selected is None:
        return ANFSynthesisResult(
            None,
            "no bounded-degree predicate subset reaches the information-theoretic bit bound",
        )
    lower_bound = max(0, ceil(log2(max(1, len(signatures)))))
    if len(selected) != lower_bound:
        return ANFSynthesisResult(
            None,
            "bounded-degree predicate subset exceeds the global macro-bit lower bound",
        )
    candidate = basis_from_predicates(
        system,
        pool,
        signatures,
        selected,
        backend="anf",
        synthesis_stats={
            "anf_degree_bound": max_degree,
            "anf_monomial_bound": max_monomials,
            "selected_degrees": [pool.anfs[index].degree for index in selected if pool.anfs[index] is not None],
            "selected_monomials": [len(pool.anfs[index].monomials) for index in selected if pool.anfs[index] is not None],
            "algebraic_pivot_recovery": algebraic_recovery,
            "wall_seconds": perf_counter() - start,
            "enumerated_micro_states": False,
        },
    )
    return ANFSynthesisResult(candidate, "success")
