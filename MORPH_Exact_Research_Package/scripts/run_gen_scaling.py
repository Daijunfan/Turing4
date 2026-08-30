from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from pathlib import Path
from queue import Empty
import threading
from time import perf_counter, strftime

import psutil

from morph_gen.generator_basis import synthesize_generator
from morph_gen.recursive_factorization import factor_macro_dynamics
from morph_gen.scrambled_latent import (
    affine_scaling_machine,
    binary_organ_product,
    make_slo,
)


class PeakRSS:
    def __init__(self) -> None:
        self.peak = psutil.Process().memory_info().rss
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self) -> None:
        process = psutil.Process()
        while not self.stop.wait(0.005):
            self.peak = max(self.peak, process.memory_info().rss)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join()


def run_one(kind: str, n: int, k: int, seed: int, degree: int = 2, sparsity: int = 4, rounds: int = 3) -> dict:
    with PeakRSS() as memory:
        start = perf_counter()
        instance = make_slo(
            affine_scaling_machine(k, seed),
            n,
            encoding=kind,
            seed=seed,
            degree=degree,
            sparsity=sparsity,
            rounds=rounds,
        )
        built = perf_counter()
        outcome = synthesize_generator(instance.system)
        metrics = outcome.basis.metrics() if outcome.basis is not None else {}
        finished = perf_counter()
        if "wall_seconds" in metrics:
            metrics["synthesis_seconds"] = metrics.pop("wall_seconds")
    record = {
        "encoding": kind,
        "micro_state_bits": n,
        "latent_oracle_bits": k,
        "seed": seed,
        "degree": degree if kind == "triangular" else None,
        "sparsity": sparsity if kind == "triangular" else None,
        "rounds": rounds if kind == "feistel" else None,
        "build_seconds": built - start,
        "wall_seconds": finished - start,
        "peak_rss": memory.peak,
        "status": outcome.status,
        "attempts": outcome.attempts,
    }
    if outcome.basis is not None:
        record.update(metrics)
        record["wall_seconds"] = finished - start
        record.update({
            "proof_verified": outcome.certificate.verified,
            "proof_generation_time": outcome.certificate.proof_generation_seconds,
            "proof_checking_time": outcome.certificate.proof_checking_seconds,
            "minimum_distinguishing_word_length": outcome.certificate.maximum_distinguishing_word_length,
            "recovered_machine_isomorphism": outcome.certificate.explicit_isomorphism,
            "recursion_depth": 1,
            "recovered_organ_count": 1,
        })
    return record


def _worker(queue, arguments: tuple, keywords: dict) -> None:
    try:
        queue.put(run_one(*arguments, **keywords))
    except BaseException as error:
        queue.put({
            "encoding": arguments[0],
            "micro_state_bits": arguments[1],
            "latent_oracle_bits": arguments[2],
            "seed": arguments[3],
            "status": "REJECTED",
            "reason": f"{type(error).__name__}: {error}",
            "negative_result_preserved": True,
        })


def run_isolated(*arguments, **keywords) -> dict:
    context = mp.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=_worker, args=(queue, tuple(arguments), dict(keywords))
    )
    process.start()
    timeout = 120 if arguments[0] == "affine" else 300
    try:
        result = queue.get(timeout=timeout)
    except Empty:
        process.terminate()
        process.join()
        return {
            "encoding": arguments[0],
            "micro_state_bits": arguments[1],
            "latent_oracle_bits": arguments[2],
            "seed": arguments[3],
            "status": "REJECTED",
            "reason": f"hard timeout after {timeout} seconds",
            "negative_result_preserved": True,
        }
    if process.is_alive():
        process.terminate()
    process.join()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("affine", "triangular", "feistel", "multi", "all"), default="all")
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--out-dir", type=Path, default=Path("results_gen"))
    args = parser.parse_args()
    args.out_dir.joinpath("raw").mkdir(parents=True, exist_ok=True)
    stamp = strftime("%Y%m%d-%H%M%S")
    path = args.out_dir / "raw" / f"scaling-{args.phase}-{stamp}.jsonl"
    stream = path.open("x")
    records = []

    def emit(record: dict) -> None:
        records.append(record)
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()

    if args.phase in {"affine", "all"}:
        for n in (32, 64, 128, 256, 512, 1024, 2048, 4096):
            for k in (1, 2, 4, 8):
                if k >= n:
                    continue
                for seed in range(args.seeds):
                    emit(run_isolated("affine", n, k, 100_000 + n * 100 + k * 20 + seed))
    if args.phase in {"triangular", "all"}:
        for n in (16, 32, 64, 128, 256, 512):
            for degree in (2, 3):
                for sparsity in (2, 4, 8):
                    for seed in range(args.seeds):
                        emit(run_isolated(
                            "triangular", n, min(8, n // 2),
                            200_000 + n * 100 + degree * 10 + seed,
                            degree=degree, sparsity=sparsity,
                        ))
    if args.phase in {"feistel", "all"}:
        for n in (16, 32, 64, 128, 256):
            for rounds in (2, 3, 4):
                for seed in range(args.seeds):
                    emit(run_isolated(
                        "feistel", n, min(8, n // 2),
                        300_000 + n * 100 + rounds * 10 + seed,
                        rounds=rounds,
                    ))
    if args.phase in {"multi", "all"}:
        for count in (2, 4, 8, 16):
            if count > 8:
                emit({
                    "encoding": "global-affine-mix",
                    "latent_organ_count": count,
                    "status": "INCONCLUSIVE",
                    "reason": "explicit public MacroMachine table would require 2^32 entries",
                    "negative_result_preserved": True,
                })
                continue
            machine, labels = binary_organ_product(count)
            instance = make_slo(
                machine, max(16, count * 4), encoding="affine", seed=400_000 + count
            )
            start = perf_counter()
            outcome = synthesize_generator(instance.system)
            factorization = factor_macro_dynamics(outcome.basis)
            emit({
                "encoding": "global-affine-mix",
                "latent_organ_count": count,
                "oracle_origin_labels": labels,
                "micro_state_bits": instance.system.micro_bits,
                "status": outcome.status,
                "wall_seconds": perf_counter() - start,
                "macro_bits": outcome.basis.macro_bits,
                "proof_verified": outcome.certificate.verified,
                "recursion_depth": factorization.recursion_depth,
                "recovered_organ_count": factorization.recovered_organ_count,
                "factorization_metadata_used": factorization.proof["metadata_used"],
                "factorization_similarity_to_oracle": (
                    factorization.recovered_organ_count / count
                ),
            })
    stream.close()
    print(json.dumps({
        "raw": str(path),
        "runs": len(records),
        "successes": sum(record["status"] == "SUPPORTED" for record in records),
    }, indent=2))


if __name__ == "__main__":
    main()
