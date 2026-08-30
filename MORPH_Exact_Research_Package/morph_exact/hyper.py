from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import log2
from time import perf_counter
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from .core import CompositionResult, CompositionTooLarge, Region, compose_and_minimize
from .engine import Candidate, MorphEngine, RunStats


@dataclass
class HyperCandidate:
    center: int
    left: int
    right: int
    first_pair: Tuple[int, int]
    third: int
    first_result: CompositionResult
    second_result: CompositionResult
    score: float

    @property
    def members(self) -> Tuple[int, int, int]:
        return (self.center, self.left, self.right)


CandidateLike = Union[Candidate, HyperCandidate]


class MorphHyperEngine(MorphEngine):
    """MORPH-Hyper: exact pair and three-region organogenesis.

    Pairwise reification can face a neutral barrier: neither child plus an
    aggregator is compressible alone, while the three-way composite has a small
    exact behavior quotient. This engine detects executable two-input motifs,
    evaluates both local binary parenthesizations, and atomically commits the
    best certificate chain. No approximate quotient is ever installed.
    """

    def _triple_motifs(self, regions: Dict[int, Region]) -> List[Tuple[int, int, int]]:
        owner: Dict[str, int] = {}
        for rid, region in regions.items():
            for signal in region.machine.outputs:
                owner[signal] = rid

        # A producer is mature when no current region still drives one of its
        # executable inputs. This prevents a high-level aggregator from binding
        # to two unresolved internal gates before those gates have formed their
        # own exact organs. It is a semantic closure test, not an oracle level.
        mature: Dict[int, bool] = {}
        for rid, region in regions.items():
            mature[rid] = not any(
                name in owner and owner[name] != rid
                for name in region.machine.inputs
            )

        triples: Set[Tuple[int, int, int]] = set()
        for center_id, center in regions.items():
            # Three-way nucleation is anchored at an unresolved primitive
            # aggregator. Composite regions are already reified organs and are
            # handled as producers, not as new hyperedge centers.
            if len(center.leaves) != 1:
                continue
            producers = sorted({
                owner[name]
                for name in center.machine.inputs
                if name in owner and owner[name] != center_id
            })
            for a, b in combinations(producers, 2):
                if mature.get(a, False) and mature.get(b, False):
                    triples.add((center_id, a, b))
        return sorted(triples)

    def _triple_prefilter_key(
        self, regions: Dict[int, Region], triple: Tuple[int, int, int]
    ) -> Tuple[int, int, int]:
        center, a, b = (regions[x] for x in triple)
        crossing = (
            self.spec.semantic_crossing_count(center, a)
            + self.spec.semantic_crossing_count(center, b)
            + self.spec.semantic_crossing_count(a, b)
        )
        union = center.leaves | a.leaves | b.leaves
        keep = self.spec.keep_outputs(union)
        produced = set(center.machine.outputs) | set(a.machine.outputs) | set(b.machine.outputs)
        union_inputs = (
            set(center.machine.inputs) | set(a.machine.inputs) | set(b.machine.inputs)
        ) - produced
        boundary = len(union_inputs) + len(keep & produced)
        product = center.machine.n_states * a.machine.n_states * b.machine.n_states
        return crossing, -boundary, -product

    def _evaluate_triple(
        self,
        regions: Dict[int, Region],
        triple: Tuple[int, int, int],
        pair_cache: Dict[Tuple[int, int], Candidate],
        counters: dict,
    ) -> Optional[HyperCandidate]:
        center_id, left_id, right_id = triple
        best: Optional[HyperCandidate] = None
        for first_neighbor, third_id in ((left_id, right_id), (right_id, left_id)):
            key = (min(center_id, first_neighbor), max(center_id, first_neighbor))
            first_candidate = pair_cache.get(key)
            if first_candidate is None:
                first_candidate = self._evaluate(regions[center_id], regions[first_neighbor])
                pair_cache[key] = first_candidate
                self._record_candidate(first_candidate, counters)
            if first_candidate.result is None:
                continue
            first_result = first_candidate.result
            first_leaves = regions[center_id].leaves | regions[first_neighbor].leaves
            temporary = Region(-1, first_leaves, first_result.quotient)
            full_leaves = first_leaves | regions[third_id].leaves
            try:
                second_result = compose_and_minimize(
                    temporary.machine,
                    regions[third_id].machine,
                    self.spec.keep_outputs(full_leaves),
                    max_states=self.max_candidate_states,
                    max_transition_evaluations=self.max_candidate_transition_evaluations,
                )
            except CompositionTooLarge:
                counters["candidate_evaluations"] += 1
                counters["oversized_candidates"] += 1
                continue
            self._record_candidate(
                Candidate(-1, third_id, 0.0, second_result), counters
            )
            product = (
                regions[center_id].machine.n_states
                * regions[left_id].machine.n_states
                * regions[right_id].machine.n_states
            )
            total_gain = log2(max(1, product) / max(1, second_result.quotient.n_states))
            quotient_gain = (
                first_result.quotient_gain_bits + second_result.quotient_gain_bits
            )
            largest_input = max(
                len(regions[center_id].machine.inputs),
                len(regions[left_id].machine.inputs),
                len(regions[right_id].machine.inputs),
            )
            boundary_growth = max(0, len(second_result.quotient.inputs) - largest_input)
            work = max(
                1,
                first_result.transition_evaluations
                + second_result.transition_evaluations,
            )
            score = (
                total_gain
                + 0.45 * quotient_gain
                - 0.20 * boundary_growth
                - 0.0125 * log2(work + 1)
                + 0.10  # slight preference for resolving a proven hyperedge
            )
            candidate = HyperCandidate(
                center=center_id,
                left=left_id,
                right=right_id,
                first_pair=(center_id, first_neighbor),
                third=third_id,
                first_result=first_result,
                second_result=second_result,
                score=score,
            )
            if best is None:
                best = candidate
            else:
                best_peak = max(best.first_result.raw.n_states, best.second_result.raw.n_states)
                candidate_peak = max(first_result.raw.n_states, second_result.raw.n_states)
                if (candidate.score, -candidate_peak) > (best.score, -best_peak):
                    best = candidate
        return best

    @staticmethod
    def _members(candidate: CandidateLike) -> Tuple[int, ...]:
        if isinstance(candidate, HyperCandidate):
            return candidate.members
        return (candidate.a, candidate.b)

    def _choose_hyper_batch(
        self,
        regions: Dict[int, Region],
        pair_cache: Dict[Tuple[int, int], Candidate],
        counters: dict,
    ) -> List[CandidateLike]:
        # Evaluate mature executable hyperedges first. Pairwise candidate racing
        # is skipped in generations where positive hyper-organs exist.
        triples = self._triple_motifs(regions)
        triples.sort(key=lambda t: self._triple_prefilter_key(regions, t), reverse=True)
        triple_budget = min(
            len(triples),
            max(self.morph_shortlist, len(regions) // 2),
        )
        hyper_candidates: List[HyperCandidate] = []
        for triple in triples[:triple_budget]:
            c = self._evaluate_triple(regions, triple, pair_cache, counters)
            if c is not None:
                hyper_candidates.append(c)

        positive_hyper = [c for c in hyper_candidates if c.score > 0]
        all_candidates: List[CandidateLike]
        if positive_hyper:
            all_candidates = positive_hyper
        else:
            pair_list = self._candidate_pairs(regions, executable_only=True)
            pair_candidates = (
                self._choose_batch(regions, pair_list, pair_cache, counters)
                if pair_list else []
            )
            all_candidates = [
                c for c in pair_candidates if c.result is not None
            ] + hyper_candidates
        if not all_candidates:
            return []
        all_candidates.sort(
            key=lambda c: (c.score, len(self._members(c))), reverse=True
        )
        selected: List[CandidateLike] = []
        used: Set[int] = set()
        for candidate in all_candidates:
            members = self._members(candidate)
            if candidate.score <= 0 or any(x in used for x in members):
                continue
            selected.append(candidate)
            used.update(members)
        if not selected:
            selected = [all_candidates[0]]
        return selected

    @staticmethod
    def _append_trace(
        trace: List[dict], generation: int, a: Region, b: Region,
        result: CompositionResult, score: float, oracle_clusters: Set[frozenset[int]],
        kind: str,
    ) -> None:
        union = a.leaves | b.leaves
        trace.append({
            "generation": generation,
            "kind": kind,
            "left_leaves": len(a.leaves),
            "right_leaves": len(b.leaves),
            "union_leaves": len(union),
            "left_states": a.machine.n_states,
            "right_states": b.machine.n_states,
            "raw_states": result.raw.n_states,
            "quotient_states": result.quotient.n_states,
            "inputs": len(result.quotient.inputs),
            "outputs": len(result.quotient.outputs),
            "reachability_gain_bits": result.reachability_gain_bits,
            "quotient_gain_bits": result.quotient_gain_bits,
            "total_gain_bits": result.total_gain_bits,
            "score": score,
            "homomorphism_certificate": result.certificate.verified_homomorphism,
            "minimality_certificate": result.certificate.verified_minimal,
            "oracle_cluster": union in oracle_clusters,
        })

    def run(self, strategy: str = "morph_hyper_batch") -> Tuple[Optional[Region], RunStats]:
        if strategy != "morph_hyper_batch":
            return super().run(strategy)

        start = perf_counter()
        regions = self._initial_regions()
        pair_cache: Dict[Tuple[int, int], Candidate] = {}
        recovered: Set[frozenset[int]] = set()
        trace: List[dict] = []
        counters = {
            "candidate_evaluations": 0,
            "oversized_candidates": 0,
            "all_transition_evaluations": 0,
            "selected_transition_evaluations": 0,
            "peak_candidate_raw_states": 0,
            "peak_selected_raw_states": 0,
            "peak_quotient_states": max((r.machine.n_states for r in regions.values()), default=0),
            "peak_description_bits": max((r.machine.description_bits() for r in regions.values()), default=0),
            "selected_total_gain_bits": 0.0,
            "candidate_trace": [],
        }
        generations = 0
        failure = ""

        while len(regions) > 1:
            selected = self._choose_hyper_batch(regions, pair_cache, counters)
            if not selected:
                failure = "all available pair and hyperedge organs exceeded the resource budget"
                break
            generations += 1
            merged_ids: Set[int] = set()
            new_regions: List[Region] = []

            for candidate in selected:
                members = self._members(candidate)
                if any(x in merged_ids or x not in regions for x in members):
                    continue
                if isinstance(candidate, Candidate):
                    if candidate.result is None:
                        continue
                    a, b = regions[candidate.a], regions[candidate.b]
                    result = candidate.result
                    rid = self._next_rid
                    self._next_rid += 1
                    final = Region(rid, a.leaves | b.leaves, result.quotient, (a, b), result)
                    new_regions.append(final)
                    merged_ids.update((candidate.a, candidate.b))
                    recovered.add(final.leaves)
                    counters["selected_transition_evaluations"] += result.transition_evaluations
                    counters["peak_selected_raw_states"] = max(
                        counters["peak_selected_raw_states"], result.raw.n_states
                    )
                    counters["selected_total_gain_bits"] += result.total_gain_bits
                    self._append_trace(
                        trace, generations, a, b, result, candidate.score,
                        self.spec.oracle_clusters, "pair",
                    )
                    continue

                first_a_id, first_b_id = candidate.first_pair
                third_id = candidate.third
                first_a = regions[first_a_id]
                first_b = regions[first_b_id]
                third = regions[third_id]
                rid1 = self._next_rid
                self._next_rid += 1
                intermediate = Region(
                    rid1,
                    first_a.leaves | first_b.leaves,
                    candidate.first_result.quotient,
                    (first_a, first_b),
                    candidate.first_result,
                )
                rid2 = self._next_rid
                self._next_rid += 1
                final = Region(
                    rid2,
                    intermediate.leaves | third.leaves,
                    candidate.second_result.quotient,
                    (intermediate, third),
                    candidate.second_result,
                )
                new_regions.append(final)
                merged_ids.update(candidate.members)
                recovered.add(intermediate.leaves)
                recovered.add(final.leaves)
                counters["selected_transition_evaluations"] += (
                    candidate.first_result.transition_evaluations
                    + candidate.second_result.transition_evaluations
                )
                counters["peak_selected_raw_states"] = max(
                    counters["peak_selected_raw_states"],
                    candidate.first_result.raw.n_states,
                    candidate.second_result.raw.n_states,
                )
                counters["selected_total_gain_bits"] += (
                    candidate.first_result.total_gain_bits
                    + candidate.second_result.total_gain_bits
                )
                self._append_trace(
                    trace, generations, first_a, first_b,
                    candidate.first_result, candidate.score,
                    self.spec.oracle_clusters, "hyper-nucleus-1",
                )
                self._append_trace(
                    trace, generations, intermediate, third,
                    candidate.second_result, candidate.score,
                    self.spec.oracle_clusters, "hyper-nucleus-2",
                )

            if not new_regions:
                failure = "selected hyper batch contained no applicable organ"
                break
            for rid in merged_ids:
                regions.pop(rid, None)
            for region in new_regions:
                regions[region.rid] = region
            for key in [k for k in pair_cache if k[0] in merged_ids or k[1] in merged_ids]:
                pair_cache.pop(key, None)

        root = next(iter(regions.values())) if len(regions) == 1 and not failure else None
        oracle_count = len(self.spec.oracle_clusters)
        recovered_count = len(recovered & self.spec.oracle_clusters)
        stats = RunStats(
            strategy=strategy,
            success=root is not None,
            final_regions=len(regions),
            final_states=root.machine.n_states if root else -1,
            final_inputs=len(root.machine.inputs) if root else -1,
            final_outputs=len(root.machine.outputs) if root else -1,
            wall_seconds=perf_counter() - start,
            generations=generations,
            merges=len(trace),
            candidate_evaluations=counters["candidate_evaluations"],
            oversized_candidates=counters["oversized_candidates"],
            all_transition_evaluations=counters["all_transition_evaluations"],
            selected_transition_evaluations=counters["selected_transition_evaluations"],
            peak_candidate_raw_states=counters["peak_candidate_raw_states"],
            peak_selected_raw_states=counters["peak_selected_raw_states"],
            peak_quotient_states=counters["peak_quotient_states"],
            peak_description_bits=counters["peak_description_bits"],
            selected_total_gain_bits=counters["selected_total_gain_bits"],
            recovered_oracle_clusters=recovered_count,
            oracle_cluster_count=oracle_count,
            cluster_recall=(recovered_count / oracle_count if oracle_count else 1.0),
            merge_trace=trace,
            candidate_trace=counters["candidate_trace"],
            failure=failure,
        )
        return root, stats
