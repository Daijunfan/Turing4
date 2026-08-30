from __future__ import annotations

from dataclasses import dataclass, field
from math import log2
from random import Random
from time import perf_counter
from typing import Dict, List, Optional, Set, Tuple

from .core import (
    CompositionResult,
    CompositionTooLarge,
    NetworkSpec,
    Region,
    compose_and_minimize,
)


@dataclass
class Candidate:
    a: int
    b: int
    score: float
    result: Optional[CompositionResult]
    reason: str = ""


@dataclass
class RunStats:
    strategy: str
    success: bool
    final_regions: int
    final_states: int
    final_inputs: int
    final_outputs: int
    wall_seconds: float
    generations: int
    merges: int
    candidate_evaluations: int
    oversized_candidates: int
    all_transition_evaluations: int
    selected_transition_evaluations: int
    peak_candidate_raw_states: int
    peak_selected_raw_states: int
    peak_quotient_states: int
    peak_description_bits: int
    selected_total_gain_bits: float
    recovered_oracle_clusters: int
    oracle_cluster_count: int
    cluster_recall: float
    merge_trace: List[dict] = field(default_factory=list)
    candidate_trace: List[dict] = field(default_factory=list)
    failure: str = ""


class MorphEngine:
    """MORPH-Exact: proof-carrying recursive behavioral re-atomization."""

    def __init__(
        self,
        spec: NetworkSpec,
        max_candidate_states: int = 200_000,
        max_candidate_transition_evaluations: int = 2_000_000,
        morph_shortlist: int = 16,
        seed: int = 0,
    ) -> None:
        self.spec = spec
        self.max_candidate_states = max_candidate_states
        self.max_candidate_transition_evaluations = max_candidate_transition_evaluations
        self.morph_shortlist = morph_shortlist
        self.rng = Random(seed)
        self._next_rid = max(spec.leaf_machines, default=-1) + 1

    def _initial_regions(self) -> Dict[int, Region]:
        return {
            lid: Region(lid, frozenset({lid}), machine)
            for lid, machine in self.spec.leaf_machines.items()
        }

    def _candidate_pairs(self, regions: Dict[int, Region], executable_only: bool = False) -> List[Tuple[int, int]]:
        # Build the quotient contact graph in O(number of primitive contacts)
        # rather than testing every region pair against every primitive edge.
        leaf_to_region: Dict[int, int] = {}
        for rid, region in regions.items():
            for leaf in region.leaves:
                leaf_to_region[leaf] = rid
        pairs: Set[Tuple[int, int]] = set()
        edge_source = self.spec.signal_edges if executable_only else self.spec.contact_edges
        for x, y in edge_source:
            a = leaf_to_region[x]
            b = leaf_to_region[y]
            if a != b:
                pairs.add((min(a, b), max(a, b)))
        if not pairs and len(regions) > 1:
            ids = sorted(regions)
            pairs = {(ids[i], ids[i + 1]) for i in range(len(ids) - 1)}
        return sorted(pairs)

    def _prefilter_key(self, a: Region, b: Region) -> Tuple[int, int, int, int]:
        produced = set(a.machine.outputs) | set(b.machine.outputs)
        union_inputs = (set(a.machine.inputs) | set(b.machine.inputs)) - produced
        keep = self.spec.keep_outputs(a.leaves | b.leaves) & produced
        boundary_ports = len(union_inputs) + len(keep)
        before_ports = (
            len(a.machine.inputs) + len(b.machine.inputs)
            + len(a.machine.outputs) + len(b.machine.outputs)
        )
        internalized = before_ports - boundary_ports
        return (
            self.spec.semantic_crossing_count(a, b),
            internalized,
            -boundary_ports,
            -(a.machine.n_states * b.machine.n_states),
        )

    def _evaluate(self, a: Region, b: Region) -> Candidate:
        keep = self.spec.keep_outputs(a.leaves | b.leaves)
        try:
            result = compose_and_minimize(
                a.machine,
                b.machine,
                keep,
                max_states=self.max_candidate_states,
                max_transition_evaluations=self.max_candidate_transition_evaluations,
            )
        except CompositionTooLarge as exc:
            return Candidate(a.rid, b.rid, float("-inf"), None, str(exc))
        boundary_growth = max(
            0,
            len(result.quotient.inputs)
            - max(len(a.machine.inputs), len(b.machine.inputs)),
        )
        build = max(1, result.raw.n_states * result.raw.alphabet_size)
        score = (
            result.total_gain_bits
            + 0.40 * result.quotient_gain_bits
            - 0.20 * boundary_growth
            - 0.0125 * log2(build + 1)
        )
        return Candidate(a.rid, b.rid, score, result)

    @staticmethod
    def _record_candidate(c: Candidate, counters: dict) -> None:
        counters["candidate_evaluations"] += 1
        if c.result is None:
            counters["oversized_candidates"] += 1
            counters["candidate_trace"].append({
                "left_region": c.a,
                "right_region": c.b,
                "raw_states": None,
                "quotient_states": None,
                "oversized": True,
                "reason": c.reason,
            })
            return
        result = c.result
        counters["candidate_trace"].append({
            "left_region": c.a,
            "right_region": c.b,
            "raw_states": result.raw.n_states,
            "quotient_states": result.quotient.n_states,
            "raw_inputs": len(result.raw.inputs),
            "quotient_inputs": len(result.quotient.inputs),
            "transition_evaluations": result.transition_evaluations,
            "oversized": False,
        })
        counters["all_transition_evaluations"] += result.transition_evaluations
        counters["peak_candidate_raw_states"] = max(
            counters["peak_candidate_raw_states"], result.raw.n_states
        )
        counters["peak_quotient_states"] = max(
            counters["peak_quotient_states"], result.quotient.n_states
        )
        counters["peak_description_bits"] = max(
            counters["peak_description_bits"],
            result.raw.description_bits(),
            result.quotient.description_bits(),
        )

    def _rank_pairs(self, regions: Dict[int, Region], pairs: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        return sorted(
            pairs,
            key=lambda p: self._prefilter_key(regions[p[0]], regions[p[1]]),
            reverse=True,
        )

    def _evaluate_pool(
        self,
        regions: Dict[int, Region],
        ranked: List[Tuple[int, int]],
        budget: int,
        cache: Dict[Tuple[int, int], Candidate],
        counters: dict,
    ) -> List[Candidate]:
        evaluated: List[Candidate] = []
        for a, b in ranked[:budget]:
            key = (min(a, b), max(a, b))
            c = cache.get(key)
            if c is None:
                c = self._evaluate(regions[a], regions[b])
                cache[key] = c
                self._record_candidate(c, counters)
            evaluated.append(c)
        return evaluated

    def _choose_batch(
        self,
        regions: Dict[int, Region],
        pairs: List[Tuple[int, int]],
        cache: Dict[Tuple[int, int], Candidate],
        counters: dict,
    ) -> List[Candidate]:
        ranked = self._rank_pairs(regions, pairs)
        real = [p for p in ranked if self.spec.semantic_crossing_count(regions[p[0]], regions[p[1]]) > 0]
        pool = real if real else ranked
        budget = min(len(pool), max(self.morph_shortlist, len(regions) // 2))
        candidates = self._evaluate_pool(regions, pool, budget, cache, counters)
        finite = [c for c in candidates if c.result is not None]
        if not finite and budget < len(pool):
            candidates += self._evaluate_pool(regions, pool, len(pool), cache, counters)
            finite = [c for c in candidates if c.result is not None]
        if not finite:
            return []
        finite.sort(key=lambda c: c.score, reverse=True)
        used: Set[int] = set()
        selected: List[Candidate] = []
        for c in finite:
            if c.score <= 0:
                continue
            if c.a in used or c.b in used:
                continue
            selected.append(c)
            used.add(c.a)
            used.add(c.b)
        if not selected:
            selected = [finite[0]]
        return selected

    def _choose_single(
        self,
        strategy: str,
        regions: Dict[int, Region],
        pairs: List[Tuple[int, int]],
        cache: Dict[Tuple[int, int], Candidate],
        counters: dict,
    ) -> List[Candidate]:
        if strategy == "random":
            pair = self.rng.choice(pairs)
        elif strategy == "smallest":
            pair = min(pairs, key=lambda p: regions[p[0]].machine.n_states * regions[p[1]].machine.n_states)
        elif strategy == "structural":
            pair = max(
                pairs,
                key=lambda p: (
                    self.spec.crossing_contact_count(regions[p[0]], regions[p[1]])
                    / (1 + self.spec.boundary_contact_count(regions[p[0]].leaves | regions[p[1]].leaves)),
                    self.spec.crossing_contact_count(regions[p[0]], regions[p[1]]),
                    -(regions[p[0]].machine.n_states * regions[p[1]].machine.n_states),
                ),
            )
        elif strategy == "morph_sequential":
            ranked = self._rank_pairs(regions, pairs)
            real = [p for p in ranked if self.spec.semantic_crossing_count(regions[p[0]], regions[p[1]]) > 0]
            pool = real if real else ranked
            budget = min(len(pool), max(1, self.morph_shortlist))
            candidates = self._evaluate_pool(regions, pool, budget, cache, counters)
            finite = [c for c in candidates if c.result is not None]
            if not finite and budget < len(pool):
                candidates += self._evaluate_pool(regions, pool, len(pool), cache, counters)
                finite = [c for c in candidates if c.result is not None]
            return [max(finite, key=lambda c: c.score)] if finite else []
        else:
            raise KeyError(strategy)
        key = (min(pair), max(pair))
        c = cache.get(key)
        if c is None:
            c = self._evaluate(regions[pair[0]], regions[pair[1]])
            cache[key] = c
            self._record_candidate(c, counters)
        return [c] if c.result is not None else []

    def run(self, strategy: str = "morph_batch") -> Tuple[Optional[Region], RunStats]:
        start = perf_counter()
        regions = self._initial_regions()
        cache: Dict[Tuple[int, int], Candidate] = {}
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
            pairs = self._candidate_pairs(
                regions,
                executable_only=(strategy in {"morph_batch", "morph_sequential"}),
            )
            if not pairs:
                failure = "no candidate pairs"
                break
            if strategy == "morph_batch":
                selected = self._choose_batch(regions, pairs, cache, counters)
            else:
                selected = self._choose_single(strategy, regions, pairs, cache, counters)
            if not selected:
                failure = "all available merges exceeded the resource budget"
                break

            # Candidates are pairwise disjoint in batch mode, so each exact summary
            # was computed against the same immutable generation and can be committed.
            generations += 1
            merged_ids: Set[int] = set()
            new_regions: List[Region] = []
            for c in selected:
                if c.a in merged_ids or c.b in merged_ids:
                    continue
                if c.a not in regions or c.b not in regions or c.result is None:
                    continue
                a = regions[c.a]
                b = regions[c.b]
                result = c.result
                union = a.leaves | b.leaves
                rid = self._next_rid
                self._next_rid += 1
                new_region = Region(rid, union, result.quotient, (a, b), result)
                new_regions.append(new_region)
                merged_ids.update((c.a, c.b))
                recovered.add(union)
                counters["selected_transition_evaluations"] += result.transition_evaluations
                counters["peak_selected_raw_states"] = max(
                    counters["peak_selected_raw_states"], result.raw.n_states
                )
                counters["selected_total_gain_bits"] += result.total_gain_bits
                trace.append({
                    "generation": generations,
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
                    "score": c.score,
                    "homomorphism_certificate": result.certificate.verified_homomorphism,
                    "minimality_certificate": result.certificate.verified_minimal,
                    "oracle_cluster": union in self.spec.oracle_clusters,
                })

            if not new_regions:
                failure = "selected batch contained no applicable merge"
                break
            for rid in merged_ids:
                regions.pop(rid, None)
            for region in new_regions:
                regions[region.rid] = region
            for key in [k for k in cache if k[0] in merged_ids or k[1] in merged_ids]:
                cache.pop(key, None)

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
