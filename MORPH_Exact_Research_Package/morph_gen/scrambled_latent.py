from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log2
from pathlib import Path
from random import Random
from typing import Sequence

import numpy as np

from morph_exact.core import Machine, canonical_minimize
from morph_exact.generators import (
    alternating_bit_protocol,
    handshake_controller,
    modulo_counter,
    parity_accumulator,
    pattern_detector,
    synchronous_product,
    traffic_light,
)
from morph_exact.kiss2 import load_kiss2

from .aig import AIG
from .encodings import (
    DenseAffineEncoding,
    FeistelEncoding,
    MixedEncoding,
    ReversibleEncoding,
    TriangularPolynomialEncoding,
)
from .spec import CircuitSystem
from .structural_obfuscation import entangle_dependencies


@dataclass
class SLOInstance:
    """Evaluation wrapper. Only ``system`` is passed to synthesis backends."""

    system: CircuitSystem
    latent_machine: Machine
    encoding: ReversibleEncoding
    decoder_functions: tuple[int, ...]
    latent_state_bits: int
    encoding_label: str
    seed: int

    @property
    def oracle_macro_bits(self) -> int:
        return max(1, ceil(log2(self.latent_machine.n_states)))


def _state_function(
    aig: AIG,
    state: Sequence[int],
    inputs: Sequence[int],
    table: np.ndarray,
    output_bit: int,
) -> int:
    width = len(state)
    values = [0] * (1 << (width + len(inputs)))
    state_mask = (1 << width) - 1
    for valuation in range(len(values)):
        source = valuation & state_mask
        symbol = valuation >> width
        target = int(table[source, symbol]) if source < table.shape[0] else 0
        values[valuation] = (target >> output_bit) & 1
    return aig.truth_table((*state, *inputs), values)


def _output_function(
    aig: AIG,
    state: Sequence[int],
    table: np.ndarray,
    output_bit: int,
) -> int:
    values = [
        int(table[source, output_bit]) if source < table.shape[0] else 0
        for source in range(1 << len(state))
    ]
    return aig.truth_table(state, values)


def _state_equals(aig: AIG, state: Sequence[int], value: int) -> int:
    return aig.and_many(
        bit if (value >> index) & 1 else aig.not_(bit)
        for index, bit in enumerate(state)
    )


def _valid_state(aig: AIG, state: Sequence[int], count: int) -> int:
    if count == 1 << len(state):
        return aig.true
    return aig.xor_many(_state_equals(aig, state, value) for value in range(count))


def compile_scrambled_latent(
    latent_machine: Machine,
    micro_bits: int,
    encoding: ReversibleEncoding,
    *,
    seed: int,
    encoding_label: str,
) -> SLOInstance:
    latent_machine = canonical_minimize(latent_machine)[0]
    latent_bits = max(1, ceil(log2(max(2, latent_machine.n_states))))
    if micro_bits <= latent_bits or encoding.width != micro_bits:
        raise ValueError("micro width must exceed latent state width")
    aig = AIG()
    physical = tuple(aig.input(f"x{i}") for i in range(micro_bits))
    inputs = tuple(aig.input(f"u{i}") for i in range(len(latent_machine.inputs)))
    decoded = encoding.decode(aig, physical)
    latent = decoded[:latent_bits]
    nuisance = decoded[latent_bits:]

    latent_next = tuple(
        _state_function(aig, latent, inputs, latent_machine.next_state, bit)
        for bit in range(latent_bits)
    )
    # Nuisance coordinates are unconstrained initially and behaviorally inert.
    # Identity update keeps every initial nuisance valuation reachable.
    encoded_next = encoding.encode(aig, (*latent_next, *nuisance))
    entangled_next = entangle_dependencies(aig, physical, encoded_next)
    outputs = tuple(
        _output_function(aig, latent, latent_machine.output_bits, bit)
        for bit in range(len(latent_machine.outputs))
    )
    valid = _valid_state(aig, latent, latent_machine.n_states)
    initial = aig.and_(valid, _state_equals(aig, latent, latent_machine.initial))
    # Each opaque MUX at target i reads physical (i-1) mod n, so this cycle is
    # an exact executable SCC witness. The full dense support remains in the
    # AIG and can be expanded for small instances without materializing O(n^2)
    # edges during large benchmark construction.
    dependencies = frozenset(
        ((index - 1) % micro_bits, index) for index in range(micro_bits)
    )
    system = CircuitSystem(
        f"scrambled-system-{seed}",
        aig,
        physical,
        inputs,
        entangled_next,
        outputs,
        initial,
        valid,
        valid,
        dependencies,
        metadata={"coordinate_free": True, "seed": seed},
    )
    return SLOInstance(
        system,
        latent_machine,
        encoding,
        tuple(latent),
        latent_bits,
        encoding_label,
        seed,
    )


def make_slo(
    latent_machine: Machine,
    micro_bits: int,
    *,
    encoding: str,
    seed: int,
    degree: int = 2,
    sparsity: int = 4,
    rounds: int = 3,
) -> SLOInstance:
    latent_bits = max(1, ceil(log2(max(2, latent_machine.n_states))))
    if encoding == "affine":
        codec: ReversibleEncoding = DenseAffineEncoding.random(micro_bits, seed)
    elif encoding == "triangular":
        codec = TriangularPolynomialEncoding.random(
            micro_bits, seed, range(latent_bits), degree=degree, sparsity=sparsity
        )
    elif encoding == "feistel":
        codec = FeistelEncoding.random(micro_bits, seed, rounds=rounds)
    elif encoding == "mixed":
        codec = MixedEncoding.random(micro_bits, seed, range(latent_bits))
    else:
        raise KeyError(encoding)
    if not codec.verify_roundtrip():
        raise AssertionError("generated encoding failed roundtrip")
    return compile_scrambled_latent(
        latent_machine, micro_bits, codec, seed=seed, encoding_label=encoding
    )


def latent_machine_catalog(benchmark_dir: Path) -> dict[str, Machine]:
    parity = parity_accumulator("latent-parity")
    counter3 = modulo_counter(3, "latent-counter3")
    counter5 = modulo_counter(5, "latent-counter5")
    pattern = pattern_detector("1011", "latent-pattern")
    handshake = handshake_controller("latent-handshake")
    abp = alternating_bit_protocol("latent-abp")
    traffic = traffic_light("latent-traffic")
    bbara = load_kiss2(benchmark_dir / "bbara.kiss2", "latent-bbara")
    heterogeneous = synchronous_product(
        parity_accumulator("heterogeneous-p"),
        modulo_counter(3, "heterogeneous-c"),
        "latent-heterogeneous-product",
    )
    return {
        "parity": parity,
        "modulo3": counter3,
        "modulo5": counter5,
        "pattern": pattern,
        "handshake": handshake,
        "abp": abp,
        "traffic": traffic,
        "bbara": bbara,
        "heterogeneous": heterogeneous,
    }


def affine_scaling_machine(latent_bits: int, seed: int) -> Machine:
    """Observable affine latent machine used only to construct scaling inputs."""
    rng = Random(seed)
    states = 1 << latent_bits
    rows = [1 << ((index + 1) % latent_bits) for index in range(latent_bits)]
    next_state = np.empty((states, 2), dtype=np.int32)
    output = np.empty((states, 1), dtype=np.uint8)
    for state in range(states):
        output[state, 0] = state & 1
        for symbol in (0, 1):
            target = sum(
                (((rows[bit] & state).bit_count() & 1) ^ (symbol if bit == latent_bits - 1 else 0)) << bit
                for bit in range(latent_bits)
            )
            next_state[state, symbol] = target
    return canonical_minimize(Machine(
        f"affine-scaling-{rng.randrange(1 << 30)}",
        ("drive",),
        ("observe",),
        0,
        next_state,
        output,
    ))[0]


def binary_organ_product(organ_count: int) -> tuple[Machine, tuple[str, ...]]:
    """Independent two-state behavioral projections for global-mix recursion."""
    if not 2 <= organ_count <= 8:
        raise ValueError("explicit binary-organ product supports 2--8 organs")
    labels = (
        "parity", "modulo-counter", "pattern", "handshake",
        "alternating-bit", "traffic-light", "bbara", "heterogeneous-product",
    )[:organ_count]
    states = 1 << organ_count
    alphabet = 1 << organ_count
    next_state = np.empty((states, alphabet), dtype=np.int32)
    outputs = np.empty((states, organ_count), dtype=np.uint8)
    for state in range(states):
        outputs[state] = [(state >> bit) & 1 for bit in range(organ_count)]
        for input_value in range(alphabet):
            next_state[state, input_value] = state ^ input_value
    machine = Machine(
        "globally-mixed-binary-organs",
        tuple(f"organ_input_{index}" for index in range(organ_count)),
        tuple(f"organ_output_{index}" for index in range(organ_count)),
        0,
        next_state,
        outputs,
    )
    return machine, labels
