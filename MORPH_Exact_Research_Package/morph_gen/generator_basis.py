from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json

from .aig import AIG
from .spec import CircuitSystem


@dataclass
class GeneratorBasis:
    """Explicit F/G/H circuits and their proof/synthesis metadata."""

    source: CircuitSystem
    f_functions: tuple[int, ...]
    macro_aig: AIG
    macro_state_variables: tuple[int, ...]
    macro_input_variables: tuple[int, ...]
    g_functions: tuple[int, ...]
    h_functions: tuple[int, ...]
    initial_macro_state: int
    reachable_macro_states: tuple[int, ...]
    backend: str
    synthesis_stats: dict[str, object] = field(default_factory=dict)
    minimality_status: str = "unproved"

    def __post_init__(self) -> None:
        if len(self.f_functions) != len(self.g_functions):
            raise ValueError("F and G widths differ")
        if len(self.macro_state_variables) != len(self.f_functions):
            raise ValueError("macro state variable width differs from F")
        if len(self.macro_input_variables) != len(self.source.input_variables):
            raise ValueError("macro input width differs from source")
        if len(self.h_functions) != len(self.source.output_functions):
            raise ValueError("H output width differs from source")

    @property
    def macro_bits(self) -> int:
        return len(self.f_functions)

    @property
    def f_gate_count(self) -> int:
        return self.source.aig.gate_count(self.f_functions)

    @property
    def g_gate_count(self) -> int:
        return self.macro_aig.gate_count(self.g_functions)

    @property
    def h_gate_count(self) -> int:
        return self.macro_aig.gate_count(self.h_functions)

    @property
    def bgc(self) -> int:
        return self.f_gate_count + self.g_gate_count + self.h_gate_count

    @property
    def f_support_size(self) -> int:
        support = self.source.aig.support(self.f_functions)
        return len(support & set(self.source.state_names))

    def evaluate_f(self, state: int) -> int:
        values = self.source.aig.evaluate_vector(
            self.f_functions, self.source.assignment(state)
        )
        return sum(int(value) << bit for bit, value in enumerate(values))

    def evaluate_g(self, macro_state: int, input_value: int) -> int:
        assignment = {
            self.macro_aig.nodes[node].name: bool((macro_state >> bit) & 1)
            for bit, node in enumerate(self.macro_state_variables)
        }
        assignment.update({
            self.macro_aig.nodes[node].name: bool((input_value >> bit) & 1)
            for bit, node in enumerate(self.macro_input_variables)
        })
        values = self.macro_aig.evaluate_vector(self.g_functions, assignment)
        return sum(int(value) << bit for bit, value in enumerate(values))

    def evaluate_h(self, macro_state: int) -> int:
        assignment = {
            self.macro_aig.nodes[node].name: bool((macro_state >> bit) & 1)
            for bit, node in enumerate(self.macro_state_variables)
        }
        assignment.update({
            self.macro_aig.nodes[node].name: False
            for node in self.macro_input_variables
        })
        values = self.macro_aig.evaluate_vector(self.h_functions, assignment)
        return sum(int(value) << bit for bit, value in enumerate(values))

    def digest(self) -> str:
        digest = sha256()
        digest.update(self.backend.encode())

        def update_graph(aig, roots, label: bytes) -> None:
            digest.update(label)
            digest.update(",".join(map(str, roots)).encode())
            for node in sorted(aig.reachable_nodes(roots)):
                gate = aig.nodes[node]
                digest.update(
                    f"{node}:{gate.op}:{gate.args}:{gate.name};".encode()
                )

        update_graph(self.source.aig, self.f_functions, b"F")
        update_graph(self.macro_aig, self.g_functions, b"G")
        update_graph(self.macro_aig, self.h_functions, b"H")
        digest.update(str(self.initial_macro_state).encode())
        digest.update(",".join(map(str, self.reachable_macro_states)).encode())
        return digest.hexdigest()

    def metrics(self) -> dict:
        return {
            "backend": self.backend,
            "macro_bits": self.macro_bits,
            "quotient_reachable_states": len(self.reachable_macro_states),
            "f_gate_count": self.f_gate_count,
            "g_gate_count": self.g_gate_count,
            "h_gate_count": self.h_gate_count,
            "total_bgc": self.bgc,
            "f_support_size": self.f_support_size,
            "minimality_status": self.minimality_status,
            "digest": self.digest(),
            **self.synthesis_stats,
        }


@dataclass
class SynthesisOutcome:
    basis: GeneratorBasis | None
    macro_machine: object | None
    certificate: object | None
    attempts: tuple[dict, ...]
    status: str


def synthesize_generator(system: CircuitSystem) -> SynthesisOutcome:
    """Run representation backends by proof/complexity, never by metadata."""
    from .affine_backend import synthesize_affine
    from .aig_cegis import synthesize_shared_aig
    from .anf_backend import synthesize_anf
    from .certificates import install_if_verified

    attempts: list[dict] = []
    candidates: list[tuple[GeneratorBasis, object, object]] = []

    affine = synthesize_affine(system)
    attempts.append({"backend": "affine", "reason": affine.reason})
    if affine.basis is not None:
        macro, certificate = install_if_verified(affine.basis)
        attempts[-1]["verified"] = certificate.verified
        if macro is not None:
            candidates.append((affine.basis, macro, certificate))
            # A proven minimal observable affine space is already optimal in k;
            # avoid converting thousands of affine micro bits to higher-degree
            # representations solely to rediscover the same basis.
            return SynthesisOutcome(
                affine.basis, macro, certificate, tuple(attempts), "SUPPORTED"
            )

    for degree in (1, 2, 3):
        result = synthesize_anf(system, max_degree=degree)
        attempt = {"backend": f"anf-degree-{degree}", "reason": result.reason}
        attempts.append(attempt)
        if result.basis is None:
            if "term limit" in result.reason.lower():
                break
            continue
        macro, certificate = install_if_verified(result.basis)
        attempt["verified"] = certificate.verified
        if macro is not None:
            candidates.append((result.basis, macro, certificate))
            return SynthesisOutcome(
                result.basis, macro, certificate, tuple(attempts), "SUPPORTED"
            )

    if not candidates:
        generic = synthesize_shared_aig(system)
        attempt = {"backend": "shared-aig-cegis", "reason": generic.reason}
        attempts.append(attempt)
        if generic.basis is not None:
            macro, certificate = install_if_verified(generic.basis)
            attempt["verified"] = certificate.verified
            if macro is not None:
                candidates.append((generic.basis, macro, certificate))

    if not candidates:
        return SynthesisOutcome(None, None, None, tuple(attempts), "REJECTED")
    candidates.sort(key=lambda item: (
        item[0].macro_bits,
        item[0].bgc,
        item[0].f_support_size,
        int(item[0].synthesis_stats.get("anf_degree_bound", 0)),
        item[2].proof_checking_seconds,
    ))
    basis, macro, certificate = candidates[0]
    return SynthesisOutcome(basis, macro, certificate, tuple(attempts), "SUPPORTED")
