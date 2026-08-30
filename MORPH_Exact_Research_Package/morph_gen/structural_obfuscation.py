from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

import z3

from .aig import AIG
from .spec import CircuitSystem


def entangle_dependencies(
    aig: AIG,
    state_variables: Sequence[int],
    next_functions: Sequence[int],
) -> tuple[int, ...]:
    """Add a semantics-neutral dependency cycle at circuit level."""
    width = len(state_variables)
    return tuple(
        aig.opaque_mux(state_variables[(index - 1) % width], function)
        for index, function in enumerate(next_functions)
    )


def dependency_edges(
    aig: AIG,
    state_variables: Sequence[int],
    next_functions: Sequence[int],
) -> frozenset[tuple[int, int]]:
    position = {aig.nodes[node].name: index for index, node in enumerate(state_variables)}
    edges = set()
    for target, function in enumerate(next_functions):
        for name in aig.support(function):
            source = position.get(name)
            if source is not None:
                edges.add((source, target))
    return frozenset(edges)


def is_strongly_connected(width: int, edges: Sequence[tuple[int, int]]) -> bool:
    graph = {index: set() for index in range(width)}
    reverse = {index: set() for index in range(width)}
    for source, target in edges:
        graph[source].add(target)
        reverse[target].add(source)

    def visit(adjacency) -> set[int]:
        seen = {0}
        stack = [0]
        while stack:
            node = stack.pop()
            for target in adjacency[node] - seen:
                seen.add(target)
                stack.append(target)
        return seen

    return len(visit(graph)) == width and len(visit(reverse)) == width


@dataclass
class ObfuscationCertificate:
    strongly_connected: bool
    decoder_min_support: int
    no_coordinate_equals_macro: bool
    minimum_coordinates_determining_macro: int
    requested_r: int
    small_subset_hidden: bool
    sat_checks: int
    verified: bool


def verify_obfuscation(
    system: CircuitSystem,
    macro_functions: Sequence[int],
    *,
    r: int,
    exhaustive_subset_limit: int = 20,
) -> ObfuscationCertificate:
    aig = system.aig
    state_names = system.state_names
    macro_supports = [aig.support(function) & set(state_names) for function in macro_functions]
    minimum_support = min(map(len, macro_supports), default=0)
    x1 = {name: z3.Bool(f"ob_x1_{index}") for index, name in enumerate(state_names)}
    x2 = {name: z3.Bool(f"ob_x2_{index}") for index, name in enumerate(state_names)}
    f1, constraints1 = aig.to_z3_tseitin(
        tuple(macro_functions) + (system.reachable_predicate,),
        x1,
        prefix="obfuscation_x1",
    )
    f2, constraints2 = aig.to_z3_tseitin(
        tuple(macro_functions) + (system.reachable_predicate,),
        x2,
        prefix="obfuscation_x2",
    )
    macro1, reachable1 = f1[:-1], f1[-1]
    macro2, reachable2 = f2[:-1], f2[-1]
    sat_checks = 0

    no_equal = True
    for coordinate, name in enumerate(state_names):
        for macro in range(len(macro_functions)):
            solver = z3.Solver()
            solver.add(*constraints1, reachable1, z3.Xor(x1[name], macro1[macro]))
            sat_checks += 1
            if solver.check() == z3.unsat:
                no_equal = False
                break
        if not no_equal:
            break

    # On a full Boolean reachable domain, the union of essential supports is
    # exactly the smallest physical coordinate set that determines F. For a
    # restricted domain, exhaustively verify subsets up to r when feasible.
    support_union = set().union(*macro_supports) if macro_supports else set()
    minimum_coordinates = len(support_union)
    hidden = minimum_coordinates > r
    if len(state_names) <= exhaustive_subset_limit:
        hidden = True
        for size in range(r + 1):
            for subset in combinations(state_names, size):
                solver = z3.Solver()
                solver.add(*constraints1, *constraints2, reachable1, reachable2)
                solver.add(*(x1[name] == x2[name] for name in subset))
                solver.add(z3.Or(*(left != right for left, right in zip(macro1, macro2))))
                sat_checks += 1
                if solver.check() == z3.unsat:
                    hidden = False
                    minimum_coordinates = min(minimum_coordinates, size)
                    break
            if not hidden:
                break

    strongly_connected = is_strongly_connected(
        system.micro_bits, system.syntactic_dependencies
    )
    verified = strongly_connected and minimum_support >= 2 and no_equal and hidden
    return ObfuscationCertificate(
        strongly_connected,
        minimum_support,
        no_equal,
        minimum_coordinates,
        r,
        hidden,
        sat_checks,
        verified,
    )
