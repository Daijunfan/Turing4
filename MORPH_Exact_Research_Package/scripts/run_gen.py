from __future__ import annotations

import argparse
import json
import multiprocessing as mp
from pathlib import Path
from queue import Empty
from time import perf_counter, strftime

import numpy as np

from morph_exact.core import Machine, canonical_minimize
from morph_exact.generators import synchronous_product
from morph_gen.baselines import run_baselines
from morph_gen.generator_basis import synthesize_generator
from morph_gen.scrambled_latent import latent_machine_catalog, make_slo
from morph_gen.structural_obfuscation import verify_obfuscation


def _random_machine(seed: int) -> Machine:
    rng = np.random.default_rng(seed)
    states = 2 + seed % 3
    machine = Machine(
        f"random-gen-{seed}",
        ("u",),
        ("o",),
        0,
        rng.integers(0, states, (states, 2), dtype=np.int32),
        rng.integers(0, 2, (states, 1), dtype=np.uint8),
    )
    return canonical_minimize(machine)[0]


def _rename(machine: Machine, tag: str) -> Machine:
    return Machine(
        f"{machine.name}-{tag}",
        tuple(f"u-{tag}-{index}" for index in range(len(machine.inputs))),
        (f"o-{tag}",),
        machine.initial,
        machine.next_state,
        machine.output_bits,
    )


def _random_network_machine(seed: int) -> Machine:
    left = _rename(_random_machine(seed * 2 + 1), "left")
    right = _rename(_random_machine(seed * 2 + 2), "right")
    return synchronous_product(left, right, f"random-network-{seed}")


def _record(name: str, encoding: str, seed: int, micro_bits: int, machine: Machine) -> dict:
    instance = make_slo(machine, micro_bits, encoding=encoding, seed=seed)
    start = perf_counter()
    outcome = synthesize_generator(instance.system)
    seconds = perf_counter() - start
    record = {
        "name": name,
        "encoding": encoding,
        "seed": seed,
        "micro_state_bits": micro_bits,
        "latent_oracle_bits": instance.oracle_macro_bits,
        "latent_states": machine.n_states,
        "status": outcome.status,
        "wall_seconds": seconds,
        "attempts": outcome.attempts,
    }
    if outcome.basis is None:
        return record
    metrics = outcome.basis.metrics()
    if "wall_seconds" in metrics:
        metrics["synthesis_seconds"] = metrics.pop("wall_seconds")
    obfuscation = verify_obfuscation(
        instance.system, instance.decoder_functions, r=min(2, micro_bits - 1)
    )
    record.update({
        **metrics,
        "wall_seconds": seconds,
        "proof": outcome.certificate.to_dict(),
        "recovered_machine_isomorphism": outcome.certificate.explicit_isomorphism,
        "minimum_distinguishing_word_length": outcome.certificate.maximum_distinguishing_word_length,
        "any_physical_coordinate_equals_macro": not obfuscation.no_coordinate_equals_macro,
        "minimum_physical_coordinates_determining_macro": obfuscation.minimum_coordinates_determining_macro,
        "strongly_connected": obfuscation.strongly_connected,
        "obfuscation_verified": obfuscation.verified,
    })
    return record


def _record_worker(queue, arguments) -> None:
    try:
        queue.put(_record(*arguments))
    except BaseException as error:
        queue.put({
            "name": arguments[0],
            "encoding": arguments[1],
            "seed": arguments[2],
            "micro_state_bits": arguments[3],
            "status": "REJECTED",
            "reason": f"{type(error).__name__}: {error}",
            "negative_result_preserved": True,
        })


def _record_isolated(*arguments) -> dict:
    context = mp.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_record_worker, args=(queue, arguments))
    process.start()
    try:
        result = queue.get(timeout=120)
    except Empty:
        process.terminate()
        process.join()
        return {
            "name": arguments[0],
            "encoding": arguments[1],
            "seed": arguments[2],
            "micro_state_bits": arguments[3],
            "status": "REJECTED",
            "reason": "hard timeout after 120 seconds",
            "negative_result_preserved": True,
        }
    if process.is_alive():
        process.terminate()
    process.join()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--random-machines", type=int, default=0)
    parser.add_argument("--random-networks", type=int, default=0)
    parser.add_argument("--out-dir", type=Path, default=Path("results_gen"))
    args = parser.parse_args()
    args.out_dir.joinpath("raw").mkdir(parents=True, exist_ok=True)
    stamp = strftime("%Y%m%d-%H%M%S")
    path = args.out_dir / "raw" / f"small-{stamp}.jsonl"
    stream = path.open("x")
    records = []

    def emit(record: dict) -> None:
        records.append(record)
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
    catalog = latent_machine_catalog(Path("benchmarks"))
    names = (
        "parity", "modulo3", "modulo5", "pattern", "handshake", "abp",
        "traffic", "bbara", "heterogeneous",
    )
    for encoding_index, encoding in enumerate(("affine", "triangular", "feistel")):
        for index, name in enumerate(names):
            width = max(10, 2 * ((catalog[name].n_states - 1).bit_length() + 1))
            if encoding == "feistel" and width % 2:
                width += 1
            emit(_record_isolated(
                name, encoding, 1000 * encoding_index + index,
                min(width, 20), catalog[name],
            ))
    produced = 0
    seed = 0
    while produced < args.random_machines:
        machine = _random_machine(seed)
        if machine.n_states < 2:
            seed += 1
            continue
        encoding = ("affine", "triangular", "feistel")[produced % 3]
        width = (
            6 + 2 * (produced % 2)
            if encoding == "feistel"
            else 6 + 2 * (produced % 5)
        )
        emit(_record_isolated(
            f"random-{seed}", encoding, 10_000 + seed, width, machine
        ))
        produced += 1
        seed += 1
    produced = 0
    seed = 0
    while produced < args.random_networks:
        machine = _random_network_machine(seed)
        if machine.n_states < 2:
            seed += 1
            continue
        encoding = ("affine", "triangular", "feistel")[produced % 3]
        width = (
            8 + 2 * (produced % 2)
            if encoding == "feistel"
            else 8 + 2 * (produced % 4)
        )
        width = max(width, (machine.n_states - 1).bit_length() + 3)
        if encoding == "feistel" and width % 2:
            width += 1
        emit(_record_isolated(
            f"random-network-{seed}", encoding, 20_000 + seed,
            min(width, 20), machine,
        ))
        produced += 1
        seed += 1

    stream.close()
    successful = [record for record in records if record["status"] == "SUPPORTED"]
    representative = successful[0]
    instance = make_slo(
        catalog[representative["name"]],
        representative["micro_state_bits"],
        encoding=representative["encoding"],
        seed=representative["seed"],
    )
    outcome = synthesize_generator(instance.system)
    baseline = run_baselines(instance.system, outcome.basis)
    baseline_path = args.out_dir / "raw" / f"baselines-{stamp}.json"
    baseline_path.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "raw": str(path),
        "baselines": str(baseline_path),
        "runs": len(records),
        "successes": len(successful),
        "failures": len(records) - len(successful),
        "baseline": baseline,
    }, indent=2))


if __name__ == "__main__":
    main()
