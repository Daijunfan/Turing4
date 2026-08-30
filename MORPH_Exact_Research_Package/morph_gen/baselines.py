from __future__ import annotations

from random import Random
from time import perf_counter

from morph_lift.predicate_closure import close_predicates
from morph_lift.symbolic import _new_bdd, unique_node_count

from .generator_basis import GeneratorBasis
from .spec import CircuitSystem


def _ordered_bdd_nodes(system: CircuitSystem, order: tuple[str, ...], dynamic: bool = False) -> int:
    roots = (
        *system.next_functions,
        *system.output_functions,
        system.initial_predicate,
        system.valid_predicate,
        system.reachable_predicate,
    )
    bdd = _new_bdd()
    bdd.declare(*order)
    values = {0: bdd.false, 1: bdd.true}
    for node in sorted(system.aig.reachable_nodes(roots)):
        if node < 2:
            continue
        gate = system.aig.nodes[node]
        if gate.op == "INPUT":
            values[node] = bdd.var(gate.name)
        elif gate.op == "AND":
            values[node] = values[gate.args[0]] & values[gate.args[1]]
        elif gate.op == "XOR":
            left, right = values[gate.args[0]], values[gate.args[1]]
            values[node] = (left & ~right) | (~left & right)
        elif gate.op == "NOT":
            values[node] = ~values[gate.args[0]]
        else:
            values[node] = bdd.ite(
                values[gate.args[0]], values[gate.args[1]], values[gate.args[2]]
            )
    functions = tuple(values[root] for root in roots)
    if dynamic:
        bdd.configure(reordering=True)
        bdd.reorder()
    return unique_node_count(bdd, functions)


def bdd_order_baselines(system: CircuitSystem, seed: int = 0, orders: int = 4) -> dict:
    variables = (*system.state_names, *system.input_names)
    fixed = _ordered_bdd_nodes(system, variables)
    reverse = _ordered_bdd_nodes(system, tuple(reversed(variables)))
    dynamic = _ordered_bdd_nodes(system, variables, dynamic=True)
    rng = Random(seed)
    candidates = [fixed, reverse]
    for _ in range(orders):
        order = list(variables)
        rng.shuffle(order)
        candidates.append(_ordered_bdd_nodes(system, tuple(order)))
    return {
        "fixed_bdd_nodes": fixed,
        "reverse_bdd_nodes": reverse,
        "dynamic_bdd_nodes": dynamic,
        "best_of_n_bdd_nodes": min(candidates),
        "best_of_n_orders": len(candidates),
    }


def run_baselines(
    system: CircuitSystem,
    generated: GeneratorBasis,
    *,
    explicit_limit: int = 20,
    seed: int = 0,
) -> dict:
    results: dict[str, object] = {}
    start = perf_counter()
    lift = close_predicates(system.to_symbolic())
    results["morph_lift"] = {
        "predicate_count": lift.predicate_count,
        "macro_bits": len(lift.macro_machine.state_variables),
        "seconds": perf_counter() - start,
    }
    start = perf_counter()
    results["bdd_orders"] = {
        **bdd_order_baselines(system, seed=seed),
        "seconds": perf_counter() - start,
    }
    if system.micro_bits <= explicit_limit:
        start = perf_counter()
        explicit = system.to_explicit(explicit_limit)
        explicit_record = {
            "success": True,
            "quotient_states": explicit.n_states,
            "seconds": perf_counter() - start,
        }
        results["explicit_canonical"] = explicit_record
        results["m_invariant_stp_explicit"] = dict(explicit_record)
    else:
        results["explicit_canonical"] = {
            "success": False,
            "reason": "micro-state enumeration limit",
        }
        results["m_invariant_stp_explicit"] = {
            "success": False,
            "reason": "explicit STP matrix limit",
        }
    results["scc_whole_region"] = {
        "candidate_bits": system.micro_bits,
        "certified_macro": False,
    }
    results["static_graph_partition"] = {
        "parts": 2,
        "crosses_scc": True,
        "certified_macro": False,
    }
    state_names = set(system.state_names)
    direct = any(
        system.aig.nodes[function].op == "INPUT"
        and system.aig.nodes[function].name in state_names
        for function in generated.f_functions
    )
    results["physical_feature_selection"] = {
        "success": direct,
        "selected_bits": generated.macro_bits if direct else None,
    }
    results["oracle_latent_decoder"] = {
        "evaluation_only": True,
        "excluded_from_baseline_ranking": True,
    }
    results["morph_gen"] = generated.metrics()
    return results
