from __future__ import annotations

from random import Random

import numpy as np

from morph_exact.core import Machine, NetworkSpec


def gauge_cycle_network(n: int, seed: int = 0) -> NetworkSpec:
    """Return the stated synchronous network using only executable port wiring.

    Metadata contains no target macro, semantic family tag, or decomposition
    hierarchy.  Optional contacts are semantic no-ops and are generated solely
    from ``seed``; executable dependencies remain available as ``signal_edges``.
    """
    if n < 2:
        raise ValueError("n must be at least two")
    machines: dict[int, Machine] = {}
    outputs = np.asarray([[0], [1]], dtype=np.uint8)
    transitions = np.empty((2, 4), dtype=np.int32)
    for state in (0, 1):
        for value in range(4):
            shared_input = value & 1
            predecessor = (value >> 1) & 1
            transitions[state, value] = predecessor ^ shared_input
    for i in range(n):
        machines[i] = Machine(
            f"component-{i}",
            ("u", f"y{(i - 1) % n}"),
            (f"y{i}",),
            0,
            transitions.copy(),
            outputs.copy(),
        )

    # NetworkSpec derives every executable contact from real producer/consumer
    # ports.  Seeded extra contacts deliberately carry no execution semantics.
    contacts: set[tuple[int, int]] = set()
    rng = Random(seed)
    decoys = min(n // 4, max(0, n * (n - 1) // 2 - n))
    while len(contacts) < decoys:
        a, b = rng.sample(range(n), 2)
        edge = (min(a, b), max(a, b))
        if (a - b) % n not in (1, n - 1):
            contacts.add(edge)
    return NetworkSpec(
        leaf_machines=machines,
        global_outputs={"y0"},
        contact_edges=contacts,
        metadata={"component_count": n, "seed": seed, "contact_decoys": len(contacts)},
    )


def parity_accumulator_reference() -> Machine:
    """Independent two-state Moore reference used only by validators."""
    return Machine(
        "two-state-reference",
        ("u",),
        ("y0",),
        0,
        np.asarray([[0, 1], [1, 0]], dtype=np.int32),
        np.asarray([[0], [1]], dtype=np.uint8),
    )
