from morph_exact.core import machine_isomorphic
from morph_exact.engine import MorphEngine
from morph_exact.hyper import MorphHyperEngine
from morph_exact.reference import monolithic_compose
from morph_lift.gauge_cycle import gauge_cycle_network, parity_accumulator_reference


def test_gauge_cycle_has_only_real_executable_ring_contacts():
    spec = gauge_cycle_network(8, seed=3)
    assert len(spec.signal_edges) == 8
    assert all(
        machine.inputs == ("u", f"y{(lid - 1) % 8}")
        for lid, machine in spec.leaf_machines.items()
    )
    assert "target_macro" not in spec.metadata
    assert not spec.oracle_clusters


def test_gauge_cycle_full_reference_and_explicit_engines():
    reference = parity_accumulator_reference()
    for n in (4, 6, 8, 10, 12):
        spec = gauge_cycle_network(n)
        assert machine_isomorphic(monolithic_compose(spec), reference)
    spec = gauge_cycle_network(8)
    root, stats = MorphEngine(spec).run("morph_batch")
    assert stats.success and machine_isomorphic(root.machine, reference)
    root, stats = MorphHyperEngine(spec).run()
    assert stats.success and machine_isomorphic(root.machine, reference)
