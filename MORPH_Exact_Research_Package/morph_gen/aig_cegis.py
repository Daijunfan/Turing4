from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log2
from time import perf_counter

from .generator_basis import GeneratorBasis
from .predicate_pool import (
    PredicatePool,
    basis_from_class_encoding,
    basis_from_predicates,
    enumerate_signatures,
    future_predicate_pool,
    minimum_separating_subset,
    universal_code_functions,
)
from .spec import CircuitSystem


@dataclass
class AIGSynthesisResult:
    basis: GeneratorBasis | None
    reason: str


def synthesize_shared_aig(system: CircuitSystem) -> AIGSynthesisResult:
    """Generic exact shared-DAG synthesis over the future-output predicate algebra.

    The complete predicate signatures are the CEGIS samples/counterexamples.
    Subset search minimizes macro bits first. If no predicate subset realizes the
    lower bound, a universal shared cube template can encode any feasible class.
    """
    start = perf_counter()
    try:
        pool = future_predicate_pool(system, canonical="bdd")
        signatures = enumerate_signatures(system, pool)
    except (OverflowError, RuntimeError) as error:
        return AIGSynthesisResult(None, str(error))
    selected = minimum_separating_subset(signatures, range(len(pool.nodes)))
    lower_bound = max(0, ceil(log2(max(1, len(signatures)))))
    if selected is not None and len(selected) == lower_bound:
        candidate = basis_from_predicates(
            system,
            pool,
            signatures,
            selected,
            backend="shared-aig-cegis",
            synthesis_stats={
                "universal_template_used": False,
                "wall_seconds": perf_counter() - start,
                "enumerated_micro_states": False,
            },
        )
        return AIGSynthesisResult(candidate, "success")

    functions, codes = universal_code_functions(system, pool, signatures)
    candidate = basis_from_class_encoding(
        system,
        pool,
        signatures,
        functions,
        codes,
        backend="shared-aig-cegis",
        synthesis_stats={
            "universal_template_used": True,
            "wall_seconds": perf_counter() - start,
            "enumerated_micro_states": False,
        },
    )
    return AIGSynthesisResult(candidate, "success")
