# MORPH-LIFT 复现指南

## 环境

推荐 Python 3.11，以便从源码构建 `dd.cudd`。Python 3.11+、NumPy、pytest、dd、z3-solver、psutil 已声明或用于测试。

```bash
cd MORPH_Exact_Research_Package
python3.11 -m venv .venv311
.venv311/bin/python -m pip install -e . pytest
```

PyPI 的通用 `dd` wheel 可能只包含 `autoref`。下面按 dd 0.6.0 自带构建开关安装 CUDD；临时目录不写入仓库：

```bash
lift_tmp=$(mktemp -d)
.venv311/bin/python -m pip download \
  --no-binary=:all: --no-deps -d "$lift_tmp" dd==0.6.0
DD_CUDD=1 DD_FETCH=1 .venv311/bin/python -m pip install \
  --no-build-isolation --force-reinstall "$lift_tmp/dd-0.6.0.tar.gz"
.venv311/bin/python -c 'from dd import cudd; print(cudd.BDD())'
```

若 CUDD 不可构建，代码自动退回精确 `dd.autoref`；小测试仍可运行，但已保存的负结果表明它不满足本机强尺度门槛。

## 测试

```bash
.venv311/bin/python -m pytest -q
```

预期：`16 passed`。原包在任何修改前的基线是 `8 passed in 2.53s`。

## 分阶段复现

每次运行使用时间戳创建新的 `results_lift/raw/run-*.jsonl`，不会覆盖旧 raw 结果。

```bash
# n≤12 全子集 Oracle、五种显式策略；n=12 在本机约 141 秒
.venv311/bin/python scripts/run_lift.py --phase small

# MORPH-Exact/Hyper 的逐候选 raw/quotient trace
.venv311/bin/python scripts/run_lift.py --phase traces

# 显式扩展状态和固定 120 秒门槛记录
.venv311/bin/python scripts/run_lift.py --phase explicit

# n=8…4096 符号缩放、完整 BDD/SMT 证书、三种变量顺序
.venv311/bin/python scripts/run_lift.py --phase scaling

# 1000 随机布尔机 + 500 随机网络 + 全部 GaugeCycle 小实例
.venv311/bin/python scripts/run_lift.py --phase validation

# 5–10 组件 exact OPT 反例搜索；发现最小规模后停止
.venv311/bin/python scripts/run_lift.py \
  --phase counterexample --counterexample-trials 25
```

一次运行全部阶段：

```bash
.venv311/bin/python scripts/run_lift.py --phase all
```

## 关键现有证据

- `results_lift/summary.json`：最终机器可读摘要。
- `results_lift/raw/run-20260830-172947.jsonl`：n≤12 Oracle 和策略比较。
- `results_lift/raw/run-20260830-173348.jsonl`：n≤4096 符号缩放与变量顺序。
- `results_lift/raw/run-20260830-174104.jsonl`：显式扩展负结果。
- `results_lift/raw/run-20260830-174227.jsonl`：1500 次验证与 Gauge 小实例。
- `results_lift/raw/run-20260830-174416.jsonl`：逐候选 raw/quotient trace。
- `results_lift/raw/run-20260830-174917.jsonl`：5–10 组件完整反例搜索摘要。
- `results_lift/raw/negative-development-20260830.jsonl`：未删除的失败配置。
- `results_lift/counterexamples/minimal_epg_vs_opt.json`：可复现最小规模反例。
- `results_lift/counterexamples/maximum_ratio_epg_vs_opt.json`：搜索范围最大比值反例。

计时和 RSS 与机器有关；商状态数、同构关系、BDD 恒等式、SMT UNSAT 和反例成本应保持不变。
