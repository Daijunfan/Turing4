# Reproducing MORPH-GEN

## Locked clean environment

```bash
cd MORPH_Exact_Research_Package
python3.11 -m venv .venv-gen
.venv-gen/bin/python -m pip install -r requirements-lock.txt
.venv-gen/bin/python -m pip install --no-deps -e .
```

The PyPI universal `dd` wheel does not include CUDD on all platforms. Build the
audited source archive and verify it before installation:

```bash
gen_tmp=$(mktemp -d)
.venv-gen/bin/python -m pip download \
  --no-binary=:all: --no-deps -d "$gen_tmp" dd==0.6.0
echo "4baadadc9b2ebf6136a5b84dc51a43cec5fe91203286cd377e1e093358cdffcd  $gen_tmp/dd-0.6.0.tar.gz" \
  | shasum -a 256 -c -
DD_CUDD=1 DD_FETCH=1 .venv-gen/bin/python -m pip install \
  --no-build-isolation --force-reinstall "$gen_tmp/dd-0.6.0.tar.gz"
```

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 \
  .venv-gen/bin/python -m pytest -q -p no:cacheprovider
```

The suite includes the unchanged 16 MORPH-Exact/LIFT tests plus the MORPH-GEN
exact, encoding, certificate, recursion and no-metadata tests.

## Small exact matrix

```bash
.venv-gen/bin/python scripts/run_gen.py
```

This runs nine latent machines under affine, triangular and Feistel encodings.
To repeat the required random exactness matrix:

```bash
.venv-gen/bin/python scripts/run_gen.py \
  --random-machines 1000 --random-networks 500
```

Each instance is isolated, has a 120-second hard limit, and is flushed to a
new timestamped JSONL immediately. No failed seed is removed.

## Scaling matrices

```bash
.venv-gen/bin/python scripts/run_gen_scaling.py \
  --phase affine --seeds 20

.venv-gen/bin/python scripts/run_gen_scaling.py \
  --phase triangular --seeds 20

# Feistel is a boundary/negative experiment; start with calibration.
.venv-gen/bin/python scripts/run_gen_scaling.py \
  --phase feistel --seeds 1

.venv-gen/bin/python scripts/run_gen_scaling.py \
  --phase multi --seeds 1
```

Scaling configurations run in fresh subprocesses. Affine has a 120-second
per-instance hard gate; triangular and Feistel use 300 seconds. Queue results
are written before terminating workers so CUDD destructor time does not pollute
algorithm resource measurements.

## Structural impossibility counterexample

```bash
.venv-gen/bin/python scripts/run_gen_counterexample_search.py
```

The output is saved as
`results_gen/counterexamples/structural_nonidentifiability.json`.

## Evidence policy

- `results_gen/raw/` is append-only.
- Partial/interrupted matrices remain evidence and are not used as complete
  matrices in `summary.json`.
- Oracle decoder data appears only in evaluation wrappers and is excluded from
  synthesis and baseline ranking.
- Representative certificates are stored under `results_gen/certificates/`.
- Exact times and RSS are machine-dependent; Boolean identities, UNSAT results,
  macro-state counts and isomorphism results are invariant.
