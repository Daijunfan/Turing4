import json
from pathlib import Path

from morph_exact.engine import MorphEngine
from morph_lift.gauge_cycle import gauge_cycle_network
from morph_lift.oracle import (
    network_from_dict,
    reatomization_peak_cost,
    subset_oracle,
)


def test_subset_oracle_exhaustive_open_quotient_law():
    n = 8
    oracle = subset_oracle(gauge_cycle_network(n))
    full = (1 << n) - 1
    assert oracle.quotients[full].quotient.n_states == 2
    assert oracle.peak_cost == 6.0
    for mask, quotient in oracle.quotients.items():
        assert quotient.proof.homomorphism and quotient.proof.minimal
        if mask != full:
            assert quotient.quotient.n_states == 1 << mask.bit_count()


def test_saved_minimal_epg_counterexample_is_reproducible():
    path = Path(__file__).parents[1] / "results_lift" / "counterexamples" / "minimal_epg_vs_opt.json"
    data = json.loads(path.read_text())
    spec = network_from_dict(data["network"])
    oracle = subset_oracle(spec, max_components=10)
    root, stats = MorphEngine(spec, seed=data["seed"]).run("morph_batch")
    assert stats.success
    morph_cost = reatomization_peak_cost(root)
    assert morph_cost == data["morph_cost"]
    assert oracle.peak_cost == data["opt_cost"]
    assert morph_cost / oracle.peak_cost == data["ratio"] > 1
