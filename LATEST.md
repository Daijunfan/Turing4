# Latest Verified Stage

- Stage: **MORPH-GEN — Coordinate-Free Generative Re-Atomization**
- UTC publication date: **2026-08-30**
- Verified research-artifact commit: **`0d820730858fb66510ece85e4d24116b8f527ddd`**
- Planned immutable release tag: **`morph-gen-v0.1`**
- Test result: **24 passed in 4.21s**
- Machine summary conclusion: **SUPPORTED**

The hash above is the commit containing the audited code, experiments, raw
evidence and scientific documents. This metadata file necessarily lives in a
later commit because a Git commit cannot contain its own hash. The release tag
and final push verification are recorded in `PUSH_STATUS.md`.

## Core conclusion

MORPH-GEN automatically synthesized exact minimum-bit macrostate functions F
and explicit G/H circuits after unknown dense-affine and sparse triangular
polynomial state-coordinate scrambling. Installed macro machines passed BDD and
independent Z3/GF(2) certificates and remain recursively composable.

Decisive evidence:

- clean independent MORPH-LIFT audit, including 5,451 subset checks;
- 1,527/1,527 small exact MORPH-GEN runs;
- 640/640 affine scaling runs;
- affine n=4096,k<=8: 80/80, worst 1.727 s / 454,557,696 bytes;
- 720/720 triangular ANF runs;
- triangular degree-2,n=256: 60/60, worst 0.487 s / 117,506,048 bytes;
- eight globally mixed binary behavioral organs recovered as eight macro blocks
  and two recursive levels;
- conservative >=69.5x advantage over the generic MORPH-LIFT BDD hard gate.

## Failed or inconclusive items

- Full large Feistel scaling matrix: **INCONCLUSIVE**. Small exact Feistel runs
  succeed; random-coordinate BDD normalization becomes resource-sensitive.
- Sixteen-organ explicit public `MacroMachine`: **INCONCLUSIVE/unsupported** due
  a 2^32 transition-table representation.
- Global minimum AIG gate count for arbitrary non-affine F/G/H: **INCONCLUSIVE**.
- Universal coordinate-free synthesis for arbitrary Boolean circuits: **not
  claimed**.

All partial matrices and failed development configurations remain under
`MORPH_Exact_Research_Package/results_gen/raw/`.

## Primary result paths

- `MORPH_Exact_Research_Package/AUDIT_LIFT.md`
- `MORPH_Exact_Research_Package/RESULTS_GEN.md`
- `MORPH_Exact_Research_Package/THEORY_GEN.md`
- `MORPH_Exact_Research_Package/CLAIMS_GEN.md`
- `MORPH_Exact_Research_Package/RELATED_WORK_GEN.md`
- `MORPH_Exact_Research_Package/REPRODUCE_GEN.md`
- `MORPH_Exact_Research_Package/results_gen/summary.json`
- `PUBLIC_ARTIFACTS.json`

## Reproduction

After the locked CUDD environment setup in `REPRODUCE_GEN.md`:

```bash
cd MORPH_Exact_Research_Package
python -m pytest -q
python scripts/run_gen.py
python scripts/run_gen_scaling.py --phase affine --seeds 20
python scripts/run_gen_scaling.py --phase triangular --seeds 20
```
