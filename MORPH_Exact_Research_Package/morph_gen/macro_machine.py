from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from morph_exact.core import Machine
from morph_exact.core import canonical_minimize
from morph_lift.symbolic import SymbolicMachine

from .generator_basis import GeneratorBasis


@dataclass
class MacroMachine:
    """Reified generator basis compatible with the existing symbolic atom API."""

    basis: GeneratorBasis
    machine: Machine
    symbolic: SymbolicMachine
    micro_relation: tuple[int, ...]
    proof_chain: tuple[dict, ...] = ()

    @classmethod
    def reify(cls, basis: GeneratorBasis, proof: dict | None = None) -> "MacroMachine":
        states = basis.reachable_macro_states
        index = {state: position for position, state in enumerate(states)}
        transitions = np.empty(
            (len(states), 1 << len(basis.macro_input_variables)), dtype=np.int32
        )
        outputs = np.empty(
            (len(states), len(basis.h_functions)), dtype=np.uint8
        )
        for row, state in enumerate(states):
            output = basis.evaluate_h(state)
            outputs[row] = [
                (output >> bit) & 1 for bit in range(len(basis.h_functions))
            ]
            for input_value in range(transitions.shape[1]):
                target = basis.evaluate_g(state, input_value)
                if target not in index:
                    raise ValueError("G leaves the certified reachable macro set")
                transitions[row, input_value] = index[target]
        machine = Machine(
            f"{basis.source.name}:generated-macro",
            basis.source.input_names,
            basis.source.output_names,
            index[basis.initial_macro_state],
            transitions,
            outputs,
        )
        symbolic = SymbolicMachine.from_explicit(
            machine, variable_order="dependency", prefix="generated_macro"
        )
        return cls(
            basis,
            machine,
            symbolic,
            basis.f_functions,
            (proof,) if proof else (),
        )

    def compose(
        self,
        others: list["MacroMachine | SymbolicMachine"],
        keep_outputs: set[str],
    ) -> SymbolicMachine:
        atoms = [self.symbolic]
        atoms.extend(
            item.symbolic if isinstance(item, MacroMachine) else item
            for item in others
        )
        return SymbolicMachine.compose(atoms, keep_outputs, name="generated-recursive-product")

    def unfold(self) -> tuple[tuple[str, ...], tuple[int, ...]]:
        return self.basis.source.state_names, self.micro_relation

    def minimize(self) -> Machine:
        return canonical_minimize(self.machine)[0]

    def predicate_synthesis(self):
        from .generator_basis import synthesize_generator

        return synthesize_generator(self.basis.source)

    def recursive_organ_formation(self):
        from .recursive_factorization import factor_macro_dynamics

        return factor_macro_dynamics(self.basis)

    def with_proof(self, proof: dict) -> "MacroMachine":
        self.proof_chain += (proof,)
        return self
