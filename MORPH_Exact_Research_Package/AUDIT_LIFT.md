# Independent MORPH-LIFT Audit

Audit date: 2026-08-30 (Asia/Shanghai)  
Repository baseline: `9e1697cf79e4ca26150854e34b86221ad3b8094f`  
Audit environment: new Python 3.11 virtual environment `.audit-venv-lift`

This audit did not treat `RESULTS_LIFT.md` or `results_lift/summary.json` as evidence by themselves. It rebuilt the environment, reran the required experiments, inspected the implementation, and compared newly generated raw results.

## Environment and test audit

| Item | Status | Independent evidence |
|---|---|---|
| Portable pinned dependencies | **VERIFIED** | The previous environment freeze contained an unusable temporary path for dd; the audit added `requirements-lock.txt` with fixed versions and installed it in a new environment. |
| CUDD source identity | **VERIFIED** | Freshly downloaded `dd-0.6.0.tar.gz` SHA-256: `4baadadc9b2ebf6136a5b84dc51a43cec5fe91203286cd377e1e093358cdffcd`. |
| Native backend availability | **VERIFIED** | CUDD was rebuilt from that source with `DD_CUDD=1 DD_FETCH=1`; `from dd import cudd` succeeded. |
| Complete tests | **VERIFIED** | Clean environment result: `16 passed in 3.45s`. |
| Original 8 test groups remain intact | **VERIFIED** | `tests/test_core.py` is present and included in the 16-test run; no old test or result was removed. |

## Exact subset and Oracle audit

New raw evidence: `results_lift/raw/run-20260830-234457.jsonl`.

| n | Nonempty subsets | Proper-subset law | Full quotient | OPT | New wall time |
|---:|---:|---|---:|---:|---:|
| 4 | 15 | **VERIFIED** | 2 | 4 | 0.006 s |
| 6 | 63 | **VERIFIED** | 2 | 5 | 0.022 s |
| 8 | 255 | **VERIFIED** | 2 | 6 | 0.296 s |
| 10 | 1,023 | **VERIFIED** | 2 | 7 | 5.630 s |
| 12 | 4,095 | **VERIFIED** | 2 | 8 | 131.961 s |

Every row reports `all_open_quotient_proofs=true`, `proper_subset_power_law=true`, and an independently constructed full machine isomorphic to the two-state reference.

The claimed 5,451 is:

\[
(2^4-1)+(2^6-1)+(2^8-1)+(2^{10}-1)+(2^{12}-1)=5451.
\]

It comprises 5,446 nonempty proper subsets plus the five complete systems. The number is therefore **VERIFIED** and is not 5,451 proper subsets.

## Symbolic scaling and certificate audit

New raw evidence: `results_lift/raw/run-20260830-234731.jsonl`.

| n | BDD nodes | Reachable BDD nodes | Predicates | Macro bits | Wall time | Peak RSS | BDD checks | Z3 checks |
|---:|---:|---:|---:|---:|---:|---:|---|---|
| 512 | 5,119 | 1,024 | 1 | 1 | 0.306 s | 152,616,960 B | **VERIFIED** | all UNSAT |
| 4,096 | 40,959 | 8,192 | 1 | 1 | 36.769 s | 1,904,754,688 B | **VERIFIED** | all UNSAT |

For n=4096 the audit independently reproduced:

- `dd.cudd` backend;
- one closure iteration and one synthesized macro bit;
- two reachable macro states isomorphic to the independent reference;
- all eight BDD bad conditions false;
- all seven independently assembled Z3 bad conditions UNSAT;
- no global-state enumeration flag;
- the same exact BDD node counts as the earlier run;
- execution below 120 seconds and peak RSS below 4 GiB.

The prior exact timing (44.99 s) and RSS (1,884,585,984 B) are machine/run-dependent resource observations, not invariants. The new 36.77 s and 1,904,754,688 B reproduce the stated resource class and thresholds. Treating the old wall time as an exact deterministic constant would be **CLAIM TOO STRONG**; the threshold claim is **VERIFIED**.

## Random exactness audit

New raw evidence: `results_lift/raw/run-20260830-234832.jsonl`.

| Item | Status | Result |
|---|---|---|
| 1,000 random Boolean machines | **VERIFIED** | Exhaustive explicit/symbolic quotient agreement, zero failures. |
| 500 random machine networks | **VERIFIED** | Independent monolithic/symbolic agreement, zero failures. |
| GaugeCycle n=4,6,8,10,12 | **VERIFIED** | Explicit reachable enumeration, macro isomorphism and dual certificates pass. |
| Random trajectories as proof | **VERIFIED** | Absent: every sampled instance is checked universally over its finite transition relation; trajectories are not the correctness oracle. |

## Forbidden-oracle and implementation audit

The audit inspected `symbolic.py`, `predicate_closure.py`, `candidates.py`, `certificates.py`, and `oracle.py`, including an AST scan of selection branches.

| Potential leak | Status | Finding |
|---|---|---|
| Family-name algorithm branch | **VERIFIED** | Absent: no `if`/`match` selection branch references family metadata. |
| GaugeCycle-name branch | **VERIFIED** | Absent: generic algorithm modules do not import or branch on the Gauge generator. |
| XOR-specific recovery path | **VERIFIED** | Absent: `bdd_xor` only encodes Boolean inequality/equivalence; no transition-family detector or XOR decoder exists. |
| Benchmark filename selection | **VERIFIED** | Absent: no filename-based branch exists. |
| Oracle latent variables | **VERIFIED** | Absent: LIFT input and closure use only executable `NetworkSpec`/BDD functions; metadata is not read for synthesis. |
| SCC used as proof of abstraction | **VERIFIED** | Absent: SCCs only propose candidates; `certify_region` requires full symbolic closure and certificates before installation. |

The GaugeCycle generator necessarily contains its benchmark equation, and validation code necessarily names the benchmark. These occurrences are not algorithm-selection paths.

## Counterexample audit

Both saved EPG counterexamples were reconstructed from JSON in the clean environment:

| File | Status | Reproduced result |
|---|---|---|
| `minimal_epg_vs_opt.json` | **VERIFIED** | MORPH=5, OPT=3, ratio=1.6666666666666667. |
| `maximum_ratio_epg_vs_opt.json` | **VERIFIED** | MORPH=8.658211482751796, OPT=3, ratio=2.8860704942505984. |

The claim that EPG is always optimal remains **FAILED**, as correctly marked `REJECTED` by the LIFT report.

## Audit conclusion

| Core LIFT claim | Status |
|---|---|
| Exact two-state global quotient and exponential proper-subset quotients | **VERIFIED** |
| Exact subset-DP barrier through n=12 | **VERIFIED** |
| Proof-carrying one-bit symbolic re-atomization | **VERIFIED** |
| n=512 and n=4096 resource thresholds | **VERIFIED** |
| 1,500 random exact validations with zero errors | **VERIFIED** |
| General polynomial BDD behavior for arbitrary non-Gauge systems | **NOT REPRODUCIBLE** as a general claim because LIFT never claimed or proved it; it remains explicitly inconclusive. |
| Exact old wall-clock/RSS values as immutable constants | **CLAIM TOO STRONG**; only thresholds and structural counts are reproducible invariants. |

No unexplained core failure remains. The only reproducibility defect found was the absence of a portable dependency lock; it was repaired before this audit run. MORPH-GEN work may proceed without inheriting unverified LIFT claims.
