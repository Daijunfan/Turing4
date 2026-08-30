from morph_gen.generator_basis import synthesize_generator
from morph_gen.scrambled_latent import affine_scaling_machine, make_slo


def test_generic_shared_aig_recovers_feistel_scramble():
    instance = make_slo(
        affine_scaling_machine(3, 31),
        8,
        encoding="feistel",
        seed=32,
        rounds=3,
    )
    outcome = synthesize_generator(instance.system)
    assert outcome.status == "SUPPORTED"
    assert outcome.basis.backend == "shared-aig-cegis"
    assert outcome.basis.macro_bits == 3
    assert outcome.certificate.verified
    assert outcome.certificate.explicit_isomorphism
