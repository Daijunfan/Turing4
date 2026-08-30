# Turing4 — MORPH Research Package

Current stage: **MORPH-GEN — Coordinate-Free Generative Re-Atomization**.

The repository contains three additive stages:

1. MORPH-Exact / MORPH-Hyper: explicit proof-carrying recursive minimization;
2. MORPH-LIFT: symbolic nucleation-barrier separation and predicate closure;
3. MORPH-GEN: synthesis of explicit macrostate functions F, transition G and
   output decoder H after unknown reversible state-coordinate scrambling.

## Latest verified result

- Existing LIFT audit reproduced 16/16 tests, all 5,451 requested subset checks,
  n=4096 certificates and the 1,000+500 exact validation suite.
- MORPH-GEN combined suite: 24/24 tests.
- Small MORPH-GEN matrix: 1,527/1,527 exact successes.
- Affine scaling: 640/640 successes; n=4096 worst 1.727 s and 455 MB.
- Triangular ANF scaling: 720/720 successes; degree-2 n=256 worst 0.487 s and
  118 MB.
- Eight globally mixed binary behavioral organs recover eight blocks and two
  recursive levels.
- Large Feistel scaling is INCONCLUSIVE; sixteen-organ explicit reification is
  unsupported. These negative results are retained.

The precise phase conclusion is **SUPPORTED for dense-affine and sparse
triangular-pivot classes**, not for arbitrary encodings.

## One-command verification

After following the locked environment/CUDD setup in
[`REPRODUCE_GEN.md`](MORPH_Exact_Research_Package/REPRODUCE_GEN.md):

```bash
cd MORPH_Exact_Research_Package && python -m pytest -q
```

## Read first

- [`AUDIT_LIFT.md`](MORPH_Exact_Research_Package/AUDIT_LIFT.md)
- [`RESULTS_GEN.md`](MORPH_Exact_Research_Package/RESULTS_GEN.md)
- [`THEORY_GEN.md`](MORPH_Exact_Research_Package/THEORY_GEN.md)
- [`CLAIMS_GEN.md`](MORPH_Exact_Research_Package/CLAIMS_GEN.md)
- [`RELATED_WORK_GEN.md`](MORPH_Exact_Research_Package/RELATED_WORK_GEN.md)
- [`REPRODUCE_GEN.md`](MORPH_Exact_Research_Package/REPRODUCE_GEN.md)
- [`results_gen/summary.json`](MORPH_Exact_Research_Package/results_gen/summary.json)

## Known limits

The prototype addresses deterministic finite Boolean systems. Generic
shared-AIG synthesis remains representation-sensitive; the current Feistel
backend does not meet the full scaling matrix. Macro bit minimality is proved,
but globally minimum AIG gate count is not. The results are a scoped research
prototype, not a claim of a universal abstraction algorithm or a Turing-Award-
level accomplishment.
