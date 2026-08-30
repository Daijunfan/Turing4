from __future__ import annotations

import argparse
import csv
import json
from math import log10
from pathlib import Path
from typing import List

from morph_exact.core import equivalent_machines
from morph_exact.engine import MorphEngine
from morph_exact.generators import modular_sum_tree_network, parity_tree_network
from morph_exact.hyper import MorphHyperEngine
from morph_exact.reference import monolithic_compose


def certificate_ok(trace: List[dict]) -> bool:
    return all(x["homomorphism_certificate"] and x["minimality_certificate"] for x in trace)


def run_parity(depth: int, mode: str, seed: int, state_cap: int,
               transition_cap: int, shortlist: int) -> dict:
    spec = parity_tree_network(depth, input_bits=3, seed=seed, decoy_degree=4)
    if mode == "hyper":
        root, stats = MorphHyperEngine(
            spec, state_cap, transition_cap, shortlist, seed
        ).run("morph_hyper_batch")
    else:
        root, stats = MorphEngine(
            spec, state_cap, transition_cap, shortlist, seed
        ).run("morph_batch")
    independent = None
    if root is not None and depth <= 3:
        independent = equivalent_machines(
            root.machine,
            monolithic_compose(spec, max_states=1_000_000,
                               max_transition_evaluations=20_000_000),
        )
    return {
        "family": "registered_xor_tree",
        "mode": mode,
        "depth": depth,
        "components": len(spec.leaf_machines),
        "cartesian_state_space": f"2^{len(spec.leaf_machines)}",
        "success": stats.success,
        "failure": stats.failure,
        "wall_seconds": stats.wall_seconds,
        "final_states": stats.final_states,
        "generations": stats.generations,
        "merges": stats.merges,
        "cluster_recall": stats.cluster_recall,
        "candidate_evaluations": stats.candidate_evaluations,
        "all_transition_evaluations": stats.all_transition_evaluations,
        "peak_candidate_raw_states": stats.peak_candidate_raw_states,
        "peak_selected_raw_states": stats.peak_selected_raw_states,
        "certificates_all": certificate_ok(stats.merge_trace),
        "small_monolithic_exact": independent,
    }


def run_modsum(depth: int, mode: str, seed: int, state_cap: int,
               transition_cap: int, shortlist: int) -> dict:
    spec = modular_sum_tree_network(depth, modulus=3, seed=seed, decoy_degree=4)
    if mode == "hyper":
        root, stats = MorphHyperEngine(
            spec, state_cap, transition_cap, shortlist, seed
        ).run("morph_hyper_batch")
    else:
        root, stats = MorphEngine(
            spec, state_cap, transition_cap, shortlist, seed
        ).run("morph_batch")
    independent = None
    if root is not None and depth <= 2:
        independent = equivalent_machines(
            root.machine,
            monolithic_compose(spec, max_states=1_000_000,
                               max_transition_evaluations=20_000_000),
        )
    return {
        "family": "registered_mod3_sum_tree",
        "mode": mode,
        "depth": depth,
        "components": len(spec.leaf_machines),
        "cartesian_state_space": f"3^{len(spec.leaf_machines)}",
        "cartesian_log10": len(spec.leaf_machines) * log10(3),
        "success": stats.success,
        "failure": stats.failure,
        "wall_seconds": stats.wall_seconds,
        "final_states": stats.final_states,
        "generations": stats.generations,
        "merges": stats.merges,
        "cluster_recall": stats.cluster_recall,
        "candidate_evaluations": stats.candidate_evaluations,
        "all_transition_evaluations": stats.all_transition_evaluations,
        "peak_candidate_raw_states": stats.peak_candidate_raw_states,
        "peak_selected_raw_states": stats.peak_selected_raw_states,
        "certificates_all": certificate_ok(stats.merge_trace),
        "small_monolithic_exact": independent,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--family", choices=["parity", "modsum"], required=True)
    parser.add_argument("--mode", choices=["pair", "hyper"], default="hyper")
    parser.add_argument("--depths", nargs="+", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--state-cap", type=int, default=200_000)
    parser.add_argument("--transition-cap", type=int, default=3_000_000)
    parser.add_argument("--shortlist", type=int, default=32)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    rows = []
    for depth in args.depths:
        if args.family == "parity":
            row = run_parity(depth, args.mode, args.seed, args.state_cap,
                             args.transition_cap, args.shortlist)
        else:
            row = run_modsum(depth, args.mode, args.seed, args.state_cap,
                             args.transition_cap, args.shortlist)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
