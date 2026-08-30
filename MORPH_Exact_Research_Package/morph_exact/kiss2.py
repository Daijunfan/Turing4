from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .core import Machine, canonical_minimize


@dataclass(frozen=True)
class KissTransition:
    pattern: str
    source: str
    target: str
    output: str


@dataclass(frozen=True)
class KissModel:
    input_count: int
    output_count: int
    state_count_declared: Optional[int]
    product_count_declared: Optional[int]
    reset_state: Optional[str]
    transitions: Tuple[KissTransition, ...]


def parse_kiss2_text(text: str) -> KissModel:
    input_count: Optional[int] = None
    output_count: Optional[int] = None
    state_count: Optional[int] = None
    product_count: Optional[int] = None
    reset: Optional[str] = None
    transitions: List[KissTransition] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("."):
            parts = line.split()
            key = parts[0]
            if key == ".i":
                input_count = int(parts[1])
            elif key == ".o":
                output_count = int(parts[1])
            elif key == ".s":
                state_count = int(parts[1])
            elif key == ".p":
                product_count = int(parts[1])
            elif key == ".r":
                reset = parts[1]
            elif key in {".e", ".end", ".type"}:
                continue
            continue
        parts = line.split()
        if len(parts) != 4:
            raise ValueError(f"invalid KISS2 transition: {line}")
        transitions.append(KissTransition(*parts))

    if input_count is None or output_count is None:
        raise ValueError("KISS2 file lacks .i or .o declaration")
    for t in transitions:
        if len(t.pattern) != input_count:
            raise ValueError(f"input pattern width mismatch: {t.pattern}")
        if len(t.output) != output_count:
            raise ValueError(f"output pattern width mismatch: {t.output}")
        if any(c not in "01-" for c in t.pattern + t.output):
            raise ValueError("only binary and '-' KISS2 patterns are supported")
    return KissModel(
        input_count=input_count,
        output_count=output_count,
        state_count_declared=state_count,
        product_count_declared=product_count,
        reset_state=reset,
        transitions=tuple(transitions),
    )


def _pattern_matches(pattern: str, value: int) -> bool:
    for j, ch in enumerate(pattern):
        if ch != "-" and int(ch) != ((value >> j) & 1):
            return False
    return True


def _output_value(pattern: str) -> int:
    # For benchmark roots used here outputs are fully specified. Refuse to guess
    # don't-care outputs because doing so would change the benchmark semantics.
    if "-" in pattern:
        raise ValueError("KISS2 output don't-cares require an explicit completion policy")
    value = 0
    for j, ch in enumerate(pattern):
        value |= int(ch) << j
    return value


def kiss_to_moore(model: KissModel, name: str = "kiss") -> Machine:
    """Convert a complete deterministic KISS2 Mealy machine to an exact Moore machine.

    The Moore state stores (Mealy control state, output emitted by the previous
    transition). Thus the Moore trace equals the Mealy output trace with one
    initial zero-output symbol prepended. This standard state-splitting transform
    preserves all future behavior and makes the benchmark compatible with the
    synchronous open-machine core used by MORPH-Exact.
    """
    if not model.transitions:
        raise ValueError("empty KISS2 machine")
    states = sorted({t.source for t in model.transitions} | {t.target for t in model.transitions})
    reset = model.reset_state or model.transitions[0].source
    if reset not in states:
        raise ValueError("reset state not present")

    table: Dict[Tuple[str, int], Tuple[str, int]] = {}
    for source in states:
        rules = [t for t in model.transitions if t.source == source]
        for value in range(1 << model.input_count):
            matches = [t for t in rules if _pattern_matches(t.pattern, value)]
            if not matches:
                raise ValueError(f"incomplete KISS2 transition table at {source}, input {value}")
            resolved = {(t.target, _output_value(t.output)) for t in matches}
            if len(resolved) != 1:
                raise ValueError(f"nondeterministic/overlapping KISS2 terms at {source}, input {value}: {resolved}")
            table[(source, value)] = next(iter(resolved))

    initial_pair = (reset, 0)
    pair_to_index: Dict[Tuple[str, int], int] = {initial_pair: 0}
    pairs: List[Tuple[str, int]] = [initial_pair]
    queue = deque([initial_pair])
    rows: List[List[int]] = []
    outputs: List[List[int]] = []
    while queue:
        control, last_output = queue.popleft()
        outputs.append([(last_output >> j) & 1 for j in range(model.output_count)])
        row: List[int] = []
        for value in range(1 << model.input_count):
            target_control, emitted = table[(control, value)]
            target = (target_control, emitted)
            idx = pair_to_index.get(target)
            if idx is None:
                idx = len(pairs)
                pair_to_index[target] = idx
                pairs.append(target)
                queue.append(target)
            row.append(idx)
        rows.append(row)

    machine = Machine(
        name=name,
        inputs=tuple(f"{name}.i{j}" for j in range(model.input_count)),
        outputs=tuple(f"{name}.o{j}" for j in range(model.output_count)),
        initial=0,
        next_state=np.asarray(rows, dtype=np.int32),
        output_bits=np.asarray(outputs, dtype=np.uint8),
    )
    return canonical_minimize(machine)[0]


def load_kiss2(path: str | Path, name: Optional[str] = None) -> Machine:
    p = Path(path)
    model = parse_kiss2_text(p.read_text())
    return kiss_to_moore(model, name or p.stem)
