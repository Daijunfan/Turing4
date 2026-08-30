from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from math import log2, prod
from pathlib import Path
from typing import Dict, Iterable

import numpy as np

from morph_exact.core import (
    Machine,
    NetworkSpec,
    canonical_minimize,
    independent_is_minimal,
    verify_quotient_homomorphism,
)
from morph_exact.engine import MorphEngine


@dataclass
class OpenQuotientProof:
    raw_digest: str
    quotient_digest: str
    homomorphism: bool
    minimal: bool


@dataclass
class OpenQuotient:
    mask: int
    leaves: tuple[int, ...]
    raw: Machine
    quotient: Machine
    state_map: np.ndarray
    primitive_states: tuple[tuple[int, ...], ...]
    proof: OpenQuotientProof

    @property
    def raw_index(self) -> dict[tuple[int, ...], int]:
        return {state: index for index, state in enumerate(self.primitive_states)}

    @property
    def injective_quotient(self) -> bool:
        return self.raw.n_states == self.quotient.n_states


@dataclass
class Formation:
    left_mask: int
    right_mask: int
    reachable_product_states: int
    external_input_bits: int
    cost: float


@dataclass
class OracleNode:
    mask: int
    leaves: tuple[int, ...]
    peak_cost: float
    left: "OracleNode | None" = None
    right: "OracleNode | None" = None
    formation: Formation | None = None

    def to_dict(self) -> dict:
        return {
            "mask": self.mask,
            "leaves": list(self.leaves),
            "peak_cost": self.peak_cost,
            "formation": asdict(self.formation) if self.formation else None,
            "left": self.left.to_dict() if self.left else None,
            "right": self.right.to_dict() if self.right else None,
        }


@dataclass
class OracleResult:
    leaves: tuple[int, ...]
    quotients: Dict[int, OpenQuotient]
    opt: Dict[int, float]
    tree: OracleNode

    @property
    def peak_cost(self) -> float:
        return self.tree.peak_cost


def exact_open_quotient(
    spec: NetworkSpec,
    leaves: Iterable[int],
    *,
    max_product_states: int = 1_000_000,
) -> OpenQuotient:
    """Direct primitive product construction for one exact open region.

    This implementation is independent of recursive MORPH composition.  It
    vectorizes the finite transition table, then performs exact reachability and
    invokes the existing canonical quotient plus its independent verifier.
    """
    lids = tuple(sorted(set(leaves)))
    if not lids:
        raise ValueError("region must be nonempty")
    machines = [spec.leaf_machines[lid] for lid in lids]
    radices = [machine.n_states for machine in machines]
    product_states = prod(radices)
    if product_states > max_product_states:
        raise RuntimeError(f"region product has {product_states} states")
    multipliers: list[int] = []
    multiplier = 1
    for radix in radices:
        multipliers.append(multiplier)
        multiplier *= radix
    codes = np.arange(product_states, dtype=np.int64)
    state_digits = np.column_stack([
        (codes // multiplier) % radix
        for multiplier, radix in zip(multipliers, radices)
    ]).astype(np.int32)

    produced = {port for machine in machines for port in machine.outputs}
    external_inputs = tuple(sorted({
        port for machine in machines for port in machine.inputs if port not in produced
    }))
    external_position = {port: bit for bit, port in enumerate(external_inputs)}
    symbols = np.arange(1 << len(external_inputs), dtype=np.int64)
    signal_values: dict[str, np.ndarray] = {}
    for column, machine in enumerate(machines):
        for bit, port in enumerate(machine.outputs):
            signal_values[port] = machine.output_bits[state_digits[:, column], bit]

    targets = np.zeros((product_states, len(symbols)), dtype=np.int64)
    for column, (machine, multiplier) in enumerate(zip(machines, multipliers)):
        local_input = np.zeros((product_states, len(symbols)), dtype=np.int64)
        for bit, port in enumerate(machine.inputs):
            if port in signal_values:
                local_input |= signal_values[port][:, None].astype(np.int64) << bit
            else:
                local_input |= (
                    ((symbols >> external_position[port]) & 1)[None, :] << bit
                )
        local_target = machine.next_state[
            state_digits[:, column, None], local_input
        ]
        targets += local_target.astype(np.int64) * multiplier

    initial_code = sum(
        machine.initial * multiplier
        for machine, multiplier in zip(machines, multipliers)
    )
    reachable = np.zeros(product_states, dtype=np.bool_)
    reachable[initial_code] = True
    frontier = np.asarray([initial_code], dtype=np.int64)
    while frontier.size:
        discovered = np.unique(targets[frontier].reshape(-1))
        frontier = discovered[~reachable[discovered]]
        reachable[frontier] = True
    reachable_codes = np.flatnonzero(reachable)
    if reachable_codes[0] != initial_code:
        reachable_codes = np.concatenate((
            np.asarray([initial_code]),
            reachable_codes[reachable_codes != initial_code],
        ))
    remap = np.full(product_states, -1, dtype=np.int32)
    remap[reachable_codes] = np.arange(len(reachable_codes), dtype=np.int32)
    raw_next = remap[targets[reachable_codes]]
    keep = tuple(sorted(spec.keep_outputs(set(lids)) & produced))
    raw_outputs = np.column_stack([
        signal_values[port][reachable_codes] for port in keep
    ]).astype(np.uint8) if keep else np.empty((len(reachable_codes), 0), dtype=np.uint8)
    raw = Machine(
        f"open-{','.join(map(str, lids))}",
        external_inputs,
        keep,
        0,
        raw_next,
        raw_outputs,
    )
    quotient, state_map = canonical_minimize(raw)
    proof = OpenQuotientProof(
        raw.digest(),
        quotient.digest(),
        verify_quotient_homomorphism(raw, quotient, state_map),
        independent_is_minimal(quotient),
    )
    if not proof.homomorphism or not proof.minimal:
        raise AssertionError("open quotient proof failed")
    primitive_states = tuple(
        tuple(int(x) for x in row) for row in state_digits[reachable_codes]
    )
    mask = sum(1 << lid for lid in lids)
    return OpenQuotient(mask, lids, raw, quotient, state_map, primitive_states, proof)


def _projected_quotient_state(
    region: OpenQuotient,
    union: OpenQuotient,
    union_state: tuple[int, ...],
) -> int:
    positions = [union.leaves.index(lid) for lid in region.leaves]
    projection = tuple(union_state[position] for position in positions)
    raw_state = region.raw_index[projection]
    quotient_state = int(region.state_map[raw_state])
    if quotient_state < 0:
        raise AssertionError("reachable union projected to unreachable child state")
    return quotient_state


def formation_reachable_states(
    left: OpenQuotient,
    right: OpenQuotient,
    union: OpenQuotient,
) -> int:
    """Exact reachable image in Q(left) x Q(right), derived from union traces."""
    if left.injective_quotient and right.injective_quotient:
        # The two projections jointly contain every primitive coordinate, hence
        # their pair is injective on the union's reachable primitive states.
        return union.raw.n_states
    pairs = {
        (
            _projected_quotient_state(left, union, state),
            _projected_quotient_state(right, union, state),
        )
        for state in union.primitive_states
    }
    return len(pairs)


def subset_oracle(
    spec: NetworkSpec,
    *,
    max_components: int = 12,
    max_product_states: int = 1_000_000,
) -> OracleResult:
    """Exact subset-DP optimum over every nonempty component subset."""
    leaves = tuple(sorted(spec.leaf_machines))
    if len(leaves) > max_components:
        raise ValueError(f"subset oracle supports at most {max_components} components")
    if leaves != tuple(range(len(leaves))):
        raise ValueError("subset oracle currently requires dense component ids")
    full = (1 << len(leaves)) - 1
    quotients: dict[int, OpenQuotient] = {}
    opt: dict[int, float] = {}
    trees: dict[int, OracleNode] = {}
    for size in range(1, len(leaves) + 1):
        for mask in range(1, full + 1):
            if mask.bit_count() != size:
                continue
            region_leaves = tuple(i for i in leaves if (mask >> i) & 1)
            quotient = exact_open_quotient(
                spec, region_leaves, max_product_states=max_product_states
            )
            quotients[mask] = quotient
            if size == 1:
                opt[mask] = 0.0
                trees[mask] = OracleNode(mask, region_leaves, 0.0)
                continue
            best: tuple[float, int, int, Formation] | None = None
            left = (mask - 1) & mask
            while left:
                right = mask ^ left
                if right and left < right:
                    reachable = formation_reachable_states(
                        quotients[left], quotients[right], quotient
                    )
                    external_bits = len(quotient.raw.inputs)
                    cost = log2(reachable) + external_bits
                    formation = Formation(
                        left, right, reachable, external_bits, cost
                    )
                    peak = max(opt[left], opt[right], cost)
                    candidate = (peak, left, right, formation)
                    if best is None or candidate[:3] < best[:3]:
                        best = candidate
                left = (left - 1) & mask
            assert best is not None
            peak, left, right, formation = best
            opt[mask] = peak
            trees[mask] = OracleNode(
                mask,
                region_leaves,
                peak,
                trees[left],
                trees[right],
                formation,
            )
    return OracleResult(leaves, quotients, opt, trees[full])


def reatomization_peak_cost(root) -> float:
    """Formation metric on an already executed explicit MORPH tree."""
    peak = 0.0
    stack = [root]
    while stack:
        region = stack.pop()
        if region is None or region.merge_result is None:
            continue
        raw = region.merge_result.raw
        peak = max(peak, log2(raw.n_states) + len(raw.inputs))
        if region.children:
            stack.extend(region.children)
    return peak


def random_feedback_network(component_count: int, seed: int) -> NetworkSpec:
    """Small generic exact-search instance; no family metadata or oracle tree."""
    if not 5 <= component_count <= 10:
        raise ValueError("counterexample search uses 5--10 components")
    rng = np.random.default_rng(seed)
    permutation = list(map(int, rng.permutation(component_count)))
    predecessor = {
        permutation[(index + 1) % component_count]: permutation[index]
        for index in range(component_count)
    }
    machines: dict[int, Machine] = {}
    for lid in range(component_count):
        transitions = rng.integers(0, 2, size=(2, 4), dtype=np.int32)
        # Make the shared input genuinely executable without encoding a target
        # semantic law: redraw only a degenerate truth table.
        if np.array_equal(transitions[:, :2], transitions[:, 2:]):
            transitions[0, 2] ^= 1
        machines[lid] = Machine(
            f"random-component-{lid}",
            ("u", f"r{predecessor[lid]}"),
            (f"r{lid}",),
            0,
            transitions,
            np.asarray([[0], [1]], dtype=np.uint8),
        )
    contacts: set[tuple[int, int]] = set()
    for _ in range(component_count // 2):
        a, b = map(int, rng.choice(component_count, size=2, replace=False))
        contacts.add((min(a, b), max(a, b)))
    return NetworkSpec(
        machines,
        {f"r{int(rng.integers(0, component_count))}"},
        contacts,
        metadata={"component_count": component_count, "seed": seed},
    )


def network_to_dict(spec: NetworkSpec) -> dict:
    return {
        "leaf_machines": {
            str(lid): {
                "name": machine.name,
                "inputs": list(machine.inputs),
                "outputs": list(machine.outputs),
                "initial": machine.initial,
                "next_state": machine.next_state.tolist(),
                "output_bits": machine.output_bits.tolist(),
            }
            for lid, machine in spec.leaf_machines.items()
        },
        "global_outputs": sorted(spec.global_outputs),
        "contact_edges": [list(edge) for edge in sorted(spec.contact_edges)],
        "metadata": {
            key: value for key, value in spec.metadata.items()
            if isinstance(value, (str, int, float, bool, type(None)))
        },
    }


def network_from_dict(data: dict) -> NetworkSpec:
    machines = {
        int(lid): Machine(
            item["name"],
            tuple(item["inputs"]),
            tuple(item["outputs"]),
            int(item["initial"]),
            np.asarray(item["next_state"], dtype=np.int32),
            np.asarray(item["output_bits"], dtype=np.uint8),
        )
        for lid, item in data["leaf_machines"].items()
    }
    return NetworkSpec(
        machines,
        set(data["global_outputs"]),
        {tuple(map(int, edge)) for edge in data["contact_edges"]},
        metadata=dict(data.get("metadata", {})),
    )


def search_greedy_counterexample(
    output: Path,
    *,
    trials_per_size: int = 25,
    seed: int = 0,
) -> dict | None:
    """Exact seeded search over 5--10 components; preserve min and maximum."""
    output.parent.mkdir(parents=True, exist_ok=True)
    minimal: dict | None = None
    maximum: dict | None = None
    by_size: list[dict] = []
    for component_count in range(5, 11):
        best: dict | None = None
        for trial in range(trials_per_size):
            instance_seed = seed + component_count * 100_000 + trial
            spec = random_feedback_network(component_count, instance_seed)
            oracle = subset_oracle(spec, max_components=10)
            root, stats = MorphEngine(spec, seed=instance_seed).run("morph_batch")
            if not stats.success or root is None:
                morph_cost = float("inf")
            else:
                morph_cost = reatomization_peak_cost(root)
            ratio = morph_cost / oracle.peak_cost
            if ratio <= 1.0 + 1e-12:
                continue
            record = {
                "component_count": component_count,
                "seed": instance_seed,
                "morph_cost": morph_cost,
                "opt_cost": oracle.peak_cost,
                "ratio": ratio,
                "morph_success": stats.success,
                "morph_failure": stats.failure,
                "opt_tree": oracle.tree.to_dict(),
                "network": network_to_dict(spec),
            }
            if best is None or ratio > best["ratio"]:
                best = record
        if best is not None:
            by_size.append({
                "component_count": component_count,
                "seed": best["seed"],
                "ratio": best["ratio"],
            })
            if minimal is None:
                minimal = best
            if maximum is None or best["ratio"] > maximum["ratio"]:
                maximum = best
    if minimal is None or maximum is None:
        return None

    def preserve(path: Path, record: dict) -> None:
        text = json.dumps(record, indent=2, sort_keys=True) + "\n"
        if not path.exists():
            path.write_text(text)
        elif json.loads(path.read_text()) != record:
            alternate = path.with_name(f"{path.stem}-additional{path.suffix}")
            if not alternate.exists():
                alternate.write_text(text)

    preserve(output, minimal)
    maximum_path = output.with_name("maximum_ratio_epg_vs_opt.json")
    preserve(maximum_path, maximum)
    return {
        "trials_per_size": trials_per_size,
        "sizes": list(range(5, 11)),
        "minimal": minimal,
        "maximum": maximum,
        "best_by_size": by_size,
        "maximum_file": str(maximum_path),
    }
