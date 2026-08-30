from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
from math import ceil, log2
import re
from typing import Dict, Iterable, Mapping, Sequence

import numpy as np

try:  # Prefer the native backend when the installed dd build provides it.
    from dd import cudd as _bdd_module

    BDD_BACKEND = "dd.cudd"
except ImportError:  # Python versions without a CUDD wheel use the exact fallback.
    from dd import autoref as _bdd_module

    BDD_BACKEND = "dd.autoref"

from morph_exact.core import Machine, NetworkSpec


_IDS = count()


def _new_bdd():
    bdd = _bdd_module.BDD()
    # Required order experiments must not be silently rewritten by CUDD's
    # automatic sifting (which otherwise starts at its default 1000-var gate).
    bdd.configure(reordering=False)
    return bdd


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def _equiv(a, b):
    return (a & b) | (~a & ~b)


def bdd_xor(a, b):
    return (a & ~b) | (~a & b)


def _cube(bdd, variables: Sequence[str], value: int):
    result = bdd.true
    for bit, name in enumerate(variables):
        var = bdd.var(name)
        result &= var if (value >> bit) & 1 else ~var
    return result


def _table_function(bdd, variables: Sequence[str], values: np.ndarray):
    result = bdd.false
    for value, bit in enumerate(np.asarray(values).reshape(-1)):
        if int(bit):
            result |= _cube(bdd, variables, value)
    return result


def _evaluate(bdd, function, assignment: Mapping[str, bool]) -> bool:
    definitions = {
        name: value for name, value in assignment.items()
        if name in function.support
    }
    value = bdd.let(definitions, function) if definitions else function
    if value == bdd.true:
        return True
    if value == bdd.false:
        return False
    raise ValueError("assignment does not cover the function support")


def unique_node_count(bdd, roots: Iterable[object]) -> int:
    """Count distinct decision nodes reachable from roots (terminals included)."""
    seen: set[int] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        key = int(node)
        if key in seen:
            continue
        seen.add(key)
        if node == bdd.true or node == bdd.false:
            continue
        _, low, high = bdd.succ(node)
        stack.extend((low, high))
    return len(seen)


def _dependency_order(spec: NetworkSpec, lids: Sequence[int]) -> list[int]:
    """Generic SCC/topological dependency order derived only from signal edges."""
    allowed = set(lids)
    graph = {x: [] for x in lids}
    for signal, src in spec.producer.items():
        if src not in allowed:
            continue
        for dst in spec.consumers.get(signal, ()):
            if dst in allowed and dst != src:
                graph[src].append(dst)

    # Iterative Kosaraju avoids tying supported network size to Python's call
    # stack while using only the executable dependency graph.
    visited: set[int] = set()
    finished: list[int] = []
    for root in lids:
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
    reverse = {x: [] for x in lids}
    for source, targets in graph.items():
        for target in targets:
            reverse[target].append(source)
    components: list[list[int]] = []
    visited.clear()
    for root in reversed(finished):
        if root in visited:
            continue
        component: list[int] = []
        stack = [root]
        visited.add(root)
        while stack:
            vertex = stack.pop()
            component.append(vertex)
            for target in reverse[vertex]:
                if target not in visited:
                    visited.add(target)
                    stack.append(target)
        components.append(sorted(component))

    owner = {lid: i for i, comp in enumerate(components) for lid in comp}
    dag = {i: set() for i in range(len(components))}
    indegree = {i: 0 for i in dag}
    for src, targets in graph.items():
        for dst in targets:
            a, b = owner[src], owner[dst]
            if a != b and b not in dag[a]:
                dag[a].add(b)
                indegree[b] += 1
    ready = sorted(i for i, degree in indegree.items() if degree == 0)
    ordered: list[int] = []
    while ready:
        component = ready.pop(0)
        ordered.extend(components[component])
        for target in sorted(dag[component]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    return ordered


@dataclass
class SymbolicMachine:
    """Exact Boolean symbolic Moore machine.

    State/output/transition functions are BDDs.  The class deliberately exposes
    the predicates named in the research objective and keeps explicit port names
    separate from internal BDD variable names, so a certified macro is directly
    composable again.
    """

    name: str
    bdd: object
    state_variables: tuple[str, ...]
    next_state_variables: tuple[str, ...]
    input_variables: tuple[str, ...]
    output_functions: Dict[str, object]
    initial_predicate: object
    valid_state_predicate: object
    transition_relation: object | None
    next_state_functions: tuple[object, ...]
    reachable_predicate: object | None = None
    certificate_metadata: Dict[str, object] = field(default_factory=dict)
    variable_order: str = "dependency"
    transition_partitions: tuple[object, ...] = ()

    @property
    def outputs(self) -> tuple[str, ...]:
        return tuple(self.output_functions)

    @property
    def inputs(self) -> tuple[str, ...]:
        return self.input_variables

    @property
    def roots(self) -> tuple[object, ...]:
        roots: tuple[object, ...] = (
            self.initial_predicate,
            self.valid_state_predicate,
            *self.next_state_functions,
            *self.output_functions.values(),
            *self.transition_partitions,
        )
        if self.transition_relation is not None:
            roots += (self.transition_relation,)
        if self.reachable_predicate is not None:
            roots += (self.reachable_predicate,)
        return roots

    @property
    def bdd_node_count(self) -> int:
        return unique_node_count(self.bdd, self.roots)

    @classmethod
    def from_explicit(
        cls,
        machine: Machine,
        *,
        variable_order: str = "interleaved",
        prefix: str | None = None,
    ) -> "SymbolicMachine":
        if variable_order not in {"grouped", "interleaved", "dependency"}:
            raise ValueError(variable_order)
        width = max(1, ceil(log2(max(2, machine.n_states))))
        uid = next(_IDS)
        prefix = _safe(prefix or machine.name) + f"_{uid}"
        current = tuple(f"{prefix}_s{i}" for i in range(width))
        nxt = tuple(f"{prefix}_n{i}" for i in range(width))
        inputs = tuple(machine.inputs)
        if variable_order == "grouped":
            order = [*current, *inputs, *nxt]
        else:
            pairs = [x for pair in zip(current, nxt) for x in pair]
            order = pairs + list(inputs)
            if variable_order == "dependency":
                order = [*inputs, *pairs]
        bdd = _new_bdd()
        bdd.declare(*dict.fromkeys(order))

        valid = bdd.false
        for state in range(machine.n_states):
            valid |= _cube(bdd, current, state)
        initial = _cube(bdd, current, machine.initial)
        outputs = {
            port: _table_function(bdd, current, machine.output_bits[:, bit])
            for bit, port in enumerate(machine.outputs)
        }
        next_functions = []
        for bit in range(width):
            function = bdd.false
            for state in range(machine.n_states):
                state_guard = _cube(bdd, current, state)
                for symbol in range(machine.alphabet_size):
                    if (int(machine.next_state[state, symbol]) >> bit) & 1:
                        function |= state_guard & _cube(bdd, inputs, symbol)
            next_functions.append(function)
        partitions = []
        for name, function in zip(nxt, next_functions):
            partitions.append(_equiv(bdd.var(name), function))
        relation = valid
        for partition in partitions:
            relation &= partition
        result = cls(
            machine.name,
            bdd,
            current,
            nxt,
            inputs,
            outputs,
            initial,
            valid,
            relation,
            tuple(next_functions),
            certificate_metadata={
                "backend": BDD_BACKEND,
                "source": "explicit Machine",
                "source_digest": machine.digest(),
            },
            variable_order=variable_order,
            transition_partitions=tuple(partitions),
        )
        result.compute_reachable()
        return result

    @classmethod
    def from_network(
        cls,
        spec: NetworkSpec,
        *,
        leaves: Iterable[int] | None = None,
        keep_outputs: Iterable[str] | None = None,
        variable_order: str = "dependency",
        name: str = "symbolic-network",
    ) -> "SymbolicMachine":
        """Compile primitives directly, without constructing their product states."""
        if variable_order not in {"grouped", "interleaved", "dependency"}:
            raise ValueError(variable_order)
        lids = sorted(spec.leaf_machines if leaves is None else set(leaves))
        keep = set(spec.global_outputs if keep_outputs is None else keep_outputs)
        machines = {lid: spec.leaf_machines[lid] for lid in lids}
        produced = {port for machine in machines.values() for port in machine.outputs}
        external_inputs = tuple(sorted({
            port
            for machine in machines.values()
            for port in machine.inputs
            if port not in produced
        }))
        uid = next(_IDS)
        current_by_leaf: dict[int, tuple[str, ...]] = {}
        next_by_leaf: dict[int, tuple[str, ...]] = {}
        for lid, machine in machines.items():
            width = max(1, ceil(log2(max(2, machine.n_states))))
            prefix = f"net_{uid}_c{lid}"
            current_by_leaf[lid] = tuple(f"{prefix}_s{i}" for i in range(width))
            next_by_leaf[lid] = tuple(f"{prefix}_n{i}" for i in range(width))

        dep_lids = _dependency_order(spec, lids)
        if variable_order == "grouped":
            declaration = [
                *(x for lid in lids for x in current_by_leaf[lid]),
                *external_inputs,
                *(x for lid in lids for x in next_by_leaf[lid]),
            ]
        elif variable_order == "interleaved":
            declaration = [
                *(x for lid in lids for pair in zip(current_by_leaf[lid], next_by_leaf[lid]) for x in pair),
                *external_inputs,
            ]
        else:
            declaration = [
                *external_inputs,
                *(x for lid in dep_lids for pair in zip(current_by_leaf[lid], next_by_leaf[lid]) for x in pair),
            ]
        bdd = _new_bdd()
        bdd.declare(*declaration)

        local_outputs: dict[str, object] = {}
        valid = bdd.true
        initial = bdd.true
        for lid, machine in machines.items():
            current = current_by_leaf[lid]
            local_valid = bdd.false
            for state in range(machine.n_states):
                local_valid |= _cube(bdd, current, state)
            valid &= local_valid
            initial &= _cube(bdd, current, machine.initial)
            for bit, port in enumerate(machine.outputs):
                local_outputs[port] = _table_function(
                    bdd, current, machine.output_bits[:, bit]
                )

        input_functions = {port: bdd.var(port) for port in external_inputs}
        input_functions.update(local_outputs)
        next_functions: list[object] = []
        partitions: list[object] = []
        for lid, machine in machines.items():
            current = current_by_leaf[lid]
            port_functions = tuple(input_functions[port] for port in machine.inputs)
            width = len(current)
            functions = [bdd.false for _ in range(width)]
            for state in range(machine.n_states):
                state_guard = _cube(bdd, current, state)
                for symbol in range(machine.alphabet_size):
                    guard = state_guard
                    for bit, function in enumerate(port_functions):
                        guard &= function if (symbol >> bit) & 1 else ~function
                    target = int(machine.next_state[state, symbol])
                    for bit in range(width):
                        if (target >> bit) & 1:
                            functions[bit] |= guard
            for next_name, function in zip(next_by_leaf[lid], functions):
                partitions.append(_equiv(bdd.var(next_name), function))
                next_functions.append(function)

        state_variables = tuple(x for lid in lids for x in current_by_leaf[lid])
        next_variables = tuple(x for lid in lids for x in next_by_leaf[lid])
        outputs = {
            port: local_outputs[port]
            for port in sorted(keep & produced)
        }
        result = cls(
            name,
            bdd,
            state_variables,
            next_variables,
            external_inputs,
            outputs,
            initial,
            valid,
            None,
            tuple(next_functions),
            certificate_metadata={
                "backend": BDD_BACKEND,
                "source": "NetworkSpec",
                "component_count": len(lids),
                "compiled_without_product_enumeration": True,
                "selected_leaves": lids,
            },
            variable_order=variable_order,
            transition_partitions=tuple(partitions),
        )
        result.compute_reachable()
        return result

    @classmethod
    def compose(
        cls,
        machines: Sequence["SymbolicMachine"],
        keep_outputs: Iterable[str],
        *,
        name: str = "symbolic-product",
        variable_order: str = "dependency",
    ) -> "SymbolicMachine":
        """Synchronously compose symbolic atoms with exact signal substitution."""
        if not machines:
            raise ValueError("at least one machine is required")
        produced: dict[str, tuple[SymbolicMachine, object]] = {}
        for machine in machines:
            for port, function in machine.output_functions.items():
                if port in produced:
                    raise ValueError(f"multiple drivers for {port}")
                produced[port] = (machine, function)
        external = tuple(sorted({
            port for machine in machines for port in machine.inputs if port not in produced
        }))
        all_current = tuple(x for machine in machines for x in machine.state_variables)
        all_next = tuple(x for machine in machines for x in machine.next_state_variables)
        if len(set(all_current + all_next + external)) != len(all_current + all_next + external):
            raise ValueError("symbolic state variables must be globally unique")
        internal_inputs = sorted({
            port for machine in machines for port in machine.inputs if port in produced
        })
        if variable_order == "grouped":
            declaration = [*all_current, *external, *internal_inputs, *all_next]
        else:
            pairs = [x for machine in machines for pair in zip(
                machine.state_variables, machine.next_state_variables
            ) for x in pair]
            declaration = (
                [*external, *internal_inputs, *pairs]
                if variable_order == "dependency"
                else [*pairs, *external, *internal_inputs]
            )
        bdd = _new_bdd()
        bdd.declare(*declaration)

        def copied(machine: SymbolicMachine, function):
            return machine.bdd.copy(function, bdd)

        copied_outputs = {
            port: copied(machine, function)
            for port, (machine, function) in produced.items()
        }
        substitutions = {
            port: copied_outputs[port] if port in copied_outputs else bdd.var(port)
            for machine in machines for port in machine.inputs
        }
        initial = bdd.true
        valid = bdd.true
        next_functions: list[object] = []
        partitions: list[object] = []
        for machine in machines:
            initial &= copied(machine, machine.initial_predicate)
            valid &= copied(machine, machine.valid_state_predicate)
            for next_name, function in zip(machine.next_state_variables, machine.next_state_functions):
                target = bdd.let(
                    {port: substitutions[port] for port in machine.inputs},
                    copied(machine, function),
                )
                next_functions.append(target)
                partitions.append(_equiv(bdd.var(next_name), target))
        outputs = {
            port: copied_outputs[port]
            for port in sorted(set(keep_outputs) & set(copied_outputs))
        }
        result = cls(
            name,
            bdd,
            all_current,
            all_next,
            external,
            outputs,
            initial,
            valid,
            None,
            tuple(next_functions),
            certificate_metadata={
                "backend": BDD_BACKEND,
                "source": "symbolic synchronous composition",
                "children": [machine.name for machine in machines],
                "internal_signals_hidden": sorted(set(produced) - set(outputs)),
            },
            variable_order=variable_order,
            transition_partitions=tuple(partitions),
        )
        result.compute_reachable()
        return result

    def rename(self, mapping: Mapping[str, str]) -> "SymbolicMachine":
        """Return an exact variable-renamed copy in a fresh manager."""
        variables = set(self.bdd.vars)
        target_names = {name: mapping.get(name, name) for name in variables}
        if len(set(target_names.values())) != len(target_names):
            raise ValueError("renaming is not injective")
        bdd = _new_bdd()
        ordered = sorted(variables, key=self.bdd.level_of_var)
        bdd.declare(*(target_names[x] for x in ordered))

        def transfer(function):
            temporary = _new_bdd()
            temporary.declare(*ordered)
            copied = self.bdd.copy(function, temporary)
            # Copy first, then use a manager where both source and targets exist
            # is unnecessary: dd.copy preserves the declaration levels, so a
            # direct structural recursion gives a clean arbitrary rename.
            memo: dict[int, object] = {}

            def walk(node):
                key = int(node)
                if key in memo:
                    return memo[key]
                if node == temporary.true:
                    return bdd.true
                if node == temporary.false:
                    return bdd.false
                level, low, high = temporary.succ(node)
                var = temporary.var_at_level(level)
                regular = bdd.ite(
                    bdd.var(target_names[var]), walk(high), walk(low)
                )
                result = ~regular if node.negated else regular
                memo[key] = result
                return result

            return walk(copied)

        reachable = transfer(self.reachable_predicate) if self.reachable_predicate is not None else None
        return SymbolicMachine(
            self.name,
            bdd,
            tuple(target_names[x] for x in self.state_variables),
            tuple(target_names[x] for x in self.next_state_variables),
            tuple(target_names[x] for x in self.input_variables),
            {port: transfer(function) for port, function in self.output_functions.items()},
            transfer(self.initial_predicate),
            transfer(self.valid_state_predicate),
            transfer(self.transition_relation) if self.transition_relation is not None else None,
            tuple(transfer(function) for function in self.next_state_functions),
            reachable,
            dict(self.certificate_metadata),
            self.variable_order,
            tuple(transfer(partition) for partition in self.transition_partitions),
        )

    def exists(self, variables: Iterable[str], predicate):
        return self.bdd.exist(set(variables), predicate)

    def compute_reachable(self) -> object:
        """Least symbolic reachability fixed point over all external inputs."""
        current = self.initial_predicate & self.valid_state_predicate
        rename = dict(zip(self.next_state_variables, self.state_variables))
        iterations = 0
        while True:
            image_next = self._relational_image(current)
            image = self.bdd.let(rename, image_next) & self.valid_state_predicate
            updated = current | image
            iterations += 1
            if updated == current:
                break
            current = updated
        self.reachable_predicate = current
        self.certificate_metadata["reachability_iterations"] = iterations
        self.certificate_metadata["reachable_bdd_nodes"] = unique_node_count(
            self.bdd, (current,)
        )
        return current

    def _relational_image(self, states):
        """Exact partitioned relational product with early quantification."""
        elimination = (*self.state_variables, *self.input_variables)
        rank = {name: index for index, name in enumerate(elimination)}
        buckets: list[list[tuple[object, int]]] = [[] for _ in elimination]
        outputs: list[object] = []

        def elimination_mask(function) -> int:
            mask = 0
            for name in function.support:
                index = rank.get(name)
                if index is not None:
                    mask |= 1 << index
            return mask

        def place(function, mask: int) -> None:
            if mask:
                first = (mask & -mask).bit_length() - 1
                buckets[first].append((function, mask))
            else:
                outputs.append(function)

        place(states, elimination_mask(states))
        partitions = self.transition_partitions
        if not partitions:
            partitions = tuple(
                _equiv(self.bdd.var(name), function)
                for name, function in zip(
                    self.next_state_variables, self.next_state_functions
                )
            )
        for partition in partitions:
            place(partition, elimination_mask(partition))
        for index, variable in enumerate(elimination):
            if not buckets[index]:
                continue
            product = self.bdd.true
            combined_mask = 0
            for factor, mask in buckets[index]:
                product &= factor
                combined_mask |= mask
            place(
                self.bdd.exist({variable}, product),
                combined_mask & ~(1 << index),
            )
        result = self.bdd.true
        for factor in outputs:
            result &= factor
        return result

    def to_explicit(self, *, max_state_bits: int = 20) -> Machine:
        """Enumerate a small symbolic machine for bidirectional cross-checking."""
        if len(self.state_variables) > max_state_bits:
            raise ValueError("explicit conversion state-bit limit exceeded")
        reachable = (
            self.reachable_predicate
            if self.reachable_predicate is not None
            else self.compute_reachable()
        )
        assignments = list(self.bdd.pick_iter(
            reachable, care_vars=set(self.state_variables)
        ))
        assignments.sort(key=lambda a: sum(
            int(a[name]) << bit for bit, name in enumerate(self.state_variables)
        ))
        encodings = [tuple(bool(a[x]) for x in self.state_variables) for a in assignments]
        state_index = {bits: i for i, bits in enumerate(encodings)}
        initial_pick = self.bdd.pick(
            self.initial_predicate, care_vars=set(self.state_variables)
        )
        assert initial_pick is not None
        initial = state_index[tuple(bool(initial_pick[x]) for x in self.state_variables)]
        ns = np.empty((len(assignments), 1 << len(self.inputs)), dtype=np.int32)
        ob = np.empty((len(assignments), len(self.outputs)), dtype=np.uint8)
        for state, assignment in enumerate(assignments):
            current_values = {x: bool(assignment[x]) for x in self.state_variables}
            for bit, function in enumerate(self.output_functions.values()):
                ob[state, bit] = int(_evaluate(self.bdd, function, current_values))
            for symbol in range(1 << len(self.inputs)):
                values = dict(current_values)
                values.update({name: bool((symbol >> bit) & 1)
                               for bit, name in enumerate(self.inputs)})
                target = tuple(_evaluate(self.bdd, f, values) for f in self.next_state_functions)
                ns[state, symbol] = state_index[target]
        return Machine(self.name, self.inputs, self.outputs, initial, ns, ob)

    def state_count(self) -> int:
        reachable = (
            self.reachable_predicate
            if self.reachable_predicate is not None
            else self.compute_reachable()
        )
        support = set(reachable.support)
        if not support.issubset(self.state_variables):
            raise AssertionError("reachable predicate depends on non-state variables")
        ordered = sorted(support, key=self.bdd.level_of_var)
        compact = _new_bdd()
        compact.declare(*ordered)
        copied = self.bdd.copy(reachable, compact)
        count = int(compact.count(copied, nvars=len(ordered)))
        return count << (len(self.state_variables) - len(ordered))


def variable_order_metrics(spec: NetworkSpec) -> dict[str, dict[str, int | str]]:
    """Build all required orders and report exact reachable/root DAG sizes."""
    metrics: dict[str, dict[str, int | str]] = {}
    for order in ("grouped", "interleaved", "dependency"):
        machine = SymbolicMachine.from_network(spec, variable_order=order, name=f"order-{order}")
        metrics[order] = {
            "backend": BDD_BACKEND,
            "bdd_nodes": machine.bdd_node_count,
            "reachable_bdd_nodes": int(machine.certificate_metadata["reachable_bdd_nodes"]),
        }
    return metrics
