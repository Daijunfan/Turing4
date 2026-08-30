# MORPH-GEN Claim Ledger

This ledger is normative. A claim not listed here is not an endorsed project
claim. BDD node counts are never treated as intrinsic behavioral complexity.

| Claim | Classification | Scope/evidence |
|---|---|---|
| F/G/H homomorphism preserves every future trace | **KNOWN_PRIOR_RESULT** | Standard deterministic automaton/coalgebra morphism induction; proved for completeness in `THEORY_GEN.md`. |
| Future-output predicate-algebra atoms correspond to the canonical behavioral quotient | **KNOWN_PRIOR_RESULT** | Myhill–Nerode/observable algebra/coalgebraic minimization correspondence. |
| Canonical behavioral quotients are invariant under bijective coordinate conjugacy | **FORMALLY_PROVED** | Direct trace conjugacy and induced quotient isomorphism in `THEORY_GEN.md`. |
| Dependency graph/SCC/community structure alone cannot determine an exact macrostate | **FORMALLY_PROVED** | Two-node graph-twin counterexample with exhaustive quotient tables. |
| Minimal affine observable generator recovery is polynomial and avoids 2^n enumeration | **KNOWN_PRIOR_RESULT** for observability; **FORMALLY_PROVED** for this representation/algorithm | GF(2) observable row-space closure; implementation uses bitset circuits and dual certificates. |
| Sparse bounded-degree ANF recovery is polynomial under the stated exclusive-pivot closure condition | **FORMALLY_PROVED** | Conditional theorem 5B, not a claim for all bounded-degree encodings. |
| MORPH-GEN synthesizes explicit F/G/H rather than merely storing BDD classes | **EXHAUSTIVELY_VERIFIED** on small instances | Circuit gate counts and serialized basis digests are recorded per run. |
| Same synthesis entry point handles at least six latent-machine classes without family branches | **EXHAUSTIVELY_VERIFIED** | Parity, modulo-3, modulo-5, pattern, handshake, traffic; additional ABP, bbara and product runs. |
| Small affine/triangular/Feistel SLO instances match explicit canonical quotients | **EXHAUSTIVELY_VERIFIED** | Three encodings × nine latent machines in `results_gen/raw/small-*.jsonl`. |
| No recovered macro bit is a direct physical coordinate in the SLO matrix | **EXHAUSTIVELY_VERIFIED** on small matrix | SAT/Tseitin obfuscation checks and support metrics. |
| Affine n=4096,k<=8 completes below 120 s and 4 GiB without microstate enumeration | **EMPIRICALLY_SUPPORTED** | Full 20-seed/config scaling matrix plus independent representative run. |
| Triangular degree-2,n=256 completes below 300 s and 8 GiB | **EMPIRICALLY_SUPPORTED** | Full degree/sparsity/seed matrix; exact ANF pivot proofs and dual certificates. |
| BGC is globally minimal for every synthesized non-affine basis | **INCONCLUSIVE** | Macro bit count is minimal; shared-AIG gate count is optimized within implemented templates, not globally proven minimum. |
| All degree<=d sparse triangular encodings are polynomially recoverable | **INCONCLUSIVE** | The theorem additionally requires exclusive pivots and closure sparsity; broader substitutions can explode. |
| Generic shared-AIG CEGIS scales polynomially under arbitrary Feistel encodings | **REJECTED** | Small exact runs succeed, but physical-coordinate BDD normalization is representation-sensitive and larger calibration hits resource limits. |
| Eight globally mixed binary behavioral organs are recovered as two recursive levels | **EMPIRICALLY_SUPPORTED** | G-support SCC factorization recovers 8/8 blocks without metadata. These are two-state behavioral projections labeled by origin, not full high-state family products. |
| Sixteen globally mixed organs are currently supported | **REJECTED** | Current explicit public `MacroMachine` table would require 2^32 entries; negative result retained. |
| MORPH-GEN has established a universal coordinate-free synthesis algorithm for arbitrary finite systems | **INCONCLUSIVE** | Exact when a backend terminates and certifies; no general polynomial or completeness bound. |
| This prototype is a Turing-Award-level result | **REJECTED** | It is a finite-state research prototype with explicit scope and negative results. |

## Allowed phase conclusion

`SUPPORTED` is allowed only if every minimum success gate in `RESULTS_GEN.md` is
backed by current raw evidence. Feistel-wide or arbitrary-circuit universality is
not part of that conclusion. If affine and triangular evidence or dual
certificates fail on reproduction, the conclusion must be lowered to `PARTIAL`
or `REJECTED`.
