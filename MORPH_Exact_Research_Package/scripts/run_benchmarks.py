from __future__ import annotations

import argparse
import json
from math import log2
from pathlib import Path
from typing import Iterable, List

import pandas as pd

from morph_exact.core import machine_isomorphic
from morph_exact.engine import MorphEngine
from morph_exact.generators import hidden_morphology, root_family
from morph_exact.kiss2 import load_kiss2


def root_by_name(name: str):
    if name == "bbara":
        return load_kiss2(Path(__file__).parents[1] / "benchmarks" / "bbara.kiss2", "bbara")
    return root_family(name)


def run_one(family: str, depth: int, seed: int, strategy: str,
            decoy_degree: int, state_cap: int, transition_cap: int,
            shortlist: int) -> dict:
    target = root_by_name(family)
    spec = hidden_morphology(target, depth, seed=seed, decoy_degree=decoy_degree)
    primitive_states = [m.n_states for m in spec.leaf_machines.values()]
    engine = MorphEngine(
        spec,
        max_candidate_states=state_cap,
        max_candidate_transition_evaluations=transition_cap,
        morph_shortlist=shortlist,
        seed=seed,
    )
    root, stats = engine.run(strategy)
    exact = bool(root is not None and machine_isomorphic(root.machine, target))
    certs = bool(root is not None and all(
        x["homomorphism_certificate"] and x["minimality_certificate"]
        for x in stats.merge_trace
    ))
    row = {
        "family": family,
        "depth": depth,
        "leaves": 1 << depth,
        "seed": seed,
        "strategy": strategy,
        "decoy_degree": decoy_degree,
        "root_states": target.n_states,
        "root_inputs": len(target.inputs),
        "root_outputs": len(target.outputs),
        "primitive_state_sum": sum(primitive_states),
        "primitive_state_max": max(primitive_states),
        "primitive_input_max": max(len(m.inputs) for m in spec.leaf_machines.values()),
        "cartesian_log2_states": sum(log2(x) for x in primitive_states),
        "exact_root": exact,
        "all_certificates": certs,
        **{k: v for k, v in stats.__dict__.items() if k != "merge_trace"},
    }
    print(json.dumps({
        k: row[k] for k in (
            "family", "depth", "seed", "strategy", "success", "exact_root",
            "cluster_recall", "peak_selected_raw_states", "peak_candidate_raw_states",
            "wall_seconds", "failure",
        )
    }, ensure_ascii=False), flush=True)
    return row


def scenario_scaling() -> List[dict]:
    rows = []
    for depth in range(4, 10):
        rows.append(run_one("parity", depth, 0, "morph_batch", 4, 200_000, 4_000_000, 8))
    for depth in range(2, 7):
        rows.append(run_one("bbara", depth, 0, "morph_batch", 4, 200_000, 4_000_000, 8))
    return rows


def scenario_cross_family() -> List[dict]:
    rows = []
    for family in ["parity", "counter", "pattern", "handshake", "traffic", "abp", "mixed"]:
        for seed in range(3):
            rows.append(run_one(family, 6, seed, "morph_batch", 4, 200_000, 4_000_000, 8))
    return rows


def scenario_baselines() -> List[dict]:
    rows = []
    for family in ["parity", "counter", "handshake"]:
        for depth in [3, 4, 5, 6]:
            for seed in range(5):
                for strategy in ["morph_batch", "structural", "smallest", "random"]:
                    rows.append(run_one(
                        family, depth, seed, strategy, 4,
                        state_cap=50_000,
                        transition_cap=300_000,
                        shortlist=8,
                    ))
    return rows


def main(out_dir: Path, scenarios: Iterable[str]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    all_rows: List[dict] = []
    for scenario in scenarios:
        if scenario == "scaling":
            rows = scenario_scaling()
        elif scenario == "cross_family":
            rows = scenario_cross_family()
        elif scenario == "baselines":
            rows = scenario_baselines()
        else:
            raise KeyError(scenario)
        pd.DataFrame(rows).to_csv(out_dir / f"{scenario}.csv", index=False)
        all_rows.extend(rows)
    pd.DataFrame(all_rows).to_csv(out_dir / "all_benchmarks.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("results"))
    parser.add_argument("--scenarios", nargs="+", default=["scaling", "cross_family", "baselines"])
    args = parser.parse_args()
    main(args.out_dir, args.scenarios)
