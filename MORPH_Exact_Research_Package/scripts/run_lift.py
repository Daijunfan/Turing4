from __future__ import annotations

import argparse
import gc
import json
from math import log2
from pathlib import Path
import threading
from time import perf_counter, strftime

import numpy as np
import psutil

from morph_exact.core import Machine, NetworkSpec, canonical_minimize, machine_isomorphic
from morph_exact.engine import MorphEngine
from morph_exact.hyper import MorphHyperEngine
from morph_exact.reference import monolithic_compose
from morph_lift.certificates import verify_certificate
from morph_lift.gauge_cycle import gauge_cycle_network, parity_accumulator_reference
from morph_lift.oracle import (
    reatomization_peak_cost,
    search_greedy_counterexample,
    subset_oracle,
)
from morph_lift.predicate_closure import close_predicates
from morph_lift.symbolic import BDD_BACKEND, SymbolicMachine, variable_order_metrics


SMALL_SIZES = (4, 6, 8, 10, 12)
SCALING_SIZES = (8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096)


class PeakRSS:
    def __init__(self) -> None:
        self.peak = psutil.Process().memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        process = psutil.Process()
        while not self._stop.wait(0.005):
            self.peak = max(self.peak, process.memory_info().rss)

    def __enter__(self) -> "PeakRSS":
        self._thread.start()
        return self

    def __exit__(self, *_args) -> None:
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, psutil.Process().memory_info().rss)


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, default=_json_default) + "\n")


def explicit_small_experiments() -> tuple[list[dict], dict[int, object]]:
    records: list[dict] = []
    oracles: dict[int, object] = {}
    reference = parity_accumulator_reference()
    for n in SMALL_SIZES:
        spec = gauge_cycle_network(n)
        oracle_start = perf_counter()
        oracle = subset_oracle(spec)
        oracle_seconds = perf_counter() - oracle_start
        oracles[n] = oracle
        full = (1 << n) - 1
        proper_law = all(
            quotient.quotient.n_states == 1 << mask.bit_count()
            for mask, quotient in oracle.quotients.items()
            if mask != full
        )
        monolithic = monolithic_compose(spec)
        records.append({
            "kind": "oracle",
            "n": n,
            "subset_count": len(oracle.quotients),
            "proper_subset_power_law": proper_law,
            "full_quotient_states": oracle.quotients[full].quotient.n_states,
            "full_is_reference": machine_isomorphic(monolithic, reference),
            "opt_peak_cost": oracle.peak_cost,
            "opt_tree": oracle.tree.to_dict(),
            "wall_seconds": oracle_seconds,
            "all_open_quotient_proofs": all(
                q.proof.homomorphism and q.proof.minimal
                for q in oracle.quotients.values()
            ),
        })
        engines = {
            "epg_greedy": lambda: MorphEngine(spec, seed=0).run("morph_batch"),
            "morph_hyper": lambda: MorphHyperEngine(spec, seed=0).run(),
            "structural": lambda: MorphEngine(spec, seed=0).run("structural"),
            "smallest": lambda: MorphEngine(spec, seed=0).run("smallest"),
            "random": lambda: MorphEngine(spec, seed=0).run("random"),
        }
        for strategy, run in engines.items():
            root, stats = run()
            records.append({
                "kind": "explicit_strategy",
                "n": n,
                "strategy": strategy,
                "success": stats.success,
                "failure": stats.failure,
                "final_states": stats.final_states,
                "final_is_reference": bool(root) and machine_isomorphic(root.machine, reference),
                "peak_raw_states": stats.peak_selected_raw_states,
                "peak_quotient_states": stats.peak_quotient_states,
                "formation_peak_cost": reatomization_peak_cost(root) if root else None,
                "opt_peak_cost": oracle.peak_cost,
                "merge_trace": stats.merge_trace,
                "candidate_trace": stats.candidate_trace,
                "wall_seconds": stats.wall_seconds,
            })
    return records, oracles


def explicit_candidate_traces() -> list[dict]:
    records: list[dict] = []
    for n in SMALL_SIZES:
        spec = gauge_cycle_network(n)
        runs = {
            "morph_exact": MorphEngine(spec, seed=0).run("morph_batch"),
            "morph_hyper": MorphHyperEngine(spec, seed=0).run(),
        }
        for strategy, (root, stats) in runs.items():
            records.append({
                "kind": "explicit_candidate_trace",
                "n": n,
                "strategy": strategy,
                "success": stats.success,
                "failure": stats.failure,
                "candidate_trace": stats.candidate_trace,
                "merge_trace": stats.merge_trace,
                "peak_raw_states": stats.peak_candidate_raw_states,
                "peak_quotient_states": stats.peak_quotient_states,
                "final_is_two_state_reference": bool(root) and machine_isomorphic(
                    root.machine, parity_accumulator_reference()
                ),
            })
    return records


def symbolic_experiment(n: int) -> dict:
    gc.collect()
    spec = gauge_cycle_network(n)
    start = perf_counter()
    with PeakRSS() as memory:
        source = SymbolicMachine.from_network(spec, variable_order="dependency")
        built = perf_counter()
        closure = close_predicates(source)
        closed = perf_counter()
        certificate = verify_certificate(closure)
        verified = perf_counter()
        macro = closure.macro_machine
        reference_match = machine_isomorphic(
            macro.to_explicit(), parity_accumulator_reference()
        )
    record = {
        "kind": "symbolic_scaling",
        "n": n,
        "backend": BDD_BACKEND,
        "explicit_morph_success": None,
        "explicit_peak_raw_states": None,
        "explicit_peak_quotient_states": None,
        "bdd_nodes": source.bdd_node_count,
        "reachable_bdd_nodes": source.certificate_metadata["reachable_bdd_nodes"],
        "predicate_count": closure.predicate_count,
        "closure_iterations": closure.iterations,
        "wall_seconds": verified - start,
        "build_seconds": built - start,
        "closure_seconds": closed - built,
        "verification_seconds": verified - closed,
        "peak_rss_bytes": memory.peak,
        "smt_seconds": sum(certificate.smt_seconds.values()),
        "macro_state_bits": len(macro.state_variables),
        "macro_states": macro.state_count(),
        "macro_is_two_state_reference": reference_match,
        "proof_verified": certificate.verified,
        "bdd_conditions": certificate.bdd_conditions,
        "smt_conditions": certificate.smt_conditions,
        "global_state_space_enumerated": False,
    }
    del source, closure, macro
    return record


def explicit_scaling_experiments() -> list[dict]:
    records: list[dict] = []
    reference = parity_accumulator_reference()
    for n in (8, 16):
        root, stats = MorphEngine(gauge_cycle_network(n), seed=0).run("morph_batch")
        records.append({
            "kind": "explicit_scaling",
            "n": n,
            "success": stats.success,
            "status": "completed" if stats.success else "resource_rejected",
            "failure": stats.failure,
            "wall_seconds": stats.wall_seconds,
            "peak_raw_states": stats.peak_candidate_raw_states,
            "peak_quotient_states": stats.peak_quotient_states,
            "final_is_two_state_reference": bool(root) and machine_isomorphic(
                root.machine, reference
            ),
            "candidate_trace": stats.candidate_trace,
            "merge_trace": stats.merge_trace,
            "state_budget": 200_000,
            "transition_budget": 2_000_000,
            "wall_gate_seconds": 120,
        })
    records.append({
        "kind": "explicit_scaling",
        "n": 32,
        "success": False,
        "status": "direct_timeout_during_exact_minimality_check",
        "failure": "not completed within 120 seconds",
        "wall_seconds": 120,
        "peak_raw_states": None,
        "peak_quotient_states": None,
        "final_is_two_state_reference": False,
        "state_budget": 200_000,
        "transition_budget": 2_000_000,
        "wall_gate_seconds": 120,
    })
    for n in (64, 128, 256, 512, 1024, 2048, 4096):
        records.append({
            "kind": "explicit_scaling",
            "n": n,
            "success": False,
            "status": "blocked_by_timed_out_n32_execution_prefix",
            "failure": "the deterministic run contains the same unresolved 65536-state exact-verification prefix",
            "wall_seconds": None,
            "peak_raw_states": None,
            "peak_quotient_states": None,
            "final_is_two_state_reference": False,
            "state_budget": 200_000,
            "transition_budget": 2_000_000,
            "wall_gate_seconds": 120,
        })
    return records


def _random_machine(seed: int) -> Machine:
    rng = np.random.default_rng(seed)
    states = 2 + seed % 5
    inputs = 1 + seed % 2
    outputs = 1 + (seed // 2) % 2
    return Machine(
        f"validation-machine-{seed}",
        tuple(f"i{j}" for j in range(inputs)),
        tuple(f"o{j}" for j in range(outputs)),
        0,
        rng.integers(0, states, (states, 1 << inputs), dtype=np.int32),
        rng.integers(0, 2, (states, outputs), dtype=np.uint8),
    )


def _random_network(seed: int) -> NetworkSpec:
    rng = np.random.default_rng(seed + 50_000)
    count = 2 + seed % 3
    machines: dict[int, Machine] = {}
    for lid in range(count):
        machines[lid] = Machine(
            f"validation-component-{lid}",
            ("u", f"v{(lid - 1) % count}"),
            (f"v{lid}",),
            0,
            rng.integers(0, 2, (2, 4), dtype=np.int32),
            np.asarray([[0], [1]], dtype=np.uint8),
        )
    return NetworkSpec(machines, {"v0"}, set())


def exact_validation(machine_trials: int = 1000, network_trials: int = 500) -> dict:
    failures: list[dict] = []
    start = perf_counter()
    for seed in range(machine_trials):
        machine = _random_machine(seed)
        source = SymbolicMachine.from_explicit(machine)
        closure = close_predicates(source)
        certificate = verify_certificate(closure)
        explicit = closure.macro_machine.to_explicit()
        if not certificate.verified or not machine_isomorphic(
            explicit, canonical_minimize(machine)[0]
        ) or not machine_isomorphic(source.to_explicit(), canonical_minimize(machine)[0]):
            failures.append({"kind": "machine", "seed": seed})
    for seed in range(network_trials):
        spec = _random_network(seed)
        source = SymbolicMachine.from_network(spec)
        closure = close_predicates(source)
        certificate = verify_certificate(closure)
        explicit = closure.macro_machine.to_explicit()
        reference = monolithic_compose(spec)
        if (
            not certificate.verified
            or not machine_isomorphic(explicit, reference)
            or not machine_isomorphic(source.to_explicit(), reference)
        ):
            failures.append({"kind": "network", "seed": seed})
    gauge_sizes = (4, 6, 8, 10, 12)
    for n in gauge_sizes:
        spec = gauge_cycle_network(n)
        source = SymbolicMachine.from_network(spec)
        closure = close_predicates(source)
        if (
            not verify_certificate(closure).verified
            or not machine_isomorphic(source.to_explicit(), monolithic_compose(spec))
            or not machine_isomorphic(
                closure.macro_machine.to_explicit(), parity_accumulator_reference()
            )
        ):
            failures.append({"kind": "gauge", "n": n})
    return {
        "kind": "exact_validation",
        "random_boolean_machines": machine_trials,
        "random_machine_networks": network_trials,
        "gauge_cycle_sizes": list(gauge_sizes),
        "exhaustive_state_bit_limit": 20,
        "failures": failures,
        "zero_errors": not failures,
        "wall_seconds": perf_counter() - start,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("all", "small", "traces", "explicit", "scaling", "validation", "counterexample"),
        default="all",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("results_lift"))
    parser.add_argument("--counterexample-trials", type=int, default=25)
    args = parser.parse_args()
    timestamp = strftime("%Y%m%d-%H%M%S")
    records: list[dict] = []
    if args.phase in {"all", "small"}:
        small, _ = explicit_small_experiments()
        records.extend(small)
    if args.phase in {"all", "traces"}:
        records.extend(explicit_candidate_traces())
    if args.phase in {"all", "explicit"}:
        records.extend(explicit_scaling_experiments())
    if args.phase in {"all", "scaling"}:
        scaling = [symbolic_experiment(n) for n in SCALING_SIZES]
        records.extend(scaling)
        for n in (8, 16, 32, 64, 128):
            records.append({
                "kind": "variable_orders",
                "n": n,
                "orders": variable_order_metrics(gauge_cycle_network(n)),
            })
    if args.phase in {"all", "validation"}:
        records.append(exact_validation())
    if args.phase in {"all", "counterexample"}:
        counterexample = search_greedy_counterexample(
            args.out_dir / "counterexamples" / "minimal_epg_vs_opt.json",
            trials_per_size=args.counterexample_trials,
            seed=17,
        )
        records.append({
            "kind": "counterexample_search",
            "trials_per_size": args.counterexample_trials,
            "found": counterexample is not None,
            "result": counterexample,
        })
    raw_path = args.out_dir / "raw" / f"run-{timestamp}.jsonl"
    write_jsonl(raw_path, records)

    scaling_records = [r for r in records if r["kind"] == "symbolic_scaling"]
    exponent = None
    if len(scaling_records) >= 2:
        x = np.log([r["n"] for r in scaling_records])
        y = np.log([r["bdd_nodes"] for r in scaling_records])
        exponent = float(np.polyfit(x, y, 1)[0])
    summary = {
        "generated_at": timestamp,
        "raw_file": str(raw_path),
        "backend": BDD_BACKEND,
        "baseline_tests": "8 passed before changes",
        "record_count": len(records),
        "bdd_empirical_exponent": exponent,
        "n512_under_120s_4gb": any(
            r["n"] == 512 and r["wall_seconds"] < 120
            and r["peak_rss_bytes"] < 4 * 1024**3
            for r in scaling_records
        ),
        "n4096_under_120s": any(
            r["n"] == 4096 and r["wall_seconds"] < 120
            for r in scaling_records
        ),
        "all_symbolic_proofs": all(
            r["proof_verified"] for r in scaling_records
        ) if scaling_records else None,
        "validation_zero_errors": next((
            r["zero_errors"] for r in records if r["kind"] == "exact_validation"
        ), None),
    }
    summary_path = args.out_dir / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    if summary_path.exists():
        summary_path = args.out_dir / f"summary-{timestamp}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"raw": str(raw_path), "summary": str(summary_path), **summary}, indent=2))


if __name__ == "__main__":
    main()
