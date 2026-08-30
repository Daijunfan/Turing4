# MORPH-Exact / MORPH-Hyper

A proof-carrying prototype of **self-abstracting computation**.

Open deterministic synchronous Moore transducers are treated as computational atoms. The runtime discovers candidate organs from executable signal dependencies, counterfactually composes them, computes the exact minimal external behavior quotient, exhaustively verifies a re-atomization certificate, and promotes the quotient to a new atom of the same type. MORPH-Hyper additionally commits certified three-region organs to cross pairwise neutral barriers.

## Quick start

```bash
python -m pip install -e .
# 离线环境可使用：python -m pip install -e . --no-build-isolation --no-deps
pytest -q
```

Read:

- [`REPORT.md`](REPORT.md): Chinese research report, formal model, results, limitations and novelty boundary.
- [`REPRODUCE.md`](REPRODUCE.md): exact commands and raw evidence inventory.

The repository contains 2,500+ lines of Python, eight test groups, 10,000/1,000/500 exactness stress suites, a public LGSynth91 controller, natural XOR/modular-sum networks, baselines, and per-merge certificate ledgers.

No selected abstraction is statistical. If a candidate cannot be exhaustively certified within the declared finite resource budget, it is not installed.

## MORPH-LIFT

The additive `morph_lift` package implements exact symbolic, proof-carrying
re-atomization while preserving the original explicit engines as reference
backends.  See:

- [`RESULTS_LIFT.md`](RESULTS_LIFT.md): requirement-by-requirement status and experiments.
- [`THEORY_LIFT.md`](THEORY_LIFT.md): GaugeCycle nucleation-barrier proof and symbolic certificate argument.
- [`REPRODUCE_LIFT.md`](REPRODUCE_LIFT.md): CUDD build, tests, and non-overwriting experiment commands.

## MORPH-GEN (current stage)

MORPH-GEN receives only a circuit-level state system after unknown reversible
coordinate scrambling. It synthesizes explicit F/G/H circuits, checks them with
BDD and independent Z3/GF(2) backends, and reifies the result as a recursively
composable `MacroMachine`.

Current audited scope:

- dense-affine and sparse triangular-pivot scaling: SUPPORTED;
- nine latent-machine classes under affine/triangular/Feistel at small scale:
  exhaustively verified;
- arbitrary encodings and large Feistel scaling: INCONCLUSIVE;
- sixteen-organ explicit reification: unsupported.

Read [`RESULTS_GEN.md`](RESULTS_GEN.md), [`THEORY_GEN.md`](THEORY_GEN.md),
[`CLAIMS_GEN.md`](CLAIMS_GEN.md), [`RELATED_WORK_GEN.md`](RELATED_WORK_GEN.md),
and [`REPRODUCE_GEN.md`](REPRODUCE_GEN.md).
