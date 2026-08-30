from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple
import random

import numpy as np

from .core import Machine, NetworkSpec, canonical_minimize


@dataclass
class HiddenNode:
    leaves: frozenset[int]
    left: "HiddenNode | None" = None
    right: "HiddenNode | None" = None
    name: str = ""


def _bits(x: int, width: int) -> List[int]:
    return [(x >> i) & 1 for i in range(width)]


def parity_accumulator(name: str = "parity") -> Machine:
    return Machine(
        name,
        (f"{name}.x",),
        (f"{name}.parity",),
        0,
        np.asarray([[0, 1], [1, 0]], dtype=np.int32),
        np.asarray([[0], [1]], dtype=np.uint8),
    )


def modulo_counter(modulus: int = 5, name: str = "counter") -> Machine:
    width = max(1, (modulus - 1).bit_length())
    ns = np.empty((modulus, 2), dtype=np.int32)
    ob = np.empty((modulus, width), dtype=np.uint8)
    for state in range(modulus):
        ns[state, 0] = state
        ns[state, 1] = (state + 1) % modulus
        ob[state] = _bits(state, width)
    return canonical_minimize(Machine(
        name,
        (f"{name}.inc",),
        tuple(f"{name}.q{i}" for i in range(width)),
        0,
        ns,
        ob,
    ))[0]


def pattern_detector(pattern: str = "1011", name: str = "pattern") -> Machine:
    prefixes = [pattern[:i] for i in range(len(pattern) + 1)]
    n = len(prefixes)
    ns = np.empty((n, 2), dtype=np.int32)
    ob = np.zeros((n, 1), dtype=np.uint8)
    ob[-1, 0] = 1
    for state, prefix in enumerate(prefixes):
        for bit in (0, 1):
            candidate = prefix + str(bit)
            next_state = 0
            for k in range(min(len(pattern), len(candidate)), -1, -1):
                if candidate.endswith(pattern[:k]):
                    next_state = k
                    break
            ns[state, bit] = next_state
    return canonical_minimize(Machine(
        name,
        (f"{name}.bit",),
        (f"{name}.match",),
        0,
        ns,
        ob,
    ))[0]


def handshake_controller(name: str = "handshake") -> Machine:
    inputs = (f"{name}.req", f"{name}.ack")
    outputs = (f"{name}.busy", f"{name}.done", f"{name}.error")
    ob = np.asarray([
        [0, 0, 0],  # idle
        [1, 0, 0],  # waiting
        [0, 1, 0],  # done
        [0, 0, 1],  # error
    ], dtype=np.uint8)
    ns = np.empty((4, 4), dtype=np.int32)
    for state in range(4):
        for value in range(4):
            req = value & 1
            ack = (value >> 1) & 1
            if state == 0:
                ns[state, value] = 1 if req and not ack else (3 if ack else 0)
            elif state == 1:
                ns[state, value] = 2 if ack else 1
            elif state == 2:
                ns[state, value] = 0 if not req else 2
            else:
                ns[state, value] = 0 if not req and not ack else 3
    return canonical_minimize(Machine(name, inputs, outputs, 0, ns, ob))[0]


def traffic_light(name: str = "traffic") -> Machine:
    inputs = (f"{name}.tick", f"{name}.emergency")
    outputs = (f"{name}.green", f"{name}.yellow", f"{name}.red")
    ob = np.asarray([
        [1, 0, 0],
        [0, 1, 0],
        [0, 0, 1],
        [0, 0, 1],
    ], dtype=np.uint8)
    ns = np.empty((4, 4), dtype=np.int32)
    for state in range(4):
        for value in range(4):
            tick = value & 1
            emergency = (value >> 1) & 1
            if emergency:
                ns[state, value] = 3
            elif state == 3:
                ns[state, value] = 2
            elif tick:
                ns[state, value] = {0: 1, 1: 2, 2: 0}[state]
            else:
                ns[state, value] = state
    return canonical_minimize(Machine(name, inputs, outputs, 0, ns, ob))[0]


def alternating_bit_protocol(name: str = "abp") -> Machine:
    # Compact sender-side alternating-bit controller with timeout/retry.
    # States: idle0, wait0, idle1, wait1, failed.
    inputs = (f"{name}.send", f"{name}.ack", f"{name}.timeout")
    outputs = (f"{name}.valid", f"{name}.seq", f"{name}.failed")
    ob = np.asarray([
        [0, 0, 0],
        [1, 0, 0],
        [0, 1, 0],
        [1, 1, 0],
        [0, 0, 1],
    ], dtype=np.uint8)
    ns = np.empty((5, 8), dtype=np.int32)
    for s in range(5):
        for v in range(8):
            send = v & 1
            ack = (v >> 1) & 1
            timeout = (v >> 2) & 1
            if s == 0:
                ns[s, v] = 1 if send else 0
            elif s == 1:
                ns[s, v] = 2 if ack else (4 if timeout and ack else 1)
            elif s == 2:
                ns[s, v] = 3 if send else 2
            elif s == 3:
                ns[s, v] = 0 if ack else (4 if timeout and ack else 3)
            else:
                ns[s, v] = 0 if not send and not ack else 4
    return canonical_minimize(Machine(name, inputs, outputs, 0, ns, ob))[0]


def synchronous_product(a: Machine, b: Machine, name: str = "product") -> Machine:
    if set(a.outputs) & set(b.outputs):
        raise ValueError("overlapping outputs")
    inputs = tuple(sorted(set(a.inputs) | set(b.inputs)))
    outputs = a.outputs + b.outputs
    pos = {x: i for i, x in enumerate(inputs)}
    ns = np.empty((a.n_states * b.n_states, 1 << len(inputs)), dtype=np.int32)
    ob = np.empty((a.n_states * b.n_states, len(outputs)), dtype=np.uint8)
    for sa in range(a.n_states):
        for sb in range(b.n_states):
            state = sa * b.n_states + sb
            ob[state] = np.concatenate((a.output_bits[sa], b.output_bits[sb]))
            for value in range(1 << len(inputs)):
                va = sum(((value >> pos[x]) & 1) << j for j, x in enumerate(a.inputs))
                vb = sum(((value >> pos[x]) & 1) << j for j, x in enumerate(b.inputs))
                ta = int(a.next_state[sa, va])
                tb = int(b.next_state[sb, vb])
                ns[state, value] = ta * b.n_states + tb
    initial = a.initial * b.n_states + b.initial
    return canonical_minimize(Machine(name, inputs, outputs, initial, ns, ob))[0]


def mixed_controller(name: str = "mixed") -> Machine:
    return synchronous_product(
        parity_accumulator(f"{name}.parity"),
        handshake_controller(f"{name}.handshake"),
        name,
    )


def root_family(name: str) -> Machine:
    if name == "parity":
        return parity_accumulator()
    if name == "counter":
        return modulo_counter(5, "counter5")
    if name == "pattern":
        return pattern_detector("1011", "pattern1011")
    if name == "handshake":
        return handshake_controller()
    if name == "traffic":
        return traffic_light()
    if name == "abp":
        return alternating_bit_protocol()
    if name == "mixed":
        return mixed_controller()
    raise KeyError(name)


def split_with_hidden_gauge(parent: Machine, split_id: str) -> Tuple[Machine, Machine]:
    """Exact semantics-preserving refinement into two coupled child transducers.

    Each child exposes one internal gauge bit. Separately, an arbitrary
    environment can drive the partner-input and all gauge states matter. Once
    exact siblings are composed, reciprocal signals are hidden and the gauges
    remain equal while toggling every synchronous step. The resulting reachable
    product contains a redundant phase bit that exact Moore minimization removes.
    """
    h_lr = f"__h.{split_id}.L2R"
    h_rl = f"__h.{split_id}.R2L"
    parent_width = len(parent.inputs)

    left_inputs = parent.inputs + (h_rl,)
    left_outputs = parent.outputs + (h_lr,)
    left_states = parent.n_states * 2
    left_ns = np.empty((left_states, 1 << len(left_inputs)), dtype=np.int32)
    left_ob = np.empty((left_states, len(left_outputs)), dtype=np.uint8)
    for p in range(parent.n_states):
        for gauge in (0, 1):
            state = p * 2 + gauge
            left_ob[state, :len(parent.outputs)] = parent.output_bits[p]
            left_ob[state, -1] = gauge
            for value in range(1 << len(left_inputs)):
                parent_value = value & ((1 << parent_width) - 1)
                other = (value >> parent_width) & 1
                p2 = int(parent.next_state[p, parent_value])
                left_ns[state, value] = p2 * 2 + (other ^ 1)

    right_ns = np.asarray([[1, 0], [1, 0]], dtype=np.int32)
    # input 0 -> 1, input 1 -> 0, i.e. other_g XOR 1
    right_ob = np.asarray([[0], [1]], dtype=np.uint8)

    left = Machine(
        f"{parent.name}/{split_id}.L",
        left_inputs,
        left_outputs,
        parent.initial * 2,
        left_ns,
        left_ob,
    )
    right = Machine(
        f"{parent.name}/{split_id}.R",
        (h_lr,),
        (h_rl,),
        0,
        right_ns,
        right_ob,
    )
    return left, right

def hidden_morphology(root: Machine, depth: int, seed: int = 0,
                      decoy_degree: int = 4) -> NetworkSpec:
    if depth < 1:
        raise ValueError("depth must be positive")
    rng = random.Random(seed)
    leaves: Dict[int, Machine] = {}
    oracle: Set[frozenset[int]] = set()
    split_counter = 0
    leaf_counter = 0

    def recurse(machine: Machine, remaining: int, path: str) -> HiddenNode:
        nonlocal split_counter, leaf_counter
        if remaining == 0:
            lid = leaf_counter
            leaf_counter += 1
            leaves[lid] = machine
            return HiddenNode(frozenset({lid}), name=path)
        split_id = f"{seed}.{split_counter}.{path}"
        split_counter += 1
        left, right = split_with_hidden_gauge(machine, split_id)
        ln = recurse(left, remaining - 1, path + "L")
        rn = recurse(right, remaining - 1, path + "R")
        cluster = ln.leaves | rn.leaves
        oracle.add(cluster)
        return HiddenNode(cluster, ln, rn, path)

    tree = recurse(root, depth, "R")

    producer: Dict[str, int] = {}
    consumers: Dict[str, Set[int]] = {}
    for lid, machine in leaves.items():
        for output in machine.outputs:
            producer[output] = lid
        for input_name in machine.inputs:
            consumers.setdefault(input_name, set()).add(lid)
    contacts: Set[Tuple[int, int]] = set()
    for signal, src in producer.items():
        for dst in consumers.get(signal, ()):
            if src != dst:
                contacts.add((min(src, dst), max(src, dst)))

    # Metadata-only decoys make structure-only ordering unreliable without
    # changing executable semantics.
    ids = sorted(leaves)
    target_total = len(contacts) + decoy_degree * len(ids) // 2
    attempts = 0
    while len(contacts) < target_total and attempts < target_total * 100:
        a, b = rng.sample(ids, 2)
        contacts.add((min(a, b), max(a, b)))
        attempts += 1

    return NetworkSpec(
        leaf_machines=leaves,
        global_outputs=set(root.outputs),
        contact_edges=contacts,
        oracle_clusters=oracle,
        metadata={
            "family": root.name,
            "depth": depth,
            "seed": seed,
            "decoy_degree": decoy_degree,
            "leaves": len(leaves),
            "root_digest": root.digest(),
            "tree": tree,
        },
    )


def parity_tree_network(depth: int, input_bits: int = 3, seed: int = 0,
                        decoy_degree: int = 4, name: str = "parity_tree") -> NetworkSpec:
    """Natural registered XOR-reduction network, not produced by inverse reification.

    Primitive leaves are independent one-bit accumulators driven by small shared
    input vectors. Every internal primitive is a one-bit registered XOR gate.
    The external observer sees only the root register. Although the primitive
    Cartesian state space has 2^(2^(d+1)-1) states, each complete subtree has a
    compact exact interface: a short pipeline of aggregate parities.
    """
    if depth < 1:
        raise ValueError("depth must be >= 1")
    if input_bits < 1:
        raise ValueError("input_bits must be >= 1")
    rng = random.Random(seed)
    machines: Dict[int, Machine] = {}
    oracle: Set[frozenset[int]] = set()
    next_id = 0
    global_inputs = tuple(f"{name}.u{j}" for j in range(input_bits))

    # Choose masks so that every leaf is input-responsive and sibling aggregates
    # are usually different. This is a natural linear system, not a hidden-gauge
    # inverse construction.
    def new_leaf(index: int) -> Tuple[int, str, frozenset[int]]:
        nonlocal next_id
        lid = next_id
        next_id += 1
        signal = f"{name}.leaf{index}"
        mask = rng.randrange(1, 1 << input_bits)
        ns = np.empty((2, 1 << input_bits), dtype=np.int32)
        ob = np.asarray([[0], [1]], dtype=np.uint8)
        for state in (0, 1):
            for value in range(1 << input_bits):
                toggle = (mask & value).bit_count() & 1
                ns[state, value] = state ^ toggle
        machines[lid] = Machine(
            f"{name}/leaf{index}", global_inputs, (signal,), 0, ns, ob
        )
        return lid, signal, frozenset({lid})

    def new_xor_node(left_signal: str, right_signal: str, tag: str,
                     left_set: frozenset[int], right_set: frozenset[int]) -> Tuple[int, str, frozenset[int]]:
        nonlocal next_id
        nid = next_id
        next_id += 1
        signal = f"{name}.xor.{tag}"
        # State stores the previous cycle's XOR of child outputs.
        ns = np.empty((2, 4), dtype=np.int32)
        for state in (0, 1):
            for value in range(4):
                ns[state, value] = (value & 1) ^ ((value >> 1) & 1)
        machines[nid] = Machine(
            f"{name}/xor/{tag}",
            (left_signal, right_signal),
            (signal,),
            0,
            ns,
            np.asarray([[0], [1]], dtype=np.uint8),
        )
        # A canonical binary reification witness: attach the gate to the left
        # subtree, then attach the right subtree. The algorithm is not told this.
        partial = left_set | frozenset({nid})
        full = partial | right_set
        oracle.add(partial)
        oracle.add(full)
        return nid, signal, full

    current = [new_leaf(i) for i in range(1 << depth)]
    level = 0
    while len(current) > 1:
        nxt = []
        for j in range(0, len(current), 2):
            _, ls, lset = current[j]
            _, rs, rset = current[j + 1]
            nxt.append(new_xor_node(ls, rs, f"L{level}N{j//2}", lset, rset))
        current = nxt
        level += 1
    _, root_signal, all_nodes = current[0]

    producer: Dict[str, int] = {}
    consumers: Dict[str, Set[int]] = {}
    for lid, m in machines.items():
        for output in m.outputs:
            producer[output] = lid
        for input_name in m.inputs:
            consumers.setdefault(input_name, set()).add(lid)
    contacts: Set[Tuple[int, int]] = set()
    for signal, src in producer.items():
        for dst in consumers.get(signal, ()):  # executable signal edges
            if src != dst:
                contacts.add((min(src, dst), max(src, dst)))

    ids = list(machines)
    actual_count = len(contacts)
    target_total = actual_count + decoy_degree * len(ids) // 2
    attempts = 0
    while len(contacts) < target_total and attempts < target_total * 50 + 100:
        a, b = rng.sample(ids, 2)
        contacts.add((min(a, b), max(a, b)))
        attempts += 1

    return NetworkSpec(
        leaf_machines=machines,
        global_outputs={root_signal},
        contact_edges=contacts,
        oracle_clusters=oracle,
        metadata={
            "family": "natural_registered_parity_tree",
            "depth": depth,
            "input_bits": input_bits,
            "seed": seed,
            "primitive_components": len(machines),
            "primitive_cartesian_log2": len(machines),
            "not_inverse_generated": True,
        },
    )


def modular_sum_tree_network(depth: int, modulus: int = 3, seed: int = 0,
                             decoy_degree: int = 4, name: str = "modsum_tree") -> NetworkSpec:
    """Natural registered modular-sum tree over q-state primitive machines."""
    if depth < 1 or modulus < 2:
        raise ValueError("depth>=1 and modulus>=2 required")
    rng = random.Random(seed)
    width = max(1, (modulus - 1).bit_length())
    machines: Dict[int, Machine] = {}
    oracle: Set[frozenset[int]] = set()
    next_id = 0
    global_inputs = tuple(f"{name}.u{j}" for j in range(width))

    def encode(value: int) -> List[int]:
        return [(value >> j) & 1 for j in range(width)]

    def decode(value: int, offset: int = 0) -> int:
        raw = 0
        for j in range(width):
            raw |= ((value >> (offset + j)) & 1) << j
        return raw % modulus

    def leaf(index: int) -> Tuple[int, Tuple[str, ...], frozenset[int]]:
        nonlocal next_id
        rid = next_id
        next_id += 1
        outputs = tuple(f"{name}.leaf{index}.b{j}" for j in range(width))
        # Uniform unit coefficients guarantee that the aggregate input influence
        # never vanishes for modulus=3 and a power-of-two leaf count.
        coefficient = 1
        ns = np.empty((modulus, 1 << width), dtype=np.int32)
        ob = np.empty((modulus, width), dtype=np.uint8)
        for state in range(modulus):
            ob[state] = encode(state)
            for value in range(1 << width):
                ns[state, value] = (state + coefficient * (value % modulus)) % modulus
        machines[rid] = Machine(
            f"{name}/leaf{index}", global_inputs, outputs, 0, ns, ob
        )
        return rid, outputs, frozenset({rid})

    def node(left_outputs: Tuple[str, ...], right_outputs: Tuple[str, ...], tag: str,
             left_set: frozenset[int], right_set: frozenset[int]) -> Tuple[int, Tuple[str, ...], frozenset[int]]:
        nonlocal next_id
        rid = next_id
        next_id += 1
        outputs = tuple(f"{name}.sum.{tag}.b{j}" for j in range(width))
        inputs = left_outputs + right_outputs
        ns = np.empty((modulus, 1 << (2 * width)), dtype=np.int32)
        ob = np.empty((modulus, width), dtype=np.uint8)
        for state in range(modulus):
            ob[state] = encode(state)
            for value in range(1 << (2 * width)):
                ns[state, value] = (decode(value, 0) + decode(value, width)) % modulus
        machines[rid] = Machine(f"{name}/sum/{tag}", inputs, outputs, 0, ns, ob)
        partial = left_set | frozenset({rid})
        full = partial | right_set
        oracle.add(partial)
        oracle.add(full)
        return rid, outputs, full

    current = [leaf(i) for i in range(1 << depth)]
    level = 0
    while len(current) > 1:
        nxt = []
        for j in range(0, len(current), 2):
            _, lo, ls = current[j]
            _, ro, rs = current[j + 1]
            nxt.append(node(lo, ro, f"L{level}N{j//2}", ls, rs))
        current = nxt
        level += 1
    _, root_outputs, _ = current[0]

    producer: Dict[str, int] = {}
    consumers: Dict[str, Set[int]] = {}
    for rid, m in machines.items():
        for output in m.outputs:
            producer[output] = rid
        for input_name in m.inputs:
            consumers.setdefault(input_name, set()).add(rid)
    contacts: Set[Tuple[int, int]] = set()
    for signal, src in producer.items():
        for dst in consumers.get(signal, ()):
            if src != dst:
                contacts.add((min(src, dst), max(src, dst)))
    ids = list(machines)
    target_total = len(contacts) + decoy_degree * len(ids) // 2
    attempts = 0
    while len(contacts) < target_total and attempts < target_total * 50 + 100:
        a, b = rng.sample(ids, 2)
        contacts.add((min(a, b), max(a, b)))
        attempts += 1

    return NetworkSpec(
        leaf_machines=machines,
        global_outputs=set(root_outputs),
        contact_edges=contacts,
        oracle_clusters=oracle,
        metadata={
            "family": "natural_registered_modular_sum_tree",
            "depth": depth,
            "modulus": modulus,
            "seed": seed,
            "primitive_components": len(machines),
            "primitive_cartesian_base": modulus,
            "primitive_cartesian_exponent": len(machines),
            "not_inverse_generated": True,
        },
    )
