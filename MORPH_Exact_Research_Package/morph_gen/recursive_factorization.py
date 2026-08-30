from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .generator_basis import GeneratorBasis


@dataclass(frozen=True)
class MacroBlock:
    bits: tuple[int, ...]
    dependencies: tuple[int, ...]
    independent: bool


@dataclass
class RecursiveFactorization:
    blocks: tuple[MacroBlock, ...]
    dependency_edges: frozenset[tuple[int, int]]
    recursion_depth: int
    recovered_organ_count: int
    proof: dict[str, object]


def _sccs(width: int, edges: Sequence[tuple[int, int]]) -> list[tuple[int, ...]]:
    graph = {index: set() for index in range(width)}
    reverse = {index: set() for index in range(width)}
    for source, target in edges:
        graph[source].add(target)
        reverse[target].add(source)
    visited: set[int] = set()
    finished: list[int] = []
    for root in range(width):
        if root in visited:
            continue
        stack = [(root, False)]
        visited.add(root)
        while stack:
            node, exiting = stack.pop()
            if exiting:
                finished.append(node)
            else:
                stack.append((node, True))
                for target in graph[node] - visited:
                    visited.add(target)
                    stack.append((target, False))
    visited.clear()
    components = []
    for root in reversed(finished):
        if root in visited:
            continue
        component = []
        stack = [root]
        visited.add(root)
        while stack:
            node = stack.pop()
            component.append(node)
            for target in reverse[node] - visited:
                visited.add(target)
                stack.append(target)
        components.append(tuple(sorted(component)))
    return components


def factor_macro_dynamics(basis: GeneratorBasis) -> RecursiveFactorization:
    """Discover macro organs solely from G's semantic state-variable supports."""
    state_names = {
        basis.macro_aig.nodes[node].name: index
        for index, node in enumerate(basis.macro_state_variables)
    }
    edges: set[tuple[int, int]] = set()
    for target, function in enumerate(basis.g_functions):
        for name in basis.macro_aig.support(function):
            source = state_names.get(name)
            if source is not None:
                edges.add((source, target))
    components = _sccs(basis.macro_bits, edges)
    blocks = []
    for component in components:
        component_set = set(component)
        incoming = sorted({
            source for source, target in edges
            if target in component_set and source not in component_set
        })
        blocks.append(MacroBlock(component, tuple(incoming), not incoming))
    organ_count = len(blocks)
    return RecursiveFactorization(
        tuple(blocks),
        frozenset(edges),
        2 if organ_count > 1 else 1,
        organ_count,
        {
            "method": "semantic support SCCs of synthesized G",
            "metadata_used": False,
            "all_bits_covered": sorted(bit for block in blocks for bit in block.bits)
            == list(range(basis.macro_bits)),
        },
    )
