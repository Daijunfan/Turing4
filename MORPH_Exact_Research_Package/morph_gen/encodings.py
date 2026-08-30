from __future__ import annotations

from dataclasses import dataclass
from math import ceil, log2
from random import Random
from typing import Sequence

from .aig import AIG


class ReversibleEncoding:
    width: int

    def encode(self, aig: AIG, latent: Sequence[int]) -> tuple[int, ...]:
        raise NotImplementedError

    def decode(self, aig: AIG, physical: Sequence[int]) -> tuple[int, ...]:
        raise NotImplementedError

    def decoder_supports(self) -> tuple[frozenset[str], ...]:
        aig = AIG()
        physical = tuple(aig.input(f"p{i}") for i in range(self.width))
        decoded = self.decode(aig, physical)
        return tuple(aig.support(node) for node in decoded)

    def verify_roundtrip(self, exhaustive_limit: int = 16) -> bool:
        if self.width > exhaustive_limit:
            return True
        aig = AIG()
        source = tuple(aig.input(f"s{i}") for i in range(self.width))
        recovered = self.decode(aig, self.encode(aig, source))
        for value in range(1 << self.width):
            assignment = {f"s{i}": bool((value >> i) & 1) for i in range(self.width)}
            bits = aig.evaluate_vector(recovered, assignment)
            if sum(int(bit) << i for i, bit in enumerate(bits)) != value:
                return False
        return True


@dataclass(frozen=True)
class DenseAffineEncoding(ReversibleEncoding):
    width: int
    operations: tuple[tuple[int, int], ...]
    permutation: tuple[int, ...]
    offset: int

    @classmethod
    def random(cls, width: int, seed: int) -> "DenseAffineEncoding":
        if width < 2:
            raise ValueError("dense affine encoding needs at least two bits")
        rng = Random(seed)
        rounds = max(8, 5 * ceil(log2(width)))
        operations: list[tuple[int, int]] = []
        for _ in range(rounds):
            order = list(range(width))
            rng.shuffle(order)
            for index in range(0, width - 1, 2):
                left, right = order[index], order[index + 1]
                if rng.getrandbits(1):
                    operations.append((left, right))
                else:
                    operations.append((right, left))
        permutation = list(range(width))
        rng.shuffle(permutation)
        offset = rng.getrandbits(width)
        result = cls(width, tuple(operations), tuple(permutation), offset)
        # The CNOT product is invertible by construction. Extra rounds are added
        # only when a small matrix has an accidentally sparse row.
        rows = result.matrix_rows()
        minimum = max(2, width // 8)
        if min(row.bit_count() for row in rows) < minimum:
            extra = list(result.operations)
            for _ in range(rounds):
                target, source = rng.sample(range(width), 2)
                extra.append((target, source))
            result = cls(width, tuple(extra), tuple(permutation), offset)
        return result

    def encode(self, aig: AIG, latent: Sequence[int]) -> tuple[int, ...]:
        if len(latent) != self.width:
            raise ValueError("affine width mismatch")
        values = list(latent)
        for target, source in self.operations:
            values[target] = aig.xor(values[target], values[source])
        values = [values[index] for index in self.permutation]
        return tuple(
            aig.not_(value) if (self.offset >> bit) & 1 else value
            for bit, value in enumerate(values)
        )

    def decode(self, aig: AIG, physical: Sequence[int]) -> tuple[int, ...]:
        if len(physical) != self.width:
            raise ValueError("affine width mismatch")
        shifted = [
            aig.not_(value) if (self.offset >> bit) & 1 else value
            for bit, value in enumerate(physical)
        ]
        inverse_permutation = [0] * self.width
        for output, source in enumerate(self.permutation):
            inverse_permutation[source] = output
        values = [shifted[inverse_permutation[index]] for index in range(self.width)]
        for target, source in reversed(self.operations):
            values[target] = aig.xor(values[target], values[source])
        return tuple(values)

    def matrix_rows(self) -> tuple[int, ...]:
        rows = [1 << index for index in range(self.width)]
        for target, source in self.operations:
            rows[target] ^= rows[source]
        return tuple(rows[index] for index in self.permutation)


@dataclass(frozen=True)
class TriangularPolynomialEncoding(ReversibleEncoding):
    width: int
    order: tuple[int, ...]
    physical_permutation: tuple[int, ...]
    terms: tuple[tuple[tuple[int, ...], ...], ...]
    degree: int

    @classmethod
    def random(
        cls,
        width: int,
        seed: int,
        protected_indices: Sequence[int],
        degree: int = 2,
        sparsity: int = 4,
    ) -> "TriangularPolynomialEncoding":
        if degree not in (2, 3):
            raise ValueError("triangular degree must be two or three")
        rng = Random(seed)
        protected = tuple(protected_indices)
        ordinary = [index for index in range(width) if index not in protected]
        rng.shuffle(ordinary)
        order = tuple(ordinary + list(protected))
        anchor_count = min(len(ordinary), max(4, degree * sparsity))
        anchors = ordinary[:anchor_count]
        position = {logical: index for index, logical in enumerate(order)}
        terms: list[tuple[tuple[int, ...], ...]] = []
        for ordered_index, logical in enumerate(order):
            if ordered_index < anchor_count:
                terms.append(())
                continue
            pool = [candidate for candidate in anchors if position[candidate] < ordered_index]
            if len(pool) < degree:
                terms.append(())
                continue
            chosen: set[tuple[int, ...]] = set()
            target_terms = max(1, sparsity if logical in protected else sparsity // 2)
            while len(chosen) < target_terms:
                term_degree = rng.randint(2, min(degree, len(pool)))
                chosen.add(tuple(sorted(rng.sample(pool, term_degree))))
            terms.append(tuple(sorted(chosen)))
        physical = list(range(width))
        rng.shuffle(physical)
        return cls(width, order, tuple(physical), tuple(terms), degree)

    def _polynomial(self, aig: AIG, term_list: Sequence[Sequence[int]], values: Sequence[int]) -> int:
        return aig.xor_many(
            aig.and_many(values[index] for index in term)
            for term in term_list
        )

    def encode(self, aig: AIG, latent: Sequence[int]) -> tuple[int, ...]:
        ordered = [latent[index] for index in self.order]
        encoded_order = [
            aig.xor(value, self._polynomial(aig, self.terms[index], latent))
            for index, value in enumerate(ordered)
        ]
        logical_encoded = [0] * self.width
        for ordered_index, logical in enumerate(self.order):
            logical_encoded[logical] = encoded_order[ordered_index]
        return tuple(logical_encoded[index] for index in self.physical_permutation)

    def decode(self, aig: AIG, physical: Sequence[int]) -> tuple[int, ...]:
        inverse_physical = [0] * self.width
        for output, logical in enumerate(self.physical_permutation):
            inverse_physical[logical] = output
        logical_encoded = [physical[inverse_physical[index]] for index in range(self.width)]
        decoded = [0] * self.width
        for ordered_index, logical in enumerate(self.order):
            decoded[logical] = aig.xor(
                logical_encoded[logical],
                self._polynomial(aig, self.terms[ordered_index], decoded),
            )
        return tuple(decoded)


@dataclass(frozen=True)
class FeistelEncoding(ReversibleEncoding):
    width: int
    rounds: int
    round_terms: tuple[tuple[tuple[tuple[int, ...], ...], ...], ...]
    physical_permutation: tuple[int, ...]

    @classmethod
    def random(cls, width: int, seed: int, rounds: int = 3) -> "FeistelEncoding":
        if width % 2 or width < 4:
            raise ValueError("Feistel encoding requires an even width >= 4")
        if rounds not in (2, 3, 4):
            raise ValueError("Feistel rounds must be 2, 3, or 4")
        rng = Random(seed)
        half = width // 2
        description = []
        for _ in range(rounds):
            outputs = []
            for _bit in range(half):
                terms = set()
                while len(terms) < 3:
                    degree = rng.choice((1, 2, 2, 3 if half >= 3 else 2))
                    terms.add(tuple(sorted(rng.sample(range(half), degree))))
                outputs.append(tuple(sorted(terms)))
            description.append(tuple(outputs))
        permutation = list(range(width))
        rng.shuffle(permutation)
        return cls(width, rounds, tuple(description), tuple(permutation))

    @staticmethod
    def _round(aig: AIG, values: Sequence[int], terms) -> tuple[int, ...]:
        return tuple(
            aig.xor_many(aig.and_many(values[index] for index in term) for term in output)
            for output in terms
        )

    def encode(self, aig: AIG, latent: Sequence[int]) -> tuple[int, ...]:
        half = self.width // 2
        left, right = tuple(latent[:half]), tuple(latent[half:])
        for terms in self.round_terms:
            function = self._round(aig, right, terms)
            left, right = right, tuple(aig.xor(x, y) for x, y in zip(left, function))
        combined = left + right
        return tuple(combined[index] for index in self.physical_permutation)

    def decode(self, aig: AIG, physical: Sequence[int]) -> tuple[int, ...]:
        inverse = [0] * self.width
        for output, source in enumerate(self.physical_permutation):
            inverse[source] = output
        combined = tuple(physical[inverse[index]] for index in range(self.width))
        half = self.width // 2
        left, right = combined[:half], combined[half:]
        for terms in reversed(self.round_terms):
            previous_right = left
            function = self._round(aig, previous_right, terms)
            previous_left = tuple(aig.xor(x, y) for x, y in zip(right, function))
            left, right = previous_left, previous_right
        return left + right


@dataclass(frozen=True)
class MixedEncoding(ReversibleEncoding):
    width: int
    inner: ReversibleEncoding
    outer: DenseAffineEncoding

    @classmethod
    def random(
        cls,
        width: int,
        seed: int,
        protected_indices: Sequence[int],
    ) -> "MixedEncoding":
        inner = TriangularPolynomialEncoding.random(
            width, seed, protected_indices, degree=2, sparsity=2
        )
        outer = DenseAffineEncoding.random(width, seed ^ 0x5A17)
        return cls(width, inner, outer)

    def encode(self, aig: AIG, latent: Sequence[int]) -> tuple[int, ...]:
        return self.outer.encode(aig, self.inner.encode(aig, latent))

    def decode(self, aig: AIG, physical: Sequence[int]) -> tuple[int, ...]:
        return self.inner.decode(aig, self.outer.decode(aig, physical))
