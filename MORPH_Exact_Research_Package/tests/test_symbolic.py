import numpy as np

from morph_exact.core import Machine, compose_and_minimize, machine_isomorphic
from morph_lift.candidates import (
    certify_region,
    dependency_sccs,
    discover_candidate_regions,
    expand_failed_candidates,
    feedback_cycle_closures,
)
from morph_lift.certificates import verify_certificate
from morph_lift.gauge_cycle import gauge_cycle_network, parity_accumulator_reference
from morph_lift.predicate_closure import close_predicates
from morph_lift.symbolic import SymbolicMachine, variable_order_metrics


def test_explicit_symbolic_bidirectional_and_orders():
    reference = parity_accumulator_reference()
    for order in ("grouped", "interleaved", "dependency"):
        symbolic = SymbolicMachine.from_explicit(reference, variable_order=order)
        assert machine_isomorphic(symbolic.to_explicit(), reference)
    metrics = variable_order_metrics(gauge_cycle_network(8))
    assert set(metrics) == {"grouped", "interleaved", "dependency"}
    assert all(value["bdd_nodes"] > 0 for value in metrics.values())


def test_symbolic_composition_hiding_rename_and_exists():
    spec = gauge_cycle_network(4)
    atoms = [
        SymbolicMachine.from_explicit(machine, prefix=f"atom{lid}")
        for lid, machine in spec.leaf_machines.items()
    ]
    product = SymbolicMachine.compose(atoms, spec.global_outputs)
    direct = SymbolicMachine.from_network(spec)
    assert machine_isomorphic(product.to_explicit(), direct.to_explicit())
    renamed = product.rename({product.state_variables[0]: "renamed_state"})
    assert machine_isomorphic(renamed.to_explicit(), product.to_explicit())
    assert product.exists(product.state_variables, product.initial_predicate) == product.bdd.true


def test_predicate_closure_certificate_and_recursive_macro_composition():
    spec = gauge_cycle_network(8)
    closure = close_predicates(SymbolicMachine.from_network(spec))
    assert closure.predicate_count == 1
    assert closure.closure_error == closure.source.bdd.false
    certificate = verify_certificate(closure)
    assert certificate.verified
    assert all(certificate.bdd_conditions.values())
    assert set(certificate.smt_conditions.values()) == {"UNSAT"}
    macro = closure.macro_machine
    assert machine_isomorphic(macro.to_explicit(), parity_accumulator_reference())

    consumer = Machine(
        "consumer",
        ("y0",),
        ("q",),
        0,
        np.asarray([[0, 1], [1, 0]], dtype=np.int32),
        np.asarray([[0], [1]], dtype=np.uint8),
    )
    symbolic_consumer = SymbolicMachine.from_explicit(consumer, prefix="consumer")
    recursive = SymbolicMachine.compose([macro, symbolic_consumer], {"q"})
    explicit = compose_and_minimize(
        parity_accumulator_reference(), consumer, {"q"}
    ).quotient
    assert machine_isomorphic(recursive.to_explicit(), explicit)


def test_generic_candidate_discovery_finds_feedback_scc():
    spec = gauge_cycle_network(16)
    assert dependency_sccs(spec) == [frozenset(range(16))]
    assert frozenset(range(16)) in discover_candidate_regions(spec)
    assert frozenset(range(16)) in feedback_cycle_closures(spec)
    assert frozenset(range(16)) in expand_failed_candidates(spec, [{0, 1}])
    certified = certify_region(spec, range(16))
    assert certified is not None and certified.certificate.verified
