# MORPH-GEN Results

## Phase conclusion

**SUPPORTED — within the exact scope below.**

MORPH-GEN synthesized non-coordinate physical-state functions F, explicit macro
transition/output circuits G/H, and recursively composable proof-carrying macro
machines under unknown dense-affine and triangular-polynomial encodings. All 16
minimum success gates in `results_gen/summary.json` are true.

This conclusion does **not** claim arbitrary-coordinate universality. Large
Feistel scaling is INCONCLUSIVE and sixteen-organ recursion is currently
REJECTED. Those failures are part of the result.

## Minimum-gate ledger

| Requirement | Status | Current evidence |
|---|---|---|
| Existing MORPH-LIFT 16/16 remains passing | **SUPPORTED** | Clean audit plus final combined tests. |
| Independent LIFT audit has no core unexplained failure | **SUPPORTED** | `AUDIT_LIFT.md`; fresh 5,451 subset, n=512/4096 and 1,500 validations. |
| All small instances equal explicit canonical quotients | **SUPPORTED** | 1,527/1,527 exact runs, zero errors. |
| One kernel handles at least six latent-machine classes | **SUPPORTED** | Nine classes × three encodings; no family branch. |
| No family/encoding metadata used | **SUPPORTED** | Public metadata guard, AST test, backend API only accepts `CircuitSystem`. |
| Affine and triangular encodings both succeed | **SUPPORTED** | 640/640 affine and 720/720 triangular scaling runs. |
| Recovered F is not physical feature selection | **SUPPORTED** | Small matrix SAT/support checks find no direct physical macro coordinate. |
| Macro bit count equals exact oracle lower bound | **SUPPORTED** | Zero mismatches in small/affine/triangular raw records. |
| Every installed atom has dual certificates | **SUPPORTED** | BDD identities plus independent Z3/Tseitin or GF(2)-normalized residuals. |
| affine n=4096,k≤8, <=120 s and <=4 GiB | **SUPPORTED** | 80 runs; worst 1.727 s and 454,557,696 bytes. |
| triangular degree-2,n=256, <=300 s and <=8 GiB | **SUPPORTED** | 60 runs; worst 0.487 s and 117,506,048 bytes. |
| Eight globally mixed organs recover two levels | **SUPPORTED** | 8/8 G-dependency blocks, depth 2, no metadata. |
| Same-graph/different-quotient counterexample | **SUPPORTED** | Two-node exhaustive proof; quotients 1 vs 4. |
| Nontrivial polynomial recovery theorem | **SUPPORTED** | Affine observability theorem and conditional sparse triangular-pivot theorem. |
| >=10x over best completed non-oracle baseline or baseline resource limit | **SUPPORTED** | Generic MORPH-LIFT exceeds 120 s; MORPH-GEN worst 1.727 s, lower-bound speedup 69.5x. |
| Negative results retained | **SUPPORTED** | Partial raw matrices, Feistel boundary, n=4096 development timeouts, and 16-organ limit remain present. |

## Small exact matrix

Authoritative raw file: `results_gen/raw/small-20260831-024906.jsonl`.

| Category | Runs | Success | Exact macro bits | Dual proof | Explicit isomorphism |
|---|---:|---:|---:|---:|---:|
| Nine latent classes × three encodings | 27 | 27 | 27 | 27 | 27 |
| Random Boolean machines | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 |
| Random machine networks | 500 | 500 | 500 | 500 | 500 |
| **Total** | **1,527** | **1,527** | **1,527** | **1,527** | **1,527** |

The nine classes are parity, modulo-3, modulo-5, pattern detector, handshake,
alternating-bit protocol, traffic controller, bbara-derived controller, and a
heterogeneous product. Backend selection over all 1,527 runs was:

- affine: 103;
- bounded-degree ANF: 541;
- shared-AIG CEGIS: 883.

The three input encodings are balanced across the random suite. Nonlinear random
instances use 6–14 physical bits; the overall test/scale matrix covers physical
widths through 4,096. A retained development run shows that a 20-bit nonlinear
dense scramble can exceed the generic SMT proof budget; it is not counted as a
successful exact validation.

## Affine scaling

Authoritative raw file: `results_gen/raw/scaling-affine-20260831-023544.jsonl`.

Matrix: n=32,64,128,256,512,1024,2048,4096; k=1,2,4,8; 20 seeds per
configuration. Results:

- 640/640 synthesis successes;
- 640/640 exact macro-bit matches;
- 640/640 dual certificates;
- no microstate enumeration;
- n=4096: 80/80 successes;
- n=4096 worst wall time: 1.7266 s;
- n=4096 worst peak RSS: 454,557,696 bytes;
- n=4096 maximum measured BGC: 14,536 gates.

The polynomial algorithm is the observable GF(2) row-space closure. The public
system does not expose the affine encoder; the backend detects affine semantics
from the supplied circuit.

## Triangular ANF scaling

Authoritative raw file: `results_gen/raw/scaling-triangular-20260831-015406.jsonl`.

Matrix: n=16,32,64,128,256,512; degree=2,3; sparsity=2,4,8; 20 seeds.

- 720/720 synthesis successes;
- 720/720 exact 8-bit recovery;
- 720/720 bounded-degree ANF backend selections;
- 720/720 dual certificates;
- degree-2 n=256: 60/60 successes;
- degree-2 n=256 worst wall time: 0.4874 s;
- degree-2 n=256 worst peak RSS: 117,506,048 bytes;
- full triangular worst wall time: 0.9106 s;
- full triangular worst peak RSS: 141,115,392 bytes.

The decisive optimization is exact sparse-ANF pivot elimination. Failed lower
degree attempts are recorded as INCONCLUSIVE before the successful true degree;
they are not silently skipped.

## Feistel boundary

Small Feistel instances are exact: all nine fixed latent classes and the random
small suite pass. The scaling calibration raw file
`results_gen/raw/scaling-feistel-20260831-020037.jsonl` contains an n=16,
two-round, k=8 success in 24.17 seconds.

Larger calibration exposes coordinate-sensitive BDD cost: even k=1 at n=32,
four rounds exceeded a 60-second probe. The requested 300-run Feistel matrix is
therefore **INCONCLUSIVE**, not counted as completed and not used in the
SUPPORTED minimum-gate decision. This prevents the affine/ANF result from being
misreported as arbitrary-encoding universality.

## Recursive global mixing

Raw file: `results_gen/raw/scaling-multi-20260831-020321.jsonl`.

| Oracle organ count | Recovered blocks | Depth | Metadata read | Status |
|---:|---:|---:|---|---|
| 2 | 2 | 2 | no | SUPPORTED |
| 4 | 4 | 2 | no | SUPPORTED |
| 8 | 8 | 2 | no | SUPPORTED |
| 16 | — | — | no | INCONCLUSIVE |

The 8-organ experiment uses globally affine-mixed independent two-state
behavioral projections labeled by eight controller origins. It proves the
recursive factorization mechanism and lack of coordinate blocks; it is not a
claim that the full high-state eight-family Cartesian product has been recovered.
The 16-organ explicit `MacroMachine` table would require 2^32 entries and is a
retained negative result.

## Baselines

Raw file: `results_gen/raw/baseline-affine-n4096.jsonl`.

On the same n=4096,k=8 affine SLO:

- generic MORPH-LIFT AIG→BDD compilation did not finish within 120 seconds and
  was interrupted at 141.49 seconds / 2,714,566,656 bytes;
- explicit canonical quotient requires 2^4096 microstates;
- explicit STP requires a 2^4096-dimensional logical state representation;
- physical feature selection is rejected by the dense decoder proof;
- MORPH-GEN completed all 80 matrix runs, worst 1.727 seconds / 454,557,696 bytes.

Using the 120-second hard gate gives a conservative speedup lower bound of
69.5x over the strongest completed generic BDD baseline attempt. Oracle decoder
is excluded from ranking.

## BGC and proof artifacts

BGC counts shared `AND/XOR/NOT/MUX` gates in F/G/H and excludes proof files.
Representative certificates are in:

- `results_gen/certificates/affine-representative.json`;
- `results_gen/certificates/triangular-representative.json`;
- `results_gen/certificates/feistel-representative.json`.

The project proves minimal macro bit count and pairwise behavioral minimality.
It does not claim globally minimum AIG gate count for every non-affine instance.

## Preserved negative results

- multiple interrupted triangular development matrices (177, 237, 239, 477
  records) expose BDD projection, timing-field, and CUDD lifecycle bottlenecks;
- an earlier complete affine file has invalid outer timing due a field overwrite
  and remains retained but non-authoritative;
- partial nonlinear random files include the 20-bit generic proof boundary;
- Feistel scaling remains incomplete;
- sixteen-organ explicit reification is unsupported;
- all authoritative files are selected by exact expected record count in
  `scripts/summarize_gen.py`.

## Final scientific statement

MORPH-GEN demonstrates coordinate-free exact macrostate synthesis on two
non-equivalent scalable encoding classes (dense affine and sparse triangular
polynomial), produces explicit F/G/H circuits, installs recursively composable
macro machines, and attaches independent universal certificates. The result is
SUPPORTED for these stated classes. Generic arbitrary-coordinate synthesis,
full Feistel scaling, globally minimum BGC, and sixteen-organ explicit
reification remain open or rejected.
