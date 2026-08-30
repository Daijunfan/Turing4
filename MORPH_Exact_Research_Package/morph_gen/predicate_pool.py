from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import ceil, log2
from typing import Sequence

import z3

from .aig import AIG, ANF
from .generator_basis import GeneratorBasis
from .spec import CircuitSystem


@dataclass
class PredicatePool:
    nodes: tuple[int, ...]
    anfs: tuple[ANF | None, ...]
    successors: dict[tuple[int, int], int]
    output_indices: tuple[int, ...]
    closure_rounds: int
    counterexample_count: int


def future_predicate_pool(
    system: CircuitSystem,
    *,
    max_predicates: int = 4096,
    max_terms: int = 100_000,
    canonical: str = "anf",
) -> PredicatePool:
    """Exact closure of output predicates under every one-step preimage."""
    aig = system.aig
    state_names = system.state_names
    all_names = (*state_names, *system.input_names)
    nodes: list[int] = []
    anfs: list[ANF | None] = []
    semantic_index: dict[object, int] = {}
    bdd = None
    bdd_values = None
    reachable_bdd = None
    if canonical == "bdd":
        from morph_lift.symbolic import _new_bdd

        bdd = _new_bdd()
        bdd.declare(*all_names)
        bdd_values = [bdd.false, bdd.true]

        def sync_bdd() -> None:
            assert bdd is not None and bdd_values is not None
            while len(bdd_values) < len(aig.nodes):
                gate = aig.nodes[len(bdd_values)]
                if gate.op == "INPUT":
                    bdd_values.append(bdd.var(gate.name))
                elif gate.op == "AND":
                    bdd_values.append(bdd_values[gate.args[0]] & bdd_values[gate.args[1]])
                elif gate.op == "XOR":
                    left, right = bdd_values[gate.args[0]], bdd_values[gate.args[1]]
                    bdd_values.append((left & ~right) | (~left & right))
                elif gate.op == "NOT":
                    bdd_values.append(~bdd_values[gate.args[0]])
                else:
                    bdd_values.append(bdd.ite(
                        bdd_values[gate.args[0]], bdd_values[gate.args[1]], bdd_values[gate.args[2]]
                    ))

        sync_bdd()
        reachable_bdd = bdd_values[system.reachable_predicate]
    elif canonical != "anf":
        raise ValueError(canonical)

    def add(node: int) -> tuple[int, bool]:
        if canonical == "anf":
            anf = aig.to_anf((node,), all_names, max_terms=max_terms)[0]
            key: object = anf.monomials
        else:
            sync_bdd()
            assert bdd_values is not None and reachable_bdd is not None
            anf = None
            key = int(bdd_values[node] & reachable_bdd)
        existing = semantic_index.get(key)
        if existing is not None:
            return existing, False
        index = len(nodes)
        if index >= max_predicates:
            raise RuntimeError(f"predicate pool exceeded {max_predicates}")
        nodes.append(node)
        anfs.append(anf)
        semantic_index[key] = index
        return index, True

    output_indices = tuple(add(node)[0] for node in system.output_functions)
    successors: dict[tuple[int, int], int] = {}
    fixed_next: dict[int, tuple[int, ...]] = {}
    for input_value in range(1 << len(system.input_variables)):
        input_replacements = {
            name: aig.true if (input_value >> bit) & 1 else aig.false
            for bit, name in enumerate(system.input_names)
        }
        fixed_next[input_value] = tuple(
            aig.substitute(function, input_replacements)
            for function in system.next_functions
        )
    cursor = 0
    rounds = 0
    counterexamples = 0
    while cursor < len(nodes):
        round_end = len(nodes)
        rounds += 1
        while cursor < round_end:
            predicate = nodes[cursor]
            for input_value in range(1 << len(system.input_variables)):
                replacements = {
                    name: function
                    for name, function in zip(state_names, fixed_next[input_value])
                }
                replacements.update({
                    name: aig.true if (input_value >> bit) & 1 else aig.false
                    for bit, name in enumerate(system.input_names)
                })
                preimage = aig.substitute(predicate, replacements)
                target, created = add(preimage)
                successors[(cursor, input_value)] = target
                counterexamples += int(created)
            cursor += 1
    return PredicatePool(
        tuple(nodes), tuple(anfs), successors, output_indices, rounds, counterexamples
    )


def enumerate_signatures(system: CircuitSystem, pool: PredicatePool) -> tuple[tuple[int, ...], ...]:
    bdd, expressions = _bdd_roots(
        system, (*pool.nodes, system.reachable_predicate)
    )
    predicates, reachable = expressions[:-1], expressions[-1]
    names = tuple(f"pool_signature_{index}" for index in range(len(predicates)))
    bdd.declare(*names)
    relation = reachable
    for name, predicate in zip(names, predicates):
        variable = bdd.var(name)
        relation &= (variable & predicate) | (~variable & ~predicate)
    projected = bdd.exist(set(system.state_names) | set(system.input_names), relation)
    signatures = [
        tuple(int(assignment[name]) for name in names)
        for assignment in bdd.pick_iter(projected, care_vars=set(names))
    ]
    return tuple(sorted(set(signatures)))


def initial_signature(system: CircuitSystem, pool: PredicatePool) -> tuple[int, ...]:
    zero = {
        **{name: False for name in system.state_names},
        **{name: False for name in system.input_names},
    }
    if system.aig.evaluate(system.initial_predicate, zero):
        return tuple(
            int(system.aig.evaluate(node, zero)) for node in pool.nodes
        )
    bdd, expressions = _bdd_roots(system, (*pool.nodes, system.initial_predicate))
    predicates, initial = expressions[:-1], expressions[-1]
    if initial == bdd.false:
        raise ValueError("initial predicate is unsatisfiable")
    signature = []
    for predicate in predicates:
        can_be_zero = initial & ~predicate != bdd.false
        can_be_one = initial & predicate != bdd.false
        if can_be_zero and can_be_one:
            raise ValueError("initial predicate maps to multiple macro states")
        signature.append(int(can_be_one))
    return tuple(signature)


def _bdd_roots(system: CircuitSystem, roots: Sequence[int]):
    from morph_lift.symbolic import _new_bdd

    bdd = _new_bdd()
    names = (*system.state_names, *system.input_names)
    bdd.declare(*names)
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
    return bdd, tuple(values[root] for root in roots)


def functionally_dependent(
    system: CircuitSystem,
    predicate: int,
    generators: Sequence[int],
) -> bool:
    """Exact check that p is a function of Q on the reachable domain."""
    bdd, roots = _bdd_roots(
        system, (*generators, predicate, system.reachable_predicate)
    )
    q, p, reachable = roots[:-2], roots[-2], roots[-1]
    names = tuple(f"fd_q{index}" for index in range(len(q)))
    bdd.declare(*names)
    relation = reachable
    for name, function in zip(names, q):
        variable = bdd.var(name)
        relation &= (variable & function) | (~variable & ~function)
    state = set(system.state_names) | set(system.input_names)
    can_be_one = bdd.exist(state, relation & p)
    can_be_zero = bdd.exist(state, relation & ~p)
    return can_be_one & can_be_zero == bdd.false


def minimum_separating_subset(
    signatures: Sequence[Sequence[int]],
    candidate_indices: Sequence[int],
    *,
    maximum_combinations: int = 500_000,
) -> tuple[int, ...] | None:
    class_count = len(signatures)
    lower = max(0, ceil(log2(max(1, class_count))))
    tested = 0
    for width in range(lower, len(candidate_indices) + 1):
        for subset in combinations(candidate_indices, width):
            tested += 1
            if tested > maximum_combinations:
                return None
            codes = {
                tuple(signature[index] for index in subset)
                for signature in signatures
            }
            if len(codes) == class_count:
                return tuple(subset)
    return None


def _class_transition(
    pool: PredicatePool,
    signature: Sequence[int],
    input_value: int,
) -> tuple[int, ...]:
    return tuple(
        signature[pool.successors[(index, input_value)]]
        for index in range(len(pool.nodes))
    )


def basis_from_predicates(
    system: CircuitSystem,
    pool: PredicatePool,
    signatures: Sequence[Sequence[int]],
    selected: Sequence[int],
    *,
    backend: str,
    synthesis_stats: dict[str, object] | None = None,
) -> GeneratorBasis:
    selected = tuple(selected)
    signature_index = {tuple(signature): index for index, signature in enumerate(signatures)}
    codes = [
        sum(signature[index] << bit for bit, index in enumerate(selected))
        for signature in signatures
    ]
    if len(set(codes)) != len(signatures):
        raise ValueError("selected predicates do not separate behavioral classes")
    code_by_signature = {
        tuple(signature): code for signature, code in zip(signatures, codes)
    }
    macro = AIG()
    zvars = tuple(macro.input(f"z{i}") for i in range(len(selected)))
    uvars = tuple(macro.input(f"u{i}") for i in range(len(system.input_variables)))
    g_tables = [[0] * (1 << (len(selected) + len(uvars))) for _ in selected]
    h_tables = [[0] * (1 << len(selected)) for _ in system.output_functions]
    for signature, code in zip(signatures, codes):
        for output_bit, pool_index in enumerate(pool.output_indices):
            h_tables[output_bit][code] = signature[pool_index]
        for input_value in range(1 << len(uvars)):
            target_signature = _class_transition(pool, signature, input_value)
            if target_signature not in signature_index:
                raise AssertionError("closed predicate vector left reachable signatures")
            target_code = code_by_signature[target_signature]
            table_index = code | (input_value << len(selected))
            for bit in range(len(selected)):
                g_tables[bit][table_index] = (target_code >> bit) & 1
    g = tuple(macro.truth_table((*zvars, *uvars), table) for table in g_tables)
    h = tuple(macro.truth_table(zvars, table) for table in h_tables)
    initial = initial_signature(system, pool)
    initial_code = code_by_signature[initial]
    stats = {
        "predicate_pool_size": len(pool.nodes),
        "closure_rounds": pool.closure_rounds,
        "counterexample_count": pool.counterexample_count,
        "sat_calls": 2,
        "cegis_iterations": pool.closure_rounds,
        **(synthesis_stats or {}),
    }
    return GeneratorBasis(
        system,
        tuple(pool.nodes[index] for index in selected),
        macro,
        zvars,
        uvars,
        g,
        h,
        initial_code,
        tuple(sorted(codes)),
        backend,
        stats,
        minimality_status="bit-count lower bound and exhaustive class separation",
    )


def universal_code_functions(
    system: CircuitSystem,
    pool: PredicatePool,
    signatures: Sequence[Sequence[int]],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Universal shared-DAG code of every feasible predicate signature."""
    width = max(0, ceil(log2(max(1, len(signatures)))))
    cubes = []
    for signature in signatures:
        cubes.append(system.aig.and_many(
            node if value else system.aig.not_(node)
            for node, value in zip(pool.nodes, signature)
        ))
    functions = []
    for bit in range(width):
        functions.append(system.aig.xor_many(
            cube for index, cube in enumerate(cubes) if (index >> bit) & 1
        ))
    return tuple(functions), tuple(range(len(signatures)))


def basis_from_class_encoding(
    system: CircuitSystem,
    pool: PredicatePool,
    signatures: Sequence[Sequence[int]],
    functions: Sequence[int],
    codes: Sequence[int],
    *,
    backend: str,
    synthesis_stats: dict[str, object] | None = None,
) -> GeneratorBasis:
    """Build G/H for an arbitrary shared-AIG encoding of behavior classes."""
    width = len(functions)
    code_by_signature = {
        tuple(signature): int(code)
        for signature, code in zip(signatures, codes)
    }
    if len(set(codes)) != len(signatures):
        raise ValueError("class encoding is not injective")
    macro = AIG()
    zvars = tuple(macro.input(f"z{i}") for i in range(width))
    uvars = tuple(macro.input(f"u{i}") for i in range(len(system.input_variables)))
    g_tables = [[0] * (1 << (width + len(uvars))) for _ in range(width)]
    h_tables = [[0] * (1 << width) for _ in system.output_functions]
    for signature, code in zip(signatures, codes):
        for output_bit, pool_index in enumerate(pool.output_indices):
            h_tables[output_bit][code] = signature[pool_index]
        for input_value in range(1 << len(uvars)):
            target_signature = _class_transition(pool, signature, input_value)
            target_code = code_by_signature[target_signature]
            table_index = code | (input_value << width)
            for bit in range(width):
                g_tables[bit][table_index] = (target_code >> bit) & 1
    g = tuple(macro.truth_table((*zvars, *uvars), table) for table in g_tables)
    h = tuple(macro.truth_table(zvars, table) for table in h_tables)
    initial = initial_signature(system, pool)
    return GeneratorBasis(
        system,
        tuple(functions),
        macro,
        zvars,
        uvars,
        g,
        h,
        code_by_signature[initial],
        tuple(sorted(map(int, codes))),
        backend,
        {
            "predicate_pool_size": len(pool.nodes),
            "closure_rounds": pool.closure_rounds,
            "counterexample_count": pool.counterexample_count,
            "sat_calls": 0,
            "cegis_iterations": pool.closure_rounds,
            **(synthesis_stats or {}),
        },
        minimality_status="information-theoretic bit bound with exhaustive class injection",
    )
