from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from morph_exact.core import Machine, canonical_minimize


def dependency_signature(machine: Machine) -> tuple[tuple[int, int], ...]:
    edges = []
    for target_bit in range(2):
        values = ((machine.next_state >> target_bit) & 1).reshape(-1)
        for source_bit in range(2):
            depends = any(
                values[state] != values[state ^ (1 << source_bit)]
                for state in range(4) if not (state >> source_bit) & 1
            )
            if depends:
                edges.append((source_bit, target_bit))
    return tuple(edges)


def main() -> None:
    # Same two-node cross-coupled graph and output, different transition
    # semantics from the same initial state.
    output = np.asarray([[0], [1], [0], [1]], dtype=np.uint8)
    first_next = np.asarray([[0], [2], [1], [3]], dtype=np.int32).reshape(4, 1)
    second_next = np.asarray([[1], [3], [0], [2]], dtype=np.int32).reshape(4, 1)
    first = Machine("graph-twin-a", (), ("o",), 0, first_next, output)
    second = Machine("graph-twin-b", (), ("o",), 0, second_next, output)
    signature_a = dependency_signature(first)
    signature_b = dependency_signature(second)
    quotient_a = canonical_minimize(first)[0]
    quotient_b = canonical_minimize(second)[0]
    assert signature_a == signature_b
    assert quotient_a.n_states != quotient_b.n_states
    record = {
        "nodes": 2,
        "dependency_edges": signature_a,
        "degree_sequence": [1, 1],
        "scc_sizes": [2],
        "machine_a": {
            "next_state": first_next.tolist(),
            "output": output.tolist(),
            "initial": 0,
            "quotient_states": quotient_a.n_states,
        },
        "machine_b": {
            "next_state": second_next.tolist(),
            "output": output.tolist(),
            "initial": 0,
            "quotient_states": quotient_b.n_states,
        },
        "conclusion": "identical dependency structure does not determine behavior quotient",
        "exhaustive_proof": True,
    }
    path = Path("results_gen/counterexamples/structural_nonidentifiability.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
