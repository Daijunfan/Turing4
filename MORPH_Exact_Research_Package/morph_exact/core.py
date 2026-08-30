from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from functools import cached_property
from math import ceil, log2
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
import hashlib
import json

import numpy as np


class CompositionTooLarge(RuntimeError):
    """Raised when speculative composition exceeds a declared resource bound."""


@dataclass(frozen=True)
class Machine:
    """Deterministic open synchronous Moore transducer over Boolean ports.

    A valuation is encoded as an integer. Bit j corresponds to inputs[j].
    Outputs depend only on current state, so cyclic wiring is well-defined at a
    synchronous step: current outputs are read, then all states update together.
    """

    name: str
    inputs: Tuple[str, ...]
    outputs: Tuple[str, ...]
    initial: int
    next_state: np.ndarray  # [state, 2**|inputs|] -> state
    output_bits: np.ndarray  # [state, |outputs|] -> {0,1}

    def __post_init__(self) -> None:
        ns = np.asarray(self.next_state, dtype=np.int32)
        ob = np.asarray(self.output_bits, dtype=np.uint8)
        if ns.ndim != 2 or ob.ndim != 2:
            raise ValueError("transition and output tables must be two-dimensional")
        if ns.shape[0] != ob.shape[0]:
            raise ValueError("state counts differ")
        if ns.shape[1] != 1 << len(self.inputs):
            raise ValueError("input alphabet does not match input ports")
        if ob.shape[1] != len(self.outputs):
            raise ValueError("output table does not match output ports")
        if not 0 <= self.initial < ns.shape[0]:
            raise ValueError("invalid initial state")
        if ns.size and (int(ns.min()) < 0 or int(ns.max()) >= ns.shape[0]):
            raise ValueError("transition target outside state space")
        if len(set(self.inputs)) != len(self.inputs):
            raise ValueError("duplicate input port")
        if len(set(self.outputs)) != len(self.outputs):
            raise ValueError("duplicate output port")
        if set(self.inputs) & set(self.outputs):
            raise ValueError("direct self-wire is forbidden; use a renamed signal")
        object.__setattr__(self, "next_state", ns)
        object.__setattr__(self, "output_bits", ob)

    @property
    def n_states(self) -> int:
        return int(self.next_state.shape[0])

    @property
    def alphabet_size(self) -> int:
        return int(self.next_state.shape[1])

    @cached_property
    def output_index(self) -> Dict[str, int]:
        return {x: i for i, x in enumerate(self.outputs)}

    @cached_property
    def input_index(self) -> Dict[str, int]:
        return {x: i for i, x in enumerate(self.inputs)}

    @cached_property
    def variable_outputs(self) -> frozenset[str]:
        if self.n_states <= 1:
            return frozenset()
        return frozenset(
            name for j, name in enumerate(self.outputs)
            if bool(np.any(self.output_bits[:, j] != self.output_bits[0, j]))
        )

    def description_bits(self) -> int:
        state_bits = max(1, ceil(log2(max(2, self.n_states))))
        return self.n_states * (len(self.outputs) + self.alphabet_size * state_bits)

    def digest(self) -> str:
        h = hashlib.sha256()
        h.update(self.name.encode("utf-8"))
        h.update(json.dumps(self.inputs).encode("utf-8"))
        h.update(json.dumps(self.outputs).encode("utf-8"))
        h.update(int(self.initial).to_bytes(8, "little"))
        h.update(self.next_state.tobytes())
        h.update(self.output_bits.tobytes())
        return h.hexdigest()


@dataclass
class QuotientCertificate:
    raw_digest: str
    quotient_digest: str
    state_map: np.ndarray
    verified_homomorphism: bool = False
    verified_minimal: bool = False


@dataclass
class CompositionResult:
    raw: Machine
    quotient: Machine
    certificate: QuotientCertificate
    product_states: Tuple[Tuple[int, int], ...]
    reachability_gain_bits: float
    quotient_gain_bits: float
    total_gain_bits: float
    transition_evaluations: int


@dataclass
class Region:
    rid: int
    leaves: frozenset[int]
    machine: Machine
    children: Optional[Tuple["Region", "Region"]] = None
    merge_result: Optional[CompositionResult] = None

    @property
    def depth(self) -> int:
        if self.children is None:
            return 0
        return 1 + max(self.children[0].depth, self.children[1].depth)


@dataclass
class NetworkSpec:
    leaf_machines: Dict[int, Machine]
    global_outputs: Set[str]
    contact_edges: Set[Tuple[int, int]]
    oracle_clusters: Set[frozenset[int]] = field(default_factory=set)
    metadata: Dict[str, object] = field(default_factory=dict)

    producer: Dict[str, int] = field(init=False)
    consumers: Dict[str, Set[int]] = field(init=False)
    signal_edges: Set[Tuple[int, int]] = field(init=False)

    def __post_init__(self) -> None:
        producer: Dict[str, int] = {}
        consumers: Dict[str, Set[int]] = {}
        for lid, machine in self.leaf_machines.items():
            for signal in machine.outputs:
                if signal in producer:
                    raise ValueError(f"multiple drivers for {signal}")
                producer[signal] = lid
            for signal in machine.inputs:
                consumers.setdefault(signal, set()).add(lid)
        signal_edges: Set[Tuple[int, int]] = set()
        for signal, src in producer.items():
            for dst in consumers.get(signal, ()):
                if src != dst:
                    signal_edges.add((min(src, dst), max(src, dst)))
        self.producer = producer
        self.consumers = consumers
        self.signal_edges = signal_edges
        self.contact_edges = {
            (min(a, b), max(a, b)) for a, b in (set(self.contact_edges) | signal_edges)
            if a != b
        }

    def keep_outputs(self, leaves: Set[int] | frozenset[int]) -> Set[str]:
        keep: Set[str] = set()
        for signal, src in self.producer.items():
            if src not in leaves:
                continue
            if signal in self.global_outputs:
                keep.add(signal)
            elif any(dst not in leaves for dst in self.consumers.get(signal, ())):
                keep.add(signal)
        return keep

    def regions_touch(self, a: Region, b: Region) -> bool:
        la, lb = a.leaves, b.leaves
        return any((x in la and y in lb) or (x in lb and y in la)
                   for x, y in self.contact_edges)

    def crossing_contact_count(self, a: Region, b: Region) -> int:
        la, lb = a.leaves, b.leaves
        return sum(1 for x, y in self.contact_edges
                   if (x in la and y in lb) or (x in lb and y in la))

    def boundary_contact_count(self, leaves: Set[int] | frozenset[int]) -> int:
        return sum(1 for x, y in self.contact_edges if (x in leaves) ^ (y in leaves))

    def semantic_crossing_count(self, a: Region, b: Region) -> int:
        return (
            sum(1 for x in a.machine.variable_outputs if x in b.machine.inputs)
            + sum(1 for x in b.machine.variable_outputs if x in a.machine.inputs)
        )


def normalize_ports(machine: Machine) -> Machine:
    sin = tuple(sorted(machine.inputs))
    sout = tuple(sorted(machine.outputs))
    if sin == machine.inputs and sout == machine.outputs:
        return machine
    old_in = {x: i for i, x in enumerate(machine.inputs)}
    ns = np.empty((machine.n_states, 1 << len(sin)), dtype=np.int32)
    for new_value in range(1 << len(sin)):
        old_value = 0
        for j, name in enumerate(sin):
            old_value |= ((new_value >> j) & 1) << old_in[name]
        ns[:, new_value] = machine.next_state[:, old_value]
    old_out = {x: i for i, x in enumerate(machine.outputs)}
    ob = machine.output_bits[:, [old_out[x] for x in sout]] if sout else machine.output_bits[:, :0]
    return Machine(
        f"{machine.name}:ports", sin, sout, machine.initial, ns, ob.copy()
    )


def reachable_submachine(machine: Machine) -> Tuple[Machine, np.ndarray]:
    seen = {machine.initial: 0}
    order = [machine.initial]
    queue = deque([machine.initial])
    while queue:
        s = queue.popleft()
        for target in machine.next_state[s]:
            t = int(target)
            if t not in seen:
                seen[t] = len(order)
                order.append(t)
                queue.append(t)
    old_to_new = np.full(machine.n_states, -1, dtype=np.int32)
    for new, old in enumerate(order):
        old_to_new[old] = new
    ns = old_to_new[machine.next_state[np.asarray(order, dtype=np.int32)]]
    ob = machine.output_bits[np.asarray(order, dtype=np.int32)]
    return Machine(
        f"{machine.name}:reach", machine.inputs, machine.outputs, 0, ns, ob
    ), old_to_new


def partition_minimize(machine: Machine) -> Tuple[Machine, np.ndarray]:
    m, old_to_reach = reachable_submachine(machine)
    n = m.n_states
    signature_to_block: Dict[Tuple[int, ...], int] = {}
    block = np.empty(n, dtype=np.int32)
    for s in range(n):
        sig = tuple(int(x) for x in m.output_bits[s])
        block[s] = signature_to_block.setdefault(sig, len(signature_to_block))
    while True:
        signature_to_block = {}
        next_block = np.empty(n, dtype=np.int32)
        for s in range(n):
            sig = (
                *(int(x) for x in m.output_bits[s]),
                -1,
                *(int(block[int(t)]) for t in m.next_state[s]),
            )
            next_block[s] = signature_to_block.setdefault(sig, len(signature_to_block))
        if np.array_equal(next_block, block):
            break
        block = next_block
    k = int(block.max()) + 1
    representatives = [int(np.flatnonzero(block == b)[0]) for b in range(k)]
    qnext = np.empty((k, m.alphabet_size), dtype=np.int32)
    qout = np.empty((k, len(m.outputs)), dtype=np.uint8)
    for b, r in enumerate(representatives):
        qnext[b] = block[m.next_state[r]]
        qout[b] = m.output_bits[r]
    quotient = Machine(
        f"{machine.name}:min", m.inputs, m.outputs, int(block[m.initial]), qnext, qout
    )
    quotient, q_old_to_new = reachable_submachine(quotient)
    reach_to_q = q_old_to_new[block]
    full_map = np.full(machine.n_states, -1, dtype=np.int32)
    for old in range(machine.n_states):
        reachable = int(old_to_reach[old])
        if reachable >= 0:
            full_map[old] = int(reach_to_q[reachable])
    return quotient, full_map


def remove_irrelevant_input_once(machine: Machine) -> Tuple[Machine, Optional[int]]:
    width = len(machine.inputs)
    if width == 0:
        return machine, None
    for bit in range(width):
        reduced_width = width - 1
        irrelevant = True
        for state in range(machine.n_states):
            for compact in range(1 << reduced_width):
                low = compact & ((1 << bit) - 1)
                high = compact >> bit
                i0 = low | (high << (bit + 1))
                i1 = i0 | (1 << bit)
                if int(machine.next_state[state, i0]) != int(machine.next_state[state, i1]):
                    irrelevant = False
                    break
            if not irrelevant:
                break
        if irrelevant:
            inputs = machine.inputs[:bit] + machine.inputs[bit + 1:]
            ns = np.empty((machine.n_states, 1 << reduced_width), dtype=np.int32)
            for compact in range(1 << reduced_width):
                low = compact & ((1 << bit) - 1)
                high = compact >> bit
                old = low | (high << (bit + 1))
                ns[:, compact] = machine.next_state[:, old]
            return Machine(
                f"{machine.name}:drop({machine.inputs[bit]})",
                inputs,
                machine.outputs,
                machine.initial,
                ns,
                machine.output_bits.copy(),
            ), bit
    return machine, None


def canonical_minimize(machine: Machine) -> Tuple[Machine, np.ndarray]:
    """Exact reachable Moore quotient plus semantically irrelevant input removal."""
    current = normalize_ports(machine)
    original_to_current = np.arange(machine.n_states, dtype=np.int32)
    while True:
        q, current_to_q = partition_minimize(current)
        valid = original_to_current >= 0
        composed = np.full_like(original_to_current, -1)
        composed[valid] = current_to_q[original_to_current[valid]]
        original_to_current = composed
        current = q
        reduced, removed = remove_irrelevant_input_once(current)
        if removed is None:
            break
        current = reduced
    q, current_to_q = partition_minimize(current)
    valid = original_to_current >= 0
    composed = np.full_like(original_to_current, -1)
    composed[valid] = current_to_q[original_to_current[valid]]
    return q, composed


def verify_quotient_homomorphism(raw: Machine, quotient: Machine, state_map: np.ndarray) -> bool:
    if len(state_map) != raw.n_states:
        return False
    if int(state_map[raw.initial]) != quotient.initial:
        return False
    if raw.outputs != quotient.outputs:
        return False
    if not set(quotient.inputs).issubset(raw.inputs):
        return False
    q_input_positions = [raw.inputs.index(x) for x in quotient.inputs]
    image = {int(x) for x in state_map if int(x) >= 0}
    if image != set(range(quotient.n_states)):
        return False
    for s in range(raw.n_states):
        qs = int(state_map[s])
        if qs < 0:
            continue
        if not np.array_equal(raw.output_bits[s], quotient.output_bits[qs]):
            return False
        for raw_value in range(raw.alphabet_size):
            q_value = 0
            for j, pos in enumerate(q_input_positions):
                q_value |= ((raw_value >> pos) & 1) << j
            raw_target = int(raw.next_state[s, raw_value])
            q_target = int(quotient.next_state[qs, q_value])
            if int(state_map[raw_target]) != q_target:
                return False
    return True


def independent_is_minimal(machine: Machine) -> bool:
    """Independent table-filling distinguishability check for reachable Moore states."""
    m, _ = reachable_submachine(normalize_ports(machine))
    n = m.n_states
    distinguishable = np.zeros((n, n), dtype=np.bool_)
    for i in range(n):
        for j in range(i):
            if not np.array_equal(m.output_bits[i], m.output_bits[j]):
                distinguishable[i, j] = True
    changed = True
    while changed:
        changed = False
        for i in range(n):
            for j in range(i):
                if distinguishable[i, j]:
                    continue
                for symbol in range(m.alphabet_size):
                    a = int(m.next_state[i, symbol])
                    b = int(m.next_state[j, symbol])
                    hi, lo = (a, b) if a > b else (b, a)
                    if hi != lo and distinguishable[hi, lo]:
                        distinguishable[i, j] = True
                        changed = True
                        break
    return all(bool(distinguishable[i, j]) for i in range(n) for j in range(i))


def _input_value(machine: Machine, ext_value: int, ext_pos: Mapping[str, int],
                 own: Mapping[str, int], other: Mapping[str, int]) -> int:
    value = 0
    for bit, signal in enumerate(machine.inputs):
        if signal in other:
            x = other[signal]
        elif signal in own:
            x = own[signal]
        else:
            p = ext_pos.get(signal)
            if p is None:
                raise KeyError(f"unresolved input {signal}")
            x = (ext_value >> p) & 1
        value |= int(x) << bit
    return value


def compose_raw(a: Machine, b: Machine, keep_outputs: Set[str],
                max_states: Optional[int] = None,
                max_transition_evaluations: Optional[int] = None
                ) -> Tuple[Machine, Tuple[Tuple[int, int], ...], int]:
    if set(a.outputs) & set(b.outputs):
        raise ValueError("active machines have duplicate output drivers")
    produced = set(a.outputs) | set(b.outputs)
    ext_inputs = tuple(sorted((set(a.inputs) | set(b.inputs)) - produced))
    out_names = tuple(sorted(keep_outputs & produced))
    ext_pos = {x: i for i, x in enumerate(ext_inputs)}

    initial = (a.initial, b.initial)
    pair_to_index: Dict[Tuple[int, int], int] = {initial: 0}
    pairs: List[Tuple[int, int]] = [initial]
    queue = deque([initial])
    transitions: List[List[int]] = []
    outputs: List[List[int]] = []
    evals = 0

    while queue:
        sa, sb = queue.popleft()
        ao = {x: int(a.output_bits[sa, j]) for j, x in enumerate(a.outputs)}
        bo = {x: int(b.output_bits[sb, j]) for j, x in enumerate(b.outputs)}
        visible = ao | bo
        outputs.append([visible[x] for x in out_names])
        row: List[int] = []
        for ext in range(1 << len(ext_inputs)):
            if max_transition_evaluations is not None and evals + 2 > max_transition_evaluations:
                raise CompositionTooLarge(
                    f"candidate exceeded {max_transition_evaluations} transition evaluations"
                )
            ia = _input_value(a, ext, ext_pos, ao, bo)
            ib = _input_value(b, ext, ext_pos, bo, ao)
            target = (int(a.next_state[sa, ia]), int(b.next_state[sb, ib]))
            evals += 2
            idx = pair_to_index.get(target)
            if idx is None:
                idx = len(pairs)
                if max_states is not None and idx + 1 > max_states:
                    raise CompositionTooLarge(f"candidate exceeded {max_states} reachable states")
                pair_to_index[target] = idx
                pairs.append(target)
                queue.append(target)
            row.append(idx)
        transitions.append(row)

    raw = Machine(
        f"({a.name}⊗{b.name})",
        ext_inputs,
        out_names,
        0,
        np.asarray(transitions, dtype=np.int32),
        np.asarray(outputs, dtype=np.uint8).reshape(len(outputs), len(out_names)),
    )
    return raw, tuple(pairs), evals


def compose_and_minimize(a: Machine, b: Machine, keep_outputs: Set[str],
                         max_states: Optional[int] = None,
                         max_transition_evaluations: Optional[int] = None
                         ) -> CompositionResult:
    raw, pairs, evals = compose_raw(
        a, b, keep_outputs,
        max_states=max_states,
        max_transition_evaluations=max_transition_evaluations,
    )
    quotient, state_map = canonical_minimize(raw)
    cert = QuotientCertificate(raw.digest(), quotient.digest(), state_map)
    cert.verified_homomorphism = verify_quotient_homomorphism(raw, quotient, state_map)
    cert.verified_minimal = independent_is_minimal(quotient)
    if not cert.verified_homomorphism or not cert.verified_minimal:
        raise AssertionError("generated quotient certificate failed independent verification")
    product_bound = max(1, a.n_states * b.n_states)
    reachable = max(1, raw.n_states)
    qstates = max(1, quotient.n_states)
    return CompositionResult(
        raw=raw,
        quotient=quotient,
        certificate=cert,
        product_states=pairs,
        reachability_gain_bits=log2(product_bound / reachable),
        quotient_gain_bits=log2(reachable / qstates),
        total_gain_bits=log2(product_bound / qstates),
        transition_evaluations=evals,
    )


def equivalent_machines(a: Machine, b: Machine) -> bool:
    """Independent reachable product equivalence over the union input alphabet."""
    a = normalize_ports(a)
    b = normalize_ports(b)
    if set(a.outputs) != set(b.outputs):
        return False
    outputs = tuple(sorted(a.outputs))
    ai = {x: i for i, x in enumerate(a.inputs)}
    bi = {x: i for i, x in enumerate(b.inputs)}
    ao = {x: i for i, x in enumerate(a.outputs)}
    bo = {x: i for i, x in enumerate(b.outputs)}
    inputs = tuple(sorted(set(a.inputs) | set(b.inputs)))
    input_pos = {x: i for i, x in enumerate(inputs)}
    start = (a.initial, b.initial)
    seen = {start}
    queue = deque([start])
    while queue:
        sa, sb = queue.popleft()
        if any(int(a.output_bits[sa, ao[x]]) != int(b.output_bits[sb, bo[x]]) for x in outputs):
            return False
        for value in range(1 << len(inputs)):
            va = 0
            vb = 0
            for name, pos in ai.items():
                va |= ((value >> input_pos[name]) & 1) << pos
            for name, pos in bi.items():
                vb |= ((value >> input_pos[name]) & 1) << pos
            target = (int(a.next_state[sa, va]), int(b.next_state[sb, vb]))
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return True


def machine_isomorphic(a: Machine, b: Machine) -> bool:
    qa, _ = canonical_minimize(a)
    qb, _ = canonical_minimize(b)
    return (
        qa.inputs == qb.inputs
        and qa.outputs == qb.outputs
        and qa.n_states == qb.n_states
        and qa.initial == qb.initial
        and np.array_equal(qa.next_state, qb.next_state)
        and np.array_equal(qa.output_bits, qb.output_bits)
    )
