from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Sequence

from morph_exact.core import NetworkSpec

from .certificates import CertificateReport, verify_certificate
from .predicate_closure import PredicateClosureResult, close_predicates
from .symbolic import SymbolicMachine


def executable_graph(spec: NetworkSpec) -> dict[int, set[int]]:
    graph = {lid: set() for lid in spec.leaf_machines}
    for signal, source in spec.producer.items():
        for target in spec.consumers.get(signal, ()):
            if source != target:
                graph[source].add(target)
    return graph


def dependency_sccs(spec: NetworkSpec) -> list[frozenset[int]]:
    graph = executable_graph(spec)
    visited: set[int] = set()
    finished: list[int] = []
    for root in sorted(graph):
        if root in visited:
            continue
        visited.add(root)
        stack = [(root, False)]
        while stack:
            vertex, exiting = stack.pop()
            if exiting:
                finished.append(vertex)
                continue
            stack.append((vertex, True))
            for target in reversed(sorted(graph[vertex])):
                if target not in visited:
                    visited.add(target)
                    stack.append((target, False))
    reverse = {x: set() for x in graph}
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    result: list[frozenset[int]] = []
    visited.clear()
    for root in reversed(finished):
        if root in visited:
            continue
        component: set[int] = set()
        stack = [root]
        visited.add(root)
        while stack:
            vertex = stack.pop()
            component.add(vertex)
            for target in reverse[vertex]:
                if target not in visited:
                    visited.add(target)
                    stack.append(target)
        result.append(frozenset(component))
    return sorted(result, key=lambda region: (len(region), tuple(sorted(region))))


def feedback_cycle_closures(spec: NetworkSpec) -> list[frozenset[int]]:
    """Find executable feedback cycles without inspecting transition semantics."""
    graph = executable_graph(spec)
    closures: set[frozenset[int]] = set()
    for source, targets in graph.items():
        for target in targets:
            queue = deque([(target, (target,))])
            visited = {target}
            while queue:
                vertex, path = queue.popleft()
                if vertex == source:
                    closures.add(frozenset(path))
                    break
                for successor in sorted(graph[vertex]):
                    if successor not in visited:
                        visited.add(successor)
                        queue.append((successor, path + (successor,)))
    return sorted(closures, key=lambda region: (len(region), tuple(sorted(region))))


def pair_candidates(spec: NetworkSpec) -> list[frozenset[int]]:
    return [frozenset(edge) for edge in sorted(spec.signal_edges)]


def triple_candidates(spec: NetworkSpec) -> list[frozenset[int]]:
    producers_by_target: dict[int, set[int]] = {
        lid: set() for lid in spec.leaf_machines
    }
    for signal, source in spec.producer.items():
        for target in spec.consumers.get(signal, ()):
            if source != target:
                producers_by_target[target].add(source)
    candidates = {
        frozenset((target, a, b))
        for target, producers in producers_by_target.items()
        for a, b in combinations(sorted(producers), 2)
    }
    return sorted(candidates, key=lambda region: tuple(sorted(region)))


def expand_failed_candidates(
    spec: NetworkSpec,
    failed: Iterable[Iterable[int]],
) -> list[frozenset[int]]:
    """Grow failed pair/triple regions by one executable frontier at a time."""
    graph = executable_graph(spec)
    undirected = {vertex: set(targets) for vertex, targets in graph.items()}
    for source, targets in graph.items():
        for target in targets:
            undirected[target].add(source)
    all_leaves = frozenset(graph)
    queue = deque(frozenset(region) for region in failed)
    seen = set(queue)
    expanded: list[frozenset[int]] = []
    while queue:
        region = queue.popleft()
        frontier = set().union(*(undirected[x] for x in region)) - set(region)
        if not frontier:
            continue
        grown = region | frozenset(frontier)
        if grown not in seen:
            seen.add(grown)
            expanded.append(grown)
            if grown != all_leaves:
                queue.append(grown)
    return expanded


def discover_candidate_regions(
    spec: NetworkSpec,
    failed: Iterable[Iterable[int]] = (),
) -> list[frozenset[int]]:
    candidates = {
        *pair_candidates(spec),
        *triple_candidates(spec),
        *(region for region in dependency_sccs(spec) if len(region) > 1),
        *feedback_cycle_closures(spec),
        *expand_failed_candidates(spec, failed),
    }
    return sorted(candidates, key=lambda region: (-len(region), tuple(sorted(region))))


@dataclass
class CertifiedRegion:
    leaves: frozenset[int]
    closure: PredicateClosureResult
    certificate: CertificateReport

    @property
    def atom(self) -> SymbolicMachine:
        return self.closure.macro_machine


def certify_region(
    spec: NetworkSpec,
    leaves: Iterable[int],
    *,
    variable_order: str = "dependency",
) -> CertifiedRegion | None:
    region = frozenset(leaves)
    machine = SymbolicMachine.from_network(
        spec,
        leaves=region,
        keep_outputs=spec.keep_outputs(region),
        variable_order=variable_order,
        name=f"candidate-{len(region)}",
    )
    closure = close_predicates(machine)
    certificate = verify_certificate(closure)
    if not certificate.verified:
        return None
    return CertifiedRegion(region, closure, certificate)


def discover_certified_regions(
    spec: NetworkSpec,
    failed: Iterable[Iterable[int]] = (),
    *,
    variable_order: str = "dependency",
) -> list[CertifiedRegion]:
    """Installable output: every returned candidate has a complete exact proof."""
    installed: list[CertifiedRegion] = []
    used: set[int] = set()
    for region in discover_candidate_regions(spec, failed):
        if used & set(region):
            continue
        certified = certify_region(spec, region, variable_order=variable_order)
        if certified is not None:
            installed.append(certified)
            used.update(region)
    return installed
