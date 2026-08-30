from __future__ import annotations

from dataclasses import dataclass
from itertools import count
from typing import Dict, Mapping, Sequence

from .symbolic import SymbolicMachine, _equiv, _evaluate, bdd_xor, unique_node_count


_MACRO_IDS = count()


@dataclass
class ClosureCounterexample:
    iteration: int
    predicate_index: int
    input_assignment: Dict[str, bool]


@dataclass
class PredicateClosureResult:
    source: SymbolicMachine
    predicates: tuple[object, ...]
    output_predicate_indices: Dict[str, int]
    successor_predicates: tuple[object, ...]
    macro_machine: SymbolicMachine
    iterations: int
    counterexamples: tuple[ClosureCounterexample, ...]
    closure_error: object

    @property
    def predicate_count(self) -> int:
        return len(self.predicates)


def _normalized(machine: SymbolicMachine, predicate):
    # Keep the compact representative.  Equivalence and every proof obligation
    # are restricted to reachable states separately; conjoining R into each
    # predicate can needlessly duplicate a large invariant.
    return predicate


def _semantic_index(machine: SymbolicMachine, predicates: Sequence[object], candidate) -> int | None:
    assert machine.reachable_predicate is not None
    for index, predicate in enumerate(predicates):
        if (
            bdd_xor(candidate, predicate) & machine.reachable_predicate
            == machine.bdd.false
        ):
            return index
    return None


def _successor(machine: SymbolicMachine, predicate):
    support = predicate.support
    substitution = {
        name: function
        for name, function in zip(
            machine.state_variables, machine.next_state_functions
        )
        if name in support
    }
    return machine.bdd.let(substitution, predicate) if substitution else predicate


def _build_closure_error(
    machine: SymbolicMachine,
    predicates: Sequence[object],
    successors: Sequence[object],
    macro_variables: Sequence[str],
):
    bdd = machine.bdd
    assert machine.reachable_predicate is not None
    mapping = bdd.true
    for name, predicate in zip(macro_variables, predicates):
        mapping &= _equiv(bdd.var(name), predicate)
    base = machine.reachable_predicate & mapping
    source_variables = set(machine.state_variables)
    errors: list[object] = []
    for successor in successors:
        can_be_one = bdd.exist(source_variables, base & successor)
        can_be_zero = bdd.exist(source_variables, base & ~successor)
        errors.append(can_be_one & can_be_zero)
    combined = bdd.false
    for error in errors:
        combined |= error
    return combined, tuple(errors)


def _construct_macro(
    machine: SymbolicMachine,
    predicates: Sequence[object],
    output_indices: Mapping[str, int],
    successors: Sequence[object],
    iterations: int,
) -> SymbolicMachine:
    bdd = machine.bdd
    uid = next(_MACRO_IDS)
    state = tuple(f"macro_{uid}_z{i}" for i in range(len(predicates)))
    nxt = tuple(f"macro_{uid}_zn{i}" for i in range(len(predicates)))
    bdd.declare(*(x for pair in zip(state, nxt) for x in pair))
    mapping = bdd.true
    for name, predicate in zip(state, predicates):
        mapping &= _equiv(bdd.var(name), predicate)
    assert machine.reachable_predicate is not None
    source_state = set(machine.state_variables)
    reachable = bdd.exist(source_state, machine.reachable_predicate & mapping)
    initial = bdd.exist(source_state, machine.initial_predicate & mapping)
    next_functions = tuple(
        bdd.exist(source_state, machine.reachable_predicate & mapping & successor)
        for successor in successors
    )
    relation = reachable
    for name, function in zip(nxt, next_functions):
        relation &= _equiv(bdd.var(name), function)
    outputs = {port: bdd.var(state[index]) for port, index in output_indices.items()}
    macro = SymbolicMachine(
        f"{machine.name}:macro",
        bdd,
        state,
        nxt,
        machine.input_variables,
        outputs,
        initial,
        reachable,
        relation,
        next_functions,
        reachable,
        certificate_metadata={
            "backend": machine.certificate_metadata.get("backend"),
            "source": "counterexample-driven predicate closure",
            "source_machine": machine.name,
            "predicate_count": len(predicates),
            "closure_iterations": iterations,
            "symbolic_macro_without_state_class_enumeration": True,
            "source_bdd_nodes": machine.bdd_node_count,
        },
        variable_order=machine.variable_order,
    )
    macro.compute_reachable()
    macro.certificate_metadata["macro_bdd_nodes"] = unique_node_count(bdd, macro.roots)
    return macro


def close_predicates(
    machine: SymbolicMachine,
    *,
    max_predicates: int | None = None,
) -> PredicateClosureResult:
    """Discover a transition-closed observable state vector by exact BDD CEGAR.

    The initial set is precisely the external output functions.  A failed
    closure check supplies an input valuation and a next-predicate preimage;
    that state predicate is normalized on the reachable set and added.  No
    explicit state equivalence classes are built.
    """
    if not machine.output_functions:
        raise ValueError("predicate closure requires at least one external output")
    if machine.reachable_predicate is None:
        machine.compute_reachable()
    bdd = machine.bdd
    predicates: list[object] = []
    output_indices: dict[str, int] = {}
    for port, function in machine.output_functions.items():
        index = _semantic_index(machine, predicates, function)
        if index is None:
            index = len(predicates)
            predicates.append(_normalized(machine, function))
        output_indices[port] = index

    macro_variables: list[str] = []
    counterexamples: list[ClosureCounterexample] = []
    checks = 0
    while True:
        checks += 1
        while len(macro_variables) < len(predicates):
            name = f"{machine.name.replace('-', '_')}_closure_z{len(macro_variables)}"
            if name in bdd.vars:
                name += f"_{len(bdd.vars)}"
            bdd.add_var(name)
            macro_variables.append(name)
        successors = tuple(_successor(machine, predicate) for predicate in predicates)
        error, per_predicate_errors = _build_closure_error(
            machine, predicates, successors, macro_variables
        )
        if error == bdd.false:
            break
        witness = bdd.pick(
            error,
            care_vars=set().union(*(
                predicate_error.support
                for predicate_error in per_predicate_errors
            )),
        )
        assert witness is not None
        differing = next(
            index for index, predicate_error in enumerate(per_predicate_errors)
            if _evaluate(bdd, predicate_error, witness)
        )
        input_assignment = {
            name: bool(witness.get(name, False)) for name in machine.input_variables
        }
        refinement = (
            bdd.let(input_assignment, successors[differing])
            if input_assignment else successors[differing]
        )
        if _semantic_index(machine, predicates, refinement) is not None:
            raise AssertionError("closure counterexample produced no new predicate")
        predicates.append(_normalized(machine, refinement))
        counterexamples.append(ClosureCounterexample(
            checks, differing, input_assignment
        ))
        if max_predicates is not None and len(predicates) > max_predicates:
            raise RuntimeError(f"predicate closure exceeded {max_predicates} predicates")

    final_successors = tuple(_successor(machine, predicate) for predicate in predicates)
    final_error, _ = _build_closure_error(
        machine, predicates, final_successors, macro_variables
    )
    macro = _construct_macro(
        machine, predicates, output_indices, final_successors, checks
    )
    return PredicateClosureResult(
        machine,
        tuple(predicates),
        output_indices,
        final_successors,
        macro,
        checks,
        tuple(counterexamples),
        final_error,
    )
