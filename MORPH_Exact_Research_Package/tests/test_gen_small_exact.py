from math import ceil, log2
from pathlib import Path

from morph_gen.generator_basis import synthesize_generator
from morph_gen.scrambled_latent import latent_machine_catalog, make_slo


def test_six_latent_machine_classes_match_explicit_minimal_quotients():
    catalog = latent_machine_catalog(Path(__file__).parents[1] / "benchmarks")
    for seed, name in enumerate((
        "parity", "modulo3", "modulo5", "pattern", "handshake", "traffic"
    ), start=100):
        latent = catalog[name]
        instance = make_slo(latent, 10, encoding="affine", seed=seed)
        outcome = synthesize_generator(instance.system)
        assert outcome.status == "SUPPORTED", (name, outcome.attempts)
        assert outcome.certificate.verified
        assert outcome.certificate.explicit_isomorphism
        assert outcome.basis.macro_bits == ceil(log2(latent.n_states))
        assert len(outcome.basis.reachable_macro_states) == latent.n_states
