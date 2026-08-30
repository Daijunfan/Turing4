# Reproduction guide

## Environment

- Python 3.11+
- NumPy 2.0+
- pytest 9+

## Install and test

```bash
python -m pip install -e .
# 离线环境可使用：python -m pip install -e . --no-build-isolation --no-deps
pytest -q
```

Expected current result: `8 passed`.

## Exactness stress suites

```bash
PYTHONPATH=. python scripts/validate_exactness.py \
  --out results/exactness_reproduced.json \
  --random-minimizers 10000 \
  --split-trials 1000 \
  --hierarchy-trials 500
```

## Main benchmark suites

```bash
PYTHONPATH=. python scripts/run_benchmarks.py \
  --out-dir results/reproduced \
  --scenarios scaling cross_family baselines
```

## Natural systems

```bash
PYTHONPATH=. python scripts/run_natural.py \
  --family parity --mode hyper --depths 3 4 5 6 7 \
  --out results/natural_parity_reproduced.csv

PYTHONPATH=. python scripts/run_natural.py \
  --family modsum --mode hyper --depths 2 3 4 5 \
  --out results/natural_modsum_reproduced.csv
```

## Existing raw evidence

- `results/exactness_minimizers_10000.json`
- `results/exactness_splits_1000.json`
- `results/exactness_hierarchies_500.json`
- `results/scaling_parity.csv`
- `results/scaling_bbara.csv`
- `results/cross_family.csv`
- `results/baseline_parity.csv`
- `results/baseline_bbara.csv`
- `results/natural_parity.csv`
- `results/natural_modsum.csv`
- `results/certificate_ledger_natural_parity_d7.json`
- `results/certificate_ledger_bbara_d4.json`

All timing values are machine-dependent. Exactness and certificate checks should be invariant.
