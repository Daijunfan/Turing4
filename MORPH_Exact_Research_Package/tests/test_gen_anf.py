from morph_gen.generator_basis import synthesize_generator
from morph_gen.scrambled_latent import affine_scaling_machine, make_slo


def test_degree_two_anf_backend_recovers_triangular_scramble():
    instance = make_slo(
        affine_scaling_machine(4, 21),
        32,
        encoding="triangular",
        seed=22,
        degree=2,
        sparsity=4,
    )
    outcome = synthesize_generator(instance.system)
    assert outcome.status == "SUPPORTED"
    assert outcome.basis.backend == "anf"
    assert outcome.basis.macro_bits == 4
    assert outcome.basis.synthesis_stats["anf_degree_bound"] == 2
    assert outcome.certificate.verified
