from morph_gen.generator_basis import synthesize_generator
from morph_gen.scrambled_latent import affine_scaling_machine, make_slo
from morph_gen.structural_obfuscation import verify_obfuscation


def test_affine_backend_recovers_dense_scramble_without_coordinate_selection():
    instance = make_slo(
        affine_scaling_machine(4, 11), 32, encoding="affine", seed=12
    )
    outcome = synthesize_generator(instance.system)
    obfuscation = verify_obfuscation(
        instance.system, instance.decoder_functions, r=2
    )
    assert outcome.status == "SUPPORTED"
    assert outcome.basis.backend == "affine"
    assert outcome.basis.macro_bits == 4
    assert outcome.certificate.verified
    assert not outcome.basis.synthesis_stats["enumerated_micro_states"]
    assert obfuscation.verified
    assert obfuscation.minimum_coordinates_determining_macro > 2
