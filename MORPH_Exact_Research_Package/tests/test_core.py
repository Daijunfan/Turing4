import numpy as np

from morph_exact.core import (
    Machine,
    canonical_minimize,
    equivalent_machines,
    independent_is_minimal,
    machine_isomorphic,
    verify_quotient_homomorphism,
    compose_and_minimize,
)
from morph_exact.engine import MorphEngine
from morph_exact.generators import hidden_morphology, root_family, split_with_hidden_gauge
from morph_exact.reference import monolithic_compose


def random_machine(seed: int, states: int, inputs: int, outputs: int) -> Machine:
    rng = np.random.default_rng(seed)
    return Machine(
        f"random{seed}",
        tuple(f"i{j}" for j in range(inputs)),
        tuple(f"o{j}" for j in range(outputs)),
        0,
        rng.integers(0, states, size=(states, 1 << inputs), dtype=np.int32),
        rng.integers(0, 2, size=(states, outputs), dtype=np.uint8),
    )


def test_exhaustive_two_state_minimizer():
    # All 64 deterministic Moore machines with 2 states, 1 input, 1 output.
    for transition_code in range(16):
        ns = np.empty((2, 2), dtype=np.int32)
        for k in range(4):
            ns[k // 2, k % 2] = (transition_code >> k) & 1
        for output_code in range(4):
            ob = np.asarray([[(output_code >> 0) & 1], [(output_code >> 1) & 1]], dtype=np.uint8)
            machine = Machine("exhaustive", ("i",), ("o",), 0, ns, ob)
            quotient, mapping = canonical_minimize(machine)
            assert verify_quotient_homomorphism(machine, quotient, mapping)
            assert independent_is_minimal(quotient)
            assert equivalent_machines(machine, quotient)


def test_random_minimization_certificates():
    for seed in range(250):
        machine = random_machine(seed, 2 + seed % 7, 1 + seed % 3, 1 + seed % 2)
        quotient, mapping = canonical_minimize(machine)
        assert verify_quotient_homomorphism(machine, quotient, mapping)
        assert independent_is_minimal(quotient)
        assert equivalent_machines(machine, quotient)


def test_hidden_gauge_exactly_recovers_parent():
    for family in ["parity", "counter", "pattern", "handshake", "traffic", "abp", "mixed"]:
        parent = root_family(family)
        left, right = split_with_hidden_gauge(parent, family)
        result = compose_and_minimize(left, right, set(parent.outputs))
        assert result.certificate.verified_homomorphism
        assert result.certificate.verified_minimal
        assert result.quotient_gain_bits >= 0.99
        assert machine_isomorphic(result.quotient, parent)


def test_morph_batch_equals_independent_monolithic_reference():
    for family in ["parity", "counter", "pattern", "handshake", "traffic", "abp"]:
        for depth in [1, 2, 3]:
            for seed in range(3):
                spec = hidden_morphology(root_family(family), depth, seed, decoy_degree=4)
                root, stats = MorphEngine(
                    spec,
                    max_candidate_states=200_000,
                    max_candidate_transition_evaluations=2_000_000,
                    morph_shortlist=8,
                    seed=seed,
                ).run("morph_batch")
                assert stats.success, stats.failure
                monolithic = monolithic_compose(spec, max_states=500_000)
                assert equivalent_machines(root.machine, monolithic)
                assert machine_isomorphic(root.machine, root_family(family))
                assert all(x["homomorphism_certificate"] for x in stats.merge_trace)
                assert all(x["minimality_certificate"] for x in stats.merge_trace)


def test_kiss2_real_benchmark_root_and_hidden_reification():
    from pathlib import Path
    from morph_exact.kiss2 import load_kiss2
    path = Path(__file__).parents[1] / "benchmarks" / "bbara.kiss2"
    root_model = load_kiss2(path, "bbara")
    assert root_model.n_states >= 5
    assert independent_is_minimal(root_model)
    spec = hidden_morphology(root_model, depth=2, seed=7, decoy_degree=4)
    recovered, stats = MorphEngine(spec, morph_shortlist=8, seed=7).run("morph_batch")
    assert stats.success
    assert machine_isomorphic(recovered.machine, root_model)
    assert stats.cluster_recall == 1.0


def test_natural_parity_tree_small_matches_monolithic():
    from morph_exact.generators import parity_tree_network
    for depth in (1, 2, 3):
        spec = parity_tree_network(depth, input_bits=2, seed=depth, decoy_degree=3)
        root, stats = MorphEngine(
            spec,
            max_candidate_states=200_000,
            max_candidate_transition_evaluations=4_000_000,
            morph_shortlist=12,
            seed=depth,
        ).run("morph_batch")
        assert stats.success, stats.failure
        mono = monolithic_compose(spec, max_states=500_000, max_transition_evaluations=20_000_000)
        assert equivalent_machines(root.machine, mono)
        assert all(x["homomorphism_certificate"] and x["minimality_certificate"] for x in stats.merge_trace)


def test_hyper_morph_on_natural_parity_tree():
    from morph_exact.generators import parity_tree_network
    from morph_exact.hyper import MorphHyperEngine
    for depth in (2, 3):
        spec = parity_tree_network(depth, input_bits=2, seed=11 + depth, decoy_degree=4)
        root, stats = MorphHyperEngine(
            spec,
            max_candidate_states=200_000,
            max_candidate_transition_evaluations=4_000_000,
            morph_shortlist=16,
            seed=depth,
        ).run()
        assert stats.success, stats.failure
        mono = monolithic_compose(spec, max_states=500_000, max_transition_evaluations=20_000_000)
        assert equivalent_machines(root.machine, mono)
        assert all(x["homomorphism_certificate"] and x["minimality_certificate"] for x in stats.merge_trace)


def test_natural_modular_sum_tree_small_matches_monolithic():
    from morph_exact.generators import modular_sum_tree_network
    from morph_exact.hyper import MorphHyperEngine
    spec = modular_sum_tree_network(depth=2, modulus=3, seed=5, decoy_degree=3)
    root, stats = MorphHyperEngine(
        spec,
        max_candidate_states=200_000,
        max_candidate_transition_evaluations=4_000_000,
        morph_shortlist=16,
        seed=5,
    ).run()
    assert stats.success, stats.failure
    mono = monolithic_compose(spec, max_states=500_000, max_transition_evaluations=20_000_000)
    assert equivalent_machines(root.machine, mono)
