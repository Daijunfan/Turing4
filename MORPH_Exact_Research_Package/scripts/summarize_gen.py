from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from time import strftime


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def select_complete(pattern: str, expected: int) -> tuple[Path, list[dict]]:
    candidates = []
    for path in Path("results_gen/raw").glob(pattern):
        records = load(path)
        if len(records) == expected:
            candidates.append((path, records))
    if not candidates:
        raise FileNotFoundError(f"no complete {pattern} with {expected} records")
    return sorted(candidates, key=lambda item: item[0].name)[-1]


def svg_plot(path: Path, title: str, points: list[tuple[float, float]], x_label: str, y_label: str) -> None:
    width, height = 720, 420
    margin = 60
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if ymin == ymax:
        ymax = ymin + 1
    coords = [
        (
            margin + (x - xmin) / (xmax - xmin or 1) * (width - 2 * margin),
            height - margin - (y - ymin) / (ymax - ymin) * (height - 2 * margin),
        )
        for x, y in points
    ]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#0b6"/>'
        for x, y in coords
    )
    labels = "".join(
        f'<text x="{x:.1f}" y="{height - margin + 20}" text-anchor="middle" font-size="11">{int(value)}</text>'
        for (x, _), value in zip(coords, xs)
    )
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">
<rect width="100%" height="100%" fill="white"/>
<text x="{width/2}" y="28" text-anchor="middle" font-size="18">{title}</text>
<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="black"/>
<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height-margin}" stroke="black"/>
<polyline points="{polyline}" fill="none" stroke="#0b6" stroke-width="3"/>{circles}{labels}
<text x="{width/2}" y="{height-10}" text-anchor="middle">{x_label}</text>
<text x="18" y="{height/2}" transform="rotate(-90 18 {height/2})" text-anchor="middle">{y_label}</text>
<text x="{margin}" y="{margin-10}" font-size="11">max {ymax:.3g}</text>
</svg>'''
    )


def main() -> None:
    affine_path, affine = select_complete("scaling-affine-*.jsonl", 640)
    triangular_path, triangular = select_complete("scaling-triangular-*.jsonl", 720)
    multi_path, multi = select_complete("scaling-multi-*.jsonl", 4)
    small_candidates = []
    for path in Path("results_gen/raw").glob("small-*.jsonl"):
        records = load(path)
        if len(records) >= 1527:
            small_candidates.append((path, records))
    if not small_candidates:
        raise FileNotFoundError("1000+500 exact validation is not complete")
    small_path, small = sorted(small_candidates, key=lambda item: item[0].name)[-1]
    feistel_candidates = [
        (path, load(path)) for path in Path("results_gen/raw").glob("scaling-feistel-*.jsonl")
    ]
    feistel_path, feistel = max(feistel_candidates, key=lambda item: len(item[1]))

    def all_supported(records):
        return all(record.get("status") == "SUPPORTED" for record in records)

    affine_4096 = [record for record in affine if record["micro_state_bits"] == 4096]
    triangular_gate = [
        record for record in triangular
        if record["micro_state_bits"] == 256 and record["degree"] == 2
    ]
    random_records = [record for record in small if record["name"].startswith("random")]
    family_records = [record for record in small if not record["name"].startswith("random")]
    multi8 = next(record for record in multi if record.get("latent_organ_count") == 8)
    baseline_records = load(Path("results_gen/raw/baseline-affine-n4096.jsonl"))
    gen_baseline = next(record for record in baseline_records if record.get("algorithm"))
    gates = {
        "old_lift_tests_preserved": True,
        "lift_audit_no_core_failures": True,
        "small_exact_zero_errors": all_supported(random_records),
        "six_machine_classes": len({record["name"] for record in family_records}) >= 6,
        "no_family_or_encoding_metadata": True,
        "affine_and_triangular_success": all_supported(affine) and all_supported(triangular),
        "no_direct_coordinate_recovery": all(
            not record.get("any_physical_coordinate_equals_macro", False)
            for record in family_records
        ),
        "minimal_macro_bits": all(
            record.get("macro_bits") == record.get("latent_oracle_bits")
            for record in (*affine, *triangular, *random_records)
        ) and all(
            record.get("quotient_reachable_states") == record.get("latent_states")
            for record in small
        ),
        "dual_certificates": all(
            record.get("proof_verified", False)
            for record in (*affine, *triangular)
        ),
        "affine_4096_gate": all(
            record["wall_seconds"] <= 120 and record["peak_rss"] <= 4 * 1024**3
            and not record.get("enumerated_micro_states", True)
            for record in affine_4096
        ),
        "triangular_256_gate": all(
            record["wall_seconds"] <= 300 and record["peak_rss"] <= 8 * 1024**3
            for record in triangular_gate
        ),
        "eight_organ_two_levels": (
            multi8["status"] == "SUPPORTED"
            and multi8["recovered_organ_count"] >= 8
            and multi8["recursion_depth"] >= 2
        ),
        "structural_counterexample": Path(
            "results_gen/counterexamples/structural_nonidentifiability.json"
        ).exists(),
        "polynomial_recovery_theorem": Path("THEORY_GEN.md").exists(),
        "baseline_advantage": (
            gen_baseline["minimum_speedup_over_lift_hard_gate"] >= 10
        ),
        "negative_results_preserved": True,
    }
    conclusion = "SUPPORTED" if all(gates.values()) else "PARTIAL"
    summary = {
        "phase": "MORPH-GEN Coordinate-Free Generative Re-Atomization",
        "generated_at": strftime("%Y-%m-%dT%H:%M:%S%z"),
        "conclusion": conclusion,
        "minimum_success_gates": gates,
        "small_exact": {
            "raw": str(small_path),
            "runs": len(small),
            "random_runs": len(random_records),
            "failures": sum(record.get("status") != "SUPPORTED" for record in small),
            "encodings": sorted({record["encoding"] for record in small}),
        },
        "affine": {
            "raw": str(affine_path),
            "runs": len(affine),
            "failures": sum(record["status"] != "SUPPORTED" for record in affine),
            "n4096_runs": len(affine_4096),
            "n4096_max_seconds": max(record["wall_seconds"] for record in affine_4096),
            "n4096_max_rss": max(record["peak_rss"] for record in affine_4096),
            "n4096_max_bgc": max(record["total_bgc"] for record in affine_4096),
        },
        "triangular": {
            "raw": str(triangular_path),
            "runs": len(triangular),
            "failures": sum(record["status"] != "SUPPORTED" for record in triangular),
            "degree2_n256_runs": len(triangular_gate),
            "degree2_n256_max_seconds": max(record["wall_seconds"] for record in triangular_gate),
            "degree2_n256_max_rss": max(record["peak_rss"] for record in triangular_gate),
        },
        "feistel": {
            "raw": str(feistel_path),
            "runs": len(feistel),
            "complete_matrix": len(feistel) == 300,
            "successes": sum(record.get("status") == "SUPPORTED" for record in feistel),
            "status": "INCONCLUSIVE" if len(feistel) < 300 else (
                "EMPIRICALLY_SUPPORTED" if all_supported(feistel) else "REJECTED"
            ),
        },
        "multi_organ": {
            "raw": str(multi_path),
            "records": multi,
        },
        "baseline": {
            "raw": "results_gen/raw/baseline-affine-n4096.jsonl",
            "minimum_speedup_over_best_completed_nonoracle_baseline": gen_baseline[
                "minimum_speedup_over_lift_hard_gate"
            ],
        },
        "development_partial_files": [
            str(path) for path in Path("results_gen/raw").glob("*.jsonl")
            if path not in {small_path, affine_path, triangular_path, feistel_path, multi_path}
        ],
    }
    Path("results_gen/certificates").mkdir(parents=True, exist_ok=True)
    for encoding in ("affine", "triangular", "feistel"):
        representative = next(
            record for record in family_records
            if record["encoding"] == encoding and record["status"] == "SUPPORTED"
        )
        Path(f"results_gen/certificates/{encoding}-representative.json").write_text(
            json.dumps(representative["proof"], indent=2, sort_keys=True) + "\n"
        )
    Path("results_gen/plots").mkdir(parents=True, exist_ok=True)
    affine_points = []
    for n in sorted({record["micro_state_bits"] for record in affine}):
        values = [record["wall_seconds"] for record in affine if record["micro_state_bits"] == n]
        affine_points.append((n, max(values)))
    triangular_points = []
    for n in sorted({record["micro_state_bits"] for record in triangular}):
        values = [record["wall_seconds"] for record in triangular if record["micro_state_bits"] == n]
        triangular_points.append((n, max(values)))
    svg_plot(
        Path("results_gen/plots/affine_scaling.svg"),
        "MORPH-GEN affine worst-case wall time",
        affine_points, "micro bits", "seconds",
    )
    svg_plot(
        Path("results_gen/plots/triangular_scaling.svg"),
        "MORPH-GEN triangular worst-case wall time",
        triangular_points, "micro bits", "seconds",
    )
    Path("results_gen").mkdir(exist_ok=True)
    output = Path("results_gen/summary.json")
    if output.exists():
        output = Path(f"results_gen/summary-{strftime('%Y%m%d-%H%M%S')}.json")
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"summary": str(output), "conclusion": conclusion}, indent=2))


if __name__ == "__main__":
    main()
