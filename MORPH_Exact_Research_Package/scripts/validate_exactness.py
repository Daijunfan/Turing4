from __future__ import annotations

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from morph_exact.core import (
    Machine,
    canonical_minimize,
    compose_and_minimize,
    equivalent_machines,
    independent_is_minimal,
    machine_isomorphic,
    verify_quotient_homomorphism,
)
from morph_exact.engine import MorphEngine
from morph_exact.generators import hidden_morphology, split_with_hidden_gauge
from morph_exact.reference import monolithic_compose


def random_machine(seed: int) -> Machine:
    rng = np.random.default_rng(seed)
    states = int(rng.integers(2, 11))
    inputs = int(rng.integers(1, 4))
    outputs = int(rng.integers(1, 3))
    raw = Machine(
        f"rnd{seed}",
        tuple(f"rnd{seed}.i{j}" for j in range(inputs)),
        tuple(f"rnd{seed}.o{j}" for j in range(outputs)),
        0,
        rng.integers(0, states, size=(states, 1 << inputs), dtype=np.int32),
        rng.integers(0, 2, size=(states, outputs), dtype=np.uint8),
    )
    return canonical_minimize(raw)[0]



def random_machine_small(seed: int) -> Machine:
    rng = np.random.default_rng(seed)
    states = int(rng.integers(2, 6))
    inputs = int(rng.integers(1, 3))
    outputs = int(rng.integers(1, 3))
    raw = Machine(
        f"small{seed}",
        tuple(f"small{seed}.i{j}" for j in range(inputs)),
        tuple(f"small{seed}.o{j}" for j in range(outputs)),
        0,
        rng.integers(0, states, size=(states, 1 << inputs), dtype=np.int32),
        rng.integers(0, 2, size=(states, outputs), dtype=np.uint8),
    )
    return canonical_minimize(raw)[0]

def main(out: Path, random_minimizers: int, split_trials: int, hierarchy_trials: int) -> None:
    started = perf_counter()
    result = {
        "random_minimizers": 0,
        "split_reifications": 0,
        "hierarchy_vs_monolithic": 0,
        "failures": [],
    }

    for seed in range(random_minimizers):
        m = random_machine(seed)
        q, mapping = canonical_minimize(m)
        ok = (
            verify_quotient_homomorphism(m, q, mapping)
            and independent_is_minimal(q)
            and equivalent_machines(m, q)
        )
        if not ok:
            result["failures"].append({"kind": "minimizer", "seed": seed})
            break
        result["random_minimizers"] += 1

    for seed in range(split_trials):
        parent = random_machine(100_000 + seed)
        left, right = split_with_hidden_gauge(parent, f"stress.{seed}")
        c = compose_and_minimize(
            left, right, set(parent.outputs),
            max_states=200_000,
            max_transition_evaluations=4_000_000,
        )
        ok = (
            c.certificate.verified_homomorphism
            and c.certificate.verified_minimal
            and machine_isomorphic(c.quotient, parent)
        )
        if not ok:
            result["failures"].append({"kind": "split", "seed": seed})
            break
        result["split_reifications"] += 1

    for seed in range(hierarchy_trials):
        parent = random_machine_small(200_000 + seed)
        depth = 2 + (seed % 2)
        spec = hidden_morphology(parent, depth, seed=seed, decoy_degree=4)
        root, stats = MorphEngine(
            spec,
            max_candidate_states=200_000,
            max_candidate_transition_evaluations=4_000_000,
            morph_shortlist=8,
            seed=seed,
        ).run("morph_batch")
        if root is None:
            result["failures"].append({"kind": "hierarchy", "seed": seed, "failure": stats.failure})
            break
        mono = monolithic_compose(
            spec,
            max_states=500_000,
            max_transition_evaluations=20_000_000,
        )
        ok = (
            equivalent_machines(root.machine, mono)
            and machine_isomorphic(root.machine, parent)
            and all(x["homomorphism_certificate"] and x["minimality_certificate"] for x in stats.merge_trace)
        )
        if not ok:
            result["failures"].append({"kind": "hierarchy", "seed": seed})
            break
        result["hierarchy_vs_monolithic"] += 1

    result["elapsed_seconds"] = perf_counter() - started
    result["all_passed"] = not result["failures"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("results/exactness.json"))
    parser.add_argument("--random-minimizers", type=int, default=10_000)
    parser.add_argument("--split-trials", type=int, default=1_000)
    parser.add_argument("--hierarchy-trials", type=int, default=200)
    args = parser.parse_args()
    main(args.out, args.random_minimizers, args.split_trials, args.hierarchy_trials)
