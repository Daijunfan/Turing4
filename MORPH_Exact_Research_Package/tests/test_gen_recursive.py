from morph_exact.core import Machine
from morph_exact.generators import synchronous_product
from morph_gen.generator_basis import synthesize_generator
from morph_gen.recursive_factorization import factor_macro_dynamics
from morph_gen.scrambled_latent import affine_scaling_machine, make_slo


def _rename(machine: Machine, index: int) -> Machine:
    return Machine(
        f"organ-{index}",
        (f"u{index}",),
        (f"o{index}",),
        machine.initial,
        machine.next_state,
        machine.output_bits,
    )


def test_global_mix_recovers_independent_macro_blocks_and_higher_atom():
    latent = synchronous_product(
        _rename(affine_scaling_machine(2, 1), 0),
        _rename(affine_scaling_machine(2, 2), 1),
        "heterogeneous-product",
    )
    instance = make_slo(latent, 16, encoding="affine", seed=51)
    outcome = synthesize_generator(instance.system)
    factorization = factor_macro_dynamics(outcome.basis)
    assert outcome.certificate.verified
    assert factorization.recursion_depth == 2
    assert factorization.recovered_organ_count == 2
    assert all(block.independent for block in factorization.blocks)
    assert factorization.proof["metadata_used"] is False
    assert outcome.macro_machine.unfold()[0] == instance.system.state_names
