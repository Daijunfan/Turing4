from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from typing import Mapping, Sequence

import numpy as np

from morph_exact.core import Machine, canonical_minimize
from morph_lift.symbolic import BDD_BACKEND, SymbolicMachine, _equiv, _new_bdd

from .aig import AIG


_SYSTEM_IDS = count()


@dataclass
class CircuitSystem:
    """Public circuit-level deterministic system supplied to MORPH-GEN."""

    name: str
    aig: AIG
    state_variables: tuple[int, ...]
    input_variables: tuple[int, ...]
    next_functions: tuple[int, ...]
    output_functions: tuple[int, ...]
    initial_predicate: int
    valid_predicate: int
    reachable_predicate: int
    syntactic_dependencies: frozenset[tuple[int, int]] = frozenset()
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.state_variables) != len(self.next_functions):
            raise ValueError("one next function is required for each state bit")
        forbidden = {"family", "encoding", "latent", "oracle", "phi", "partition"}
        if any(any(word in str(key).lower() for word in forbidden) for key in self.metadata):
            raise ValueError("public metadata leaks a forbidden synthesis oracle")

    @property
    def state_names(self) -> tuple[str, ...]:
        return tuple(self.aig.nodes[node].name for node in self.state_variables)

    @property
    def input_names(self) -> tuple[str, ...]:
        return tuple(self.aig.nodes[node].name for node in self.input_variables)

    @property
    def output_names(self) -> tuple[str, ...]:
        return tuple(f"o{i}" for i in range(len(self.output_functions)))

    @property
    def micro_bits(self) -> int:
        return len(self.state_variables)

    def assignment(self, state: int, input_value: int = 0) -> dict[str, bool]:
        values = {
            name: bool((state >> bit) & 1)
            for bit, name in enumerate(self.state_names)
        }
        values.update({
            name: bool((input_value >> bit) & 1)
            for bit, name in enumerate(self.input_names)
        })
        return values

    def evaluate_next(self, state: int, input_value: int) -> int:
        assignment = self.assignment(state, input_value)
        bits = self.aig.evaluate_vector(self.next_functions, assignment)
        return sum(int(value) << bit for bit, value in enumerate(bits))

    def evaluate_output(self, state: int) -> int:
        assignment = self.assignment(state)
        bits = self.aig.evaluate_vector(self.output_functions, assignment)
        return sum(int(value) << bit for bit, value in enumerate(bits))

    def predicate_holds(self, predicate: int, state: int) -> bool:
        return self.aig.evaluate(predicate, self.assignment(state))

    def to_symbolic(self) -> SymbolicMachine:
        uid = next(_SYSTEM_IDS)
        bdd = _new_bdd()
        current = tuple(f"gen_{uid}_x{i}" for i in range(self.micro_bits))
        nxt = tuple(f"gen_{uid}_xn{i}" for i in range(self.micro_bits))
        inputs = tuple(f"gen_{uid}_u{i}" for i in range(len(self.input_variables)))
        bdd.declare(*(x for pair in zip(current, nxt) for x in pair), *inputs)
        input_map = {
            self.aig.nodes[node].name: bdd.var(name)
            for node, name in zip(self.state_variables, current)
        }
        input_map.update({
            self.aig.nodes[node].name: bdd.var(name)
            for node, name in zip(self.input_variables, inputs)
        })
        values = [bdd.false, bdd.true]
        for gate in self.aig.nodes[2:]:
            if gate.op == "INPUT":
                values.append(input_map[gate.name])
            elif gate.op == "AND":
                values.append(values[gate.args[0]] & values[gate.args[1]])
            elif gate.op == "XOR":
                left, right = values[gate.args[0]], values[gate.args[1]]
                values.append((left & ~right) | (~left & right))
            elif gate.op == "NOT":
                values.append(~values[gate.args[0]])
            else:
                values.append(bdd.ite(
                    values[gate.args[0]], values[gate.args[1]], values[gate.args[2]]
                ))
        next_functions = tuple(values[root] for root in self.next_functions)
        partitions = tuple(
            _equiv(bdd.var(name), function)
            for name, function in zip(nxt, next_functions)
        )
        outputs = {
            name: values[root] for name, root in zip(self.output_names, self.output_functions)
        }
        return SymbolicMachine(
            self.name,
            bdd,
            current,
            nxt,
            inputs,
            outputs,
            values[self.initial_predicate],
            values[self.valid_predicate],
            None,
            next_functions,
            values[self.reachable_predicate],
            certificate_metadata={
                "backend": BDD_BACKEND,
                "source": "MORPH-GEN CircuitSystem",
                "compiled_without_state_enumeration": True,
            },
            variable_order="dependency",
            transition_partitions=partitions,
        )

    def to_explicit(self, max_bits: int = 20) -> Machine:
        if self.micro_bits > max_bits:
            raise ValueError("explicit micro-state limit exceeded")
        from .predicate_pool import _bdd_roots

        bdd, (initial_bdd,) = _bdd_roots(self, (self.initial_predicate,))
        witness = bdd.pick(initial_bdd, care_vars=set(self.state_names))
        if witness is None:
            raise ValueError("no initial state")
        # Any nuisance initial valuation has the same observable behavior by
        # construction; choose the lexicographically first concrete witness.
        initial = sum(
            int(witness[name]) << bit for bit, name in enumerate(self.state_names)
        )
        index = {initial: 0}
        order = [initial]
        cursor = 0
        transitions: list[list[int]] = []
        outputs: list[list[int]] = []
        while cursor < len(order):
            state = order[cursor]
            output = self.evaluate_output(state)
            outputs.append([
                (output >> bit) & 1 for bit in range(len(self.output_functions))
            ])
            row = []
            for input_value in range(1 << len(self.input_variables)):
                target = self.evaluate_next(state, input_value)
                if target not in index:
                    index[target] = len(order)
                    order.append(target)
                row.append(index[target])
            transitions.append(row)
            cursor += 1
        machine = Machine(
            self.name,
            self.input_names,
            self.output_names,
            0,
            np.asarray(transitions, dtype=np.int32),
            np.asarray(outputs, dtype=np.uint8),
        )
        return canonical_minimize(machine)[0]

    def public_manifest(self) -> dict:
        return {
            "name": self.name,
            "micro_bits": self.micro_bits,
            "input_bits": len(self.input_variables),
            "output_bits": len(self.output_functions),
            "aig_gates": self.aig.gate_count((
                *self.next_functions,
                *self.output_functions,
                self.initial_predicate,
                self.valid_predicate,
                self.reachable_predicate,
            )),
            "metadata": dict(self.metadata),
        }
