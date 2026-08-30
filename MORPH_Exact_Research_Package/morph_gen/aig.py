from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from operator import xor
from typing import Iterable, Mapping, Sequence

import z3


@dataclass(frozen=True)
class Gate:
    op: str
    args: tuple[int, ...] = ()
    name: str = ""


@dataclass(frozen=True)
class AffineForm:
    mask: int
    constant: int = 0

    def __xor__(self, other: "AffineForm") -> "AffineForm":
        return AffineForm(self.mask ^ other.mask, self.constant ^ other.constant)

    def evaluate(self, value: int) -> int:
        return ((self.mask & value).bit_count() & 1) ^ self.constant

    @property
    def support_size(self) -> int:
        return self.mask.bit_count()


@dataclass(frozen=True)
class ANF:
    """Sparse algebraic normal form; each monomial is a variable bit mask."""

    monomials: frozenset[int]

    @classmethod
    def constant(cls, value: bool) -> "ANF":
        return cls(frozenset({0}) if value else frozenset())

    @classmethod
    def variable(cls, index: int) -> "ANF":
        return cls(frozenset({1 << index}))

    def __xor__(self, other: "ANF") -> "ANF":
        return ANF(self.monomials ^ other.monomials)

    def __and__(self, other: "ANF") -> "ANF":
        return self.multiply(other)

    def multiply(self, other: "ANF", max_terms: int | None = None) -> "ANF":
        parity: set[int] = set()
        for left in self.monomials:
            for right in other.monomials:
                product = left | right
                if product in parity:
                    parity.remove(product)
                else:
                    parity.add(product)
                if max_terms is not None and len(parity) > max_terms:
                    raise OverflowError("ANF multiplication term limit exceeded")
        return ANF(frozenset(parity))

    def __invert__(self) -> "ANF":
        return self ^ ANF.constant(True)

    @property
    def degree(self) -> int:
        return max((term.bit_count() for term in self.monomials), default=0)

    @property
    def support_mask(self) -> int:
        return reduce(int.__or__, self.monomials, 0)

    def evaluate(self, value: int) -> int:
        result = 0
        for monomial in self.monomials:
            result ^= int((value & monomial) == monomial)
        return result

    def substitute(self, replacements: Sequence["ANF"], max_terms: int = 100_000) -> "ANF":
        result = ANF.constant(False)
        for monomial in self.monomials:
            product = ANF.constant(True)
            bits = monomial
            while bits:
                low = bits & -bits
                product &= replacements[low.bit_length() - 1]
                if len(product.monomials) > max_terms:
                    raise OverflowError("ANF substitution term limit exceeded")
                bits ^= low
            result ^= product
            if len(result.monomials) > max_terms:
                raise OverflowError("ANF substitution term limit exceeded")
        return result


class AIG:
    """Hash-consed Boolean DAG over the fixed AND/XOR/NOT/MUX gate basis."""

    def __init__(self) -> None:
        self.nodes: list[Gate] = [Gate("CONST", name="0"), Gate("CONST", name="1")]
        self._unique: dict[tuple, int] = {("CONST", 0): 0, ("CONST", 1): 1}
        self._inputs: dict[str, int] = {}
        self._opaque_nonce = 0

    @property
    def false(self) -> int:
        return 0

    @property
    def true(self) -> int:
        return 1

    def input(self, name: str) -> int:
        if name in self._inputs:
            return self._inputs[name]
        node = len(self.nodes)
        self.nodes.append(Gate("INPUT", name=name))
        self._inputs[name] = node
        self._unique[("INPUT", name)] = node
        return node

    def _gate(self, op: str, args: tuple[int, ...], extra: object = None) -> int:
        key = (op, args, extra)
        existing = self._unique.get(key)
        if existing is not None:
            return existing
        node = len(self.nodes)
        self.nodes.append(Gate(op, args))
        self._unique[key] = node
        return node

    def and_(self, left: int, right: int) -> int:
        if left == 0 or right == 0:
            return 0
        if left == 1:
            return right
        if right == 1 or left == right:
            return left
        args = tuple(sorted((left, right)))
        return self._gate("AND", args)

    def xor(self, left: int, right: int) -> int:
        if left == 0:
            return right
        if right == 0:
            return left
        if left == right:
            return 0
        args = tuple(sorted((left, right)))
        return self._gate("XOR", args)

    def not_(self, value: int) -> int:
        if value == 0:
            return 1
        if value == 1:
            return 0
        gate = self.nodes[value]
        if gate.op == "NOT":
            return gate.args[0]
        return self._gate("NOT", (value,))

    def mux(self, select: int, when_true: int, when_false: int) -> int:
        if when_true == when_false:
            return when_true
        if select == 0:
            return when_false
        if select == 1:
            return when_true
        if when_true == 1 and when_false == 0:
            return select
        return self._gate("MUX", (select, when_true, when_false))

    def opaque_mux(self, select: int, value: int) -> int:
        """Semantics-preserving circuit dependency retained for structural audits."""
        self._opaque_nonce += 1
        return self._gate("MUX", (select, value, value), self._opaque_nonce)

    def xor_many(self, values: Iterable[int]) -> int:
        level = list(values)
        if not level:
            return 0
        while len(level) > 1:
            level = [
                self.xor(level[i], level[i + 1]) if i + 1 < len(level) else level[i]
                for i in range(0, len(level), 2)
            ]
        return level[0]

    def and_many(self, values: Iterable[int]) -> int:
        level = list(values)
        if not level:
            return 1
        while len(level) > 1:
            level = [
                self.and_(level[i], level[i + 1]) if i + 1 < len(level) else level[i]
                for i in range(0, len(level), 2)
            ]
        return level[0]

    def equal(self, left: int, right: int) -> int:
        return self.not_(self.xor(left, right))

    def evaluate(self, root: int, assignment: Mapping[str, bool]) -> bool:
        values = [False] * len(self.nodes)
        values[1] = True
        for node_id, gate in enumerate(self.nodes[2:], start=2):
            if gate.op == "INPUT":
                values[node_id] = bool(assignment[gate.name])
            elif gate.op == "AND":
                values[node_id] = values[gate.args[0]] and values[gate.args[1]]
            elif gate.op == "XOR":
                values[node_id] = values[gate.args[0]] ^ values[gate.args[1]]
            elif gate.op == "NOT":
                values[node_id] = not values[gate.args[0]]
            elif gate.op == "MUX":
                values[node_id] = values[gate.args[1]] if values[gate.args[0]] else values[gate.args[2]]
            else:
                raise ValueError(gate.op)
        return values[root]

    def evaluate_vector(self, roots: Sequence[int], assignment: Mapping[str, bool]) -> tuple[bool, ...]:
        values = [False] * len(self.nodes)
        values[1] = True
        for node_id, gate in enumerate(self.nodes[2:], start=2):
            if gate.op == "INPUT":
                values[node_id] = bool(assignment[gate.name])
            elif gate.op == "AND":
                values[node_id] = values[gate.args[0]] and values[gate.args[1]]
            elif gate.op == "XOR":
                values[node_id] = values[gate.args[0]] ^ values[gate.args[1]]
            elif gate.op == "NOT":
                values[node_id] = not values[gate.args[0]]
            else:
                values[node_id] = values[gate.args[1]] if values[gate.args[0]] else values[gate.args[2]]
        return tuple(values[root] for root in roots)

    def support(self, roots: int | Iterable[int]) -> frozenset[str]:
        todo = [roots] if isinstance(roots, int) else list(roots)
        seen: set[int] = set()
        names: set[str] = set()
        while todo:
            node = todo.pop()
            if node in seen:
                continue
            seen.add(node)
            gate = self.nodes[node]
            if gate.op == "INPUT":
                names.add(gate.name)
            else:
                todo.extend(gate.args)
        return frozenset(names)

    def reachable_nodes(self, roots: Iterable[int]) -> set[int]:
        todo = list(roots)
        seen: set[int] = set()
        while todo:
            node = todo.pop()
            if node in seen:
                continue
            seen.add(node)
            todo.extend(self.nodes[node].args)
        return seen

    def gate_count(self, roots: Iterable[int]) -> int:
        return sum(
            self.nodes[node].op in {"AND", "XOR", "NOT", "MUX"}
            for node in self.reachable_nodes(roots)
        )

    def gate_histogram(self, roots: Iterable[int]) -> dict[str, int]:
        result = {op: 0 for op in ("AND", "XOR", "NOT", "MUX")}
        for node in self.reachable_nodes(roots):
            op = self.nodes[node].op
            if op in result:
                result[op] += 1
        return result

    def substitute(self, root: int, replacements: Mapping[str, int]) -> int:
        memo = {0: 0, 1: 1}
        reachable = sorted(self.reachable_nodes((root,)))
        for node_id in reachable:
            if node_id < 2:
                continue
            gate = self.nodes[node_id]
            if gate.op == "INPUT":
                memo[node_id] = replacements.get(gate.name, node_id)
            elif gate.op == "AND":
                memo[node_id] = self.and_(memo[gate.args[0]], memo[gate.args[1]])
            elif gate.op == "XOR":
                memo[node_id] = self.xor(memo[gate.args[0]], memo[gate.args[1]])
            elif gate.op == "NOT":
                memo[node_id] = self.not_(memo[gate.args[0]])
            else:
                memo[node_id] = self.mux(
                    memo[gate.args[0]], memo[gate.args[1]], memo[gate.args[2]]
                )
        return memo[root]

    def to_affine(self, roots: Sequence[int], variables: Sequence[str]) -> tuple[AffineForm, ...] | None:
        positions = {name: index for index, name in enumerate(variables)}
        forms: dict[int, AffineForm | None] = {
            0: AffineForm(0, 0),
            1: AffineForm(0, 1),
        }
        for node in sorted(self.reachable_nodes(roots)):
            if node < 2:
                continue
            gate = self.nodes[node]
            if gate.op == "INPUT":
                position = positions.get(gate.name)
                forms[node] = AffineForm(1 << position, 0) if position is not None else None
            elif gate.op == "XOR":
                left, right = (forms[x] for x in gate.args)
                forms[node] = left ^ right if left is not None and right is not None else None
            elif gate.op == "NOT":
                value = forms[gate.args[0]]
                forms[node] = value ^ AffineForm(0, 1) if value is not None else None
            elif gate.op == "AND":
                left, right = (forms[x] for x in gate.args)
                if left == AffineForm(0, 0) or right == AffineForm(0, 0):
                    forms[node] = AffineForm(0, 0)
                elif left == AffineForm(0, 1):
                    forms[node] = right
                elif right == AffineForm(0, 1):
                    forms[node] = left
                else:
                    forms[node] = None
            else:
                select, when_true, when_false = gate.args
                if when_true == when_false:
                    forms[node] = forms[when_true]
                else:
                    select_form = forms[select]
                    true_form = forms[when_true]
                    false_form = forms[when_false]
                    if select_form == AffineForm(0, 0):
                        forms[node] = false_form
                    elif select_form == AffineForm(0, 1):
                        forms[node] = true_form
                    elif (
                        select_form is not None
                        and true_form is not None
                        and false_form is not None
                    ):
                        difference = true_form ^ false_form
                        if difference == AffineForm(0, 0):
                            forms[node] = false_form
                        elif difference == AffineForm(0, 1):
                            forms[node] = false_form ^ select_form
                        else:
                            forms[node] = None
                    else:
                        forms[node] = None
        result = tuple(forms[root] for root in roots)
        return result if all(form is not None for form in result) else None

    def to_anf(self, roots: Sequence[int], variables: Sequence[str], max_terms: int = 100_000) -> tuple[ANF, ...]:
        positions = {name: index for index, name in enumerate(variables)}
        forms: dict[int, ANF] = {
            0: ANF.constant(False),
            1: ANF.constant(True),
        }
        for node in sorted(self.reachable_nodes(roots)):
            if node < 2:
                continue
            gate = self.nodes[node]
            if gate.op == "INPUT":
                forms[node] = ANF.variable(positions[gate.name])
            elif gate.op == "XOR":
                forms[node] = forms[gate.args[0]] ^ forms[gate.args[1]]
            elif gate.op == "AND":
                forms[node] = forms[gate.args[0]].multiply(
                    forms[gate.args[1]], max_terms=max_terms
                )
            elif gate.op == "NOT":
                forms[node] = ~forms[gate.args[0]]
            else:
                select, when_true, when_false = gate.args
                forms[node] = (
                    forms[when_false]
                    ^ forms[select].multiply(
                        forms[when_true] ^ forms[when_false], max_terms=max_terms
                    )
                )
            if len(forms[node].monomials) > max_terms:
                raise OverflowError("AIG to ANF term limit exceeded")
        return tuple(forms[root] for root in roots)

    def from_anf(self, function: ANF, variables: Sequence[int]) -> int:
        terms = []
        for monomial in sorted(function.monomials):
            factors = [variables[index] for index in range(len(variables)) if (monomial >> index) & 1]
            terms.append(self.and_many(factors))
        return self.xor_many(terms)

    def to_z3(self, roots: Sequence[int], variables: Mapping[str, z3.BoolRef] | None = None) -> tuple[z3.BoolRef, ...]:
        variables = dict(variables or {})
        expressions: list[z3.BoolRef] = [z3.BoolVal(False), z3.BoolVal(True)]
        for gate in self.nodes[2:]:
            if gate.op == "INPUT":
                expressions.append(variables.get(gate.name, z3.Bool(gate.name)))
            elif gate.op == "AND":
                expressions.append(z3.And(expressions[gate.args[0]], expressions[gate.args[1]]))
            elif gate.op == "XOR":
                expressions.append(z3.Xor(expressions[gate.args[0]], expressions[gate.args[1]]))
            elif gate.op == "NOT":
                expressions.append(z3.Not(expressions[gate.args[0]]))
            else:
                expressions.append(z3.If(
                    expressions[gate.args[0]], expressions[gate.args[1]], expressions[gate.args[2]]
                ))
        return tuple(expressions[root] for root in roots)

    def to_z3_tseitin(
        self,
        roots: Sequence[int],
        variables: Mapping[str, z3.BoolRef] | None = None,
        *,
        prefix: str = "aig",
    ) -> tuple[tuple[z3.BoolRef, ...], tuple[z3.BoolRef, ...]]:
        """Linear-size independent SMT encoding that preserves DAG sharing."""
        variables = dict(variables or {})
        expressions: dict[int, z3.BoolRef] = {
            0: z3.BoolVal(False),
            1: z3.BoolVal(True),
        }
        constraints: list[z3.BoolRef] = []
        for node in sorted(self.reachable_nodes(roots)):
            if node < 2:
                continue
            gate = self.nodes[node]
            if gate.op == "INPUT":
                expressions[node] = variables.get(gate.name, z3.Bool(gate.name))
                continue
            value = z3.Bool(f"{prefix}_g{node}")
            if gate.op == "AND":
                definition = z3.And(expressions[gate.args[0]], expressions[gate.args[1]])
            elif gate.op == "XOR":
                definition = z3.Xor(expressions[gate.args[0]], expressions[gate.args[1]])
            elif gate.op == "NOT":
                definition = z3.Not(expressions[gate.args[0]])
            else:
                definition = z3.If(
                    expressions[gate.args[0]], expressions[gate.args[1]], expressions[gate.args[2]]
                )
            expressions[node] = value
            constraints.append(value == definition)
        return (
            tuple(expressions[root] for root in roots),
            tuple(constraints),
        )

    def truth_table(self, variables: Sequence[int], values: Sequence[int]) -> int:
        if len(values) != 1 << len(variables):
            raise ValueError("truth table width mismatch")
        memo: dict[tuple[int, tuple[int, ...]], int] = {}

        def build(level: int, table: tuple[int, ...]) -> int:
            key = (level, table)
            if key in memo:
                return memo[key]
            if all(value == table[0] for value in table):
                result = self.true if table[0] else self.false
            else:
                low = build(level + 1, table[0::2])
                high = build(level + 1, table[1::2])
                result = self.mux(variables[level], high, low)
            memo[key] = result
            return result

        return build(0, tuple(map(int, values)))

    def serialize(self, roots: Sequence[int]) -> dict:
        reachable = sorted(self.reachable_nodes(roots))
        return {
            "roots": list(roots),
            "nodes": [
                {"id": node, "op": self.nodes[node].op, "args": list(self.nodes[node].args), "name": self.nodes[node].name}
                for node in reachable
            ],
        }
