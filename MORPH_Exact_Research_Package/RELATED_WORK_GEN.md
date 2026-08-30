# MORPH-GEN Related-Work Boundary

This document separates established theory from the implementation and empirical
claims of MORPH-GEN. It is not a priority or patent search.

## Automata minimization and coalgebra

The behavioral equivalence used here is the deterministic Moore-machine form of
Myhill–Nerode equivalence. The statement that the canonical quotient is unique
up to isomorphism, and that behavior-preserving morphisms induce trace-equivalent
systems, is established automata/coalgebra theory. Rutten's survey develops
coalgebra as a general theory of state-based systems and behavioral equivalence:

- J. J. M. M. Rutten, “Universal Coalgebra: A Theory of Systems,” *Theoretical
  Computer Science* 249 (2000), 3–80,
  [CWI record and final manuscript](https://ir.cwi.nl/pub/48/),
  DOI `10.1016/S0304-3975(00)00056-6`.

MORPH-GEN does not claim the quotient/predicate-algebra correspondence as new.
Its narrower contribution is an executable search for a compact circuit basis
F/G/H under unknown coordinates, with proof artifacts and recursive reification.

## Linear observability and realization

Coordinate-free observability, unobservable subspaces and minimal realization
are classical linear-systems concepts. Kalman's treatment explicitly emphasizes
that observability is invariant under algebraic equivalence:

- R. E. Kalman, “Mathematical Description of Linear Dynamical Systems,” *SIAM
  Journal on Control* 1 (1963), 152–192,
  [author-hosted scan](https://people.duke.edu/~hpgavin/SystemID/References/Kalman-JSIAM-1963.pdf).

The affine backend is a GF(2) observable row-space computation. Its polynomial
recovery theorem is an application of this established idea to the repository's
shared Boolean-circuit representation, not a new observability theorem.

## Boolean control networks, STP and invariant dual subspaces

Cheng, Qi and Li provide the semi-tensor-product framework, including Boolean
network state-space representations, observability, realization and feedback
decomposition:

- D. Cheng, H. Qi, Z. Li, *Analysis and Control of Boolean Networks: A
  Semi-tensor Product Approach*, Springer, 2011,
  [publisher page](https://link.springer.com/book/10.1007/978-0-85729-097-7),
  DOI `10.1007/978-0-85729-097-7`.
- D. Cheng, Z. Li, H. Qi, “Realization of Boolean Control Networks,”
  *Automatica* 46(1) (2010), 62–69,
  [publisher abstract](https://www.sciencedirect.com/science/article/abs/pii/S000510980900497X),
  DOI `10.1016/j.automatica.2009.10.036`.

Recent invariant-dual-subspace work explicitly relates Boolean-network dual
subspaces to state partitions and output-generated observability:

- “Structures of M-Invariant Dual Subspaces with Respect to a Boolean Network,”
  [arXiv:2301.10961](https://arxiv.org/abs/2301.10961).

These are direct neighbors of the generator-algebra view. MORPH-GEN's BGC metric
and sparse coordinate-scrambling experiments should not be read as renaming STP
or M-invariant theory. The explicit STP baseline in this repository is limited
by its 2^n logical-state representation; that is an implementation/representation
comparison, not a claim that STP lacks symbolic variants.

## BDDs and variable ordering

Reduced ordered BDDs and their canonical fixed-order algorithms originate with
Bryant's foundational work:

- R. E. Bryant, “Graph-Based Algorithms for Boolean Function Manipulation,”
  *IEEE Transactions on Computers* 35(8) (1986), 677–691,
  [bibliographic record](https://dblp.org/rec/journals/tc/Bryant86.html),
  DOI `10.1109/TC.1986.1676819`.

That paper also makes clear that worst-case representation size is exponential
and practical cost depends on ordering. MORPH-GEN therefore reports BDD nodes
only as backend resources. BGC counts fixed-basis F/G/H circuit gates and is not
defined by a BDD order.

## AIGs and logic synthesis

Hash-consed AND/inverter graphs, rewriting and SAT-based verification are
standard logic-synthesis technology. ABC is a representative academic and
industrial-strength system:

- R. Brayton, A. Mishchenko, “ABC: An Academic Industrial-Strength Verification
  Tool,” CAV 2010, LNCS 6174, 24–40,
  [paper record/PDF](https://citeseerx.ist.psu.edu/document?doi=1c1ee7b39616c52e96d91e243dc8996cfed11027&repid=rep1&type=pdf),
  DOI `10.1007/978-3-642-14295-6_5`.

MORPH-GEN's AIG class is a small proof-oriented prototype with an extended fixed
gate basis (`AND`, `XOR`, `NOT`, `MUX`), not a replacement for ABC and not an AIG
novelty claim.

## CEGIS, sketching and active automata learning

SAT-based completion of finite program sketches and counterexample-guided
refinement are established synthesis patterns:

- A. Solar-Lezama, L. Tancau, R. Bodík, S. Seshia, V. Saraswat,
  “Combinatorial Sketching for Finite Programs,” ASPLOS 2006, 404–415,
  [author PDF](https://people.csail.mit.edu/asolar/papers/asplos06-final.pdf).

Learning a minimal automaton using membership/equivalence queries and
counterexamples is also classical:

- D. Angluin, “Learning Regular Sets from Queries and Counterexamples,”
  *Information and Computation* 75(2) (1987), 87–106,
  [paper PDF](https://homepages.math.uic.edu/~lreyzin/papers/angluin87.pdf),
  DOI `10.1016/0890-5401(87)90052-6`.

MORPH-GEN differs in its input (a complete symbolic transition/output circuit,
not an external teacher) and its output (explicit microstate predicates F plus
G/H circuits and certificates). Its use of counterexamples and universal circuit
templates is prior methodology applied to this representation problem.

## Exact scope of novelty

The project currently supports the following combined contribution claim:

1. a coordinate-scrambled finite-state benchmark with explicit leakage audits;
2. three representation backends selected without family/encoding metadata;
3. explicit BGC accounting for synthesized F/G/H circuits;
4. dual proof checking and macro-state distinguishing words;
5. recursive reification compatible with the preceding MORPH symbolic atom;
6. empirical separation between specialized affine/ANF recovery and generic
   coordinate-sensitive BDD/explicit baselines.

No claim is made that each ingredient is individually new, that the current AIG
gate count is globally minimal, or that the generic backend is polynomial or
complete for arbitrary Boolean circuits.
