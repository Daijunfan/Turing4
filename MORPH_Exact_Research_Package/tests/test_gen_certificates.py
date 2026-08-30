from dataclasses import replace

from morph_gen.certificates import verify_generator_basis
from morph_gen.generator_basis import synthesize_generator
from morph_gen.scrambled_latent import affine_scaling_machine, make_slo


def test_dual_certificate_accepts_exact_basis_and_rejects_tampering():
    instance = make_slo(
        affine_scaling_machine(3, 41), 12, encoding="triangular", seed=42
    )
    outcome = synthesize_generator(instance.system)
    assert outcome.certificate.verified
    bad_g = list(outcome.basis.g_functions)
    bad_g[0] = outcome.basis.macro_aig.not_(bad_g[0])
    tampered = replace(outcome.basis, g_functions=tuple(bad_g))
    certificate = verify_generator_basis(tampered)
    assert not certificate.verified
    assert not certificate.bdd_conditions["transition_commutation"]
    assert certificate.z3_conditions["transition_commutation"] == "SAT"
