from __future__ import annotations

from collections import deque
from typing import Dict, List, Set, Tuple

import numpy as np

from .core import Machine, NetworkSpec, canonical_minimize


def monolithic_compose(spec: NetworkSpec, max_states: int = 1_000_000,
                       max_transition_evaluations: int = 20_000_000) -> Machine:
    """Independent slow reference that directly simulates all primitive leaves."""
    lids = sorted(spec.leaf_machines)
    machines = [spec.leaf_machines[x] for x in lids]
    produced = {x for machine in machines for x in machine.outputs}
    ext_inputs = tuple(sorted({x for machine in machines for x in machine.inputs if x not in produced}))
    out_names = tuple(sorted(spec.global_outputs))
    ext_pos = {x: i for i, x in enumerate(ext_inputs)}

    initial = tuple(machine.initial for machine in machines)
    state_to_index = {initial: 0}
    states = [initial]
    queue = deque([initial])
    transitions: List[List[int]] = []
    outputs: List[List[int]] = []
    evals = 0

    while queue:
        state = queue.popleft()
        signal: Dict[str, int] = {}
        for i, machine in enumerate(machines):
            for j, name in enumerate(machine.outputs):
                if name in signal:
                    raise ValueError("multiple drivers")
                signal[name] = int(machine.output_bits[state[i], j])
        outputs.append([signal[x] for x in out_names])
        row: List[int] = []
        for ext in range(1 << len(ext_inputs)):
            target: List[int] = []
            for i, machine in enumerate(machines):
                value = 0
                for bit, name in enumerate(machine.inputs):
                    if name in signal:
                        x = signal[name]
                    else:
                        x = (ext >> ext_pos[name]) & 1
                    value |= x << bit
                target.append(int(machine.next_state[state[i], value]))
                evals += 1
                if evals > max_transition_evaluations:
                    raise RuntimeError("monolithic reference transition cap exceeded")
            target_tuple = tuple(target)
            idx = state_to_index.get(target_tuple)
            if idx is None:
                idx = len(states)
                if idx + 1 > max_states:
                    raise RuntimeError("monolithic reference state cap exceeded")
                state_to_index[target_tuple] = idx
                states.append(target_tuple)
                queue.append(target_tuple)
            row.append(idx)
        transitions.append(row)

    raw = Machine(
        "monolithic",
        ext_inputs,
        out_names,
        0,
        np.asarray(transitions, dtype=np.int32),
        np.asarray(outputs, dtype=np.uint8).reshape(len(outputs), len(out_names)),
    )
    return canonical_minimize(raw)[0]
