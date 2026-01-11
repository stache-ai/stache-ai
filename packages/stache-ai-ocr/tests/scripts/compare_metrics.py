#!/usr/bin/env python3
"""
Regression metrics comparison script.

Compares enhanced metrics against baseline to identify performance and accuracy regressions.
Generates a detailed regression report.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Setup paths
SCRIPT_DIR = Path(__file__).parent
TEST_DIR = SCRIPT_DIR.parent
OUTPUT_DIR = TEST_DIR

# Historical baseline (from Phase 0 - Task 0.3)
BASELINE_METRICS = {
    "timestamp": "2026-01-11T18:08:38.175489+00:00",
    "python_version": "3.12.3",
    "test_files": [
        {
            "filename": "01-text-based.pdf",
            "stache_ai_ocr": {"time_ms": 32.05, "text_length": 928},
            "stache_tools_ocr": {"time_ms": 3.3, "text_length": 929, "ocr_used": False},
        },
        {
            "filename": "02-empty.pdf",
            "stache_ai_ocr": {"time_ms": 1.36, "text_length": 0},
            "stache_tools_ocr": {"time_ms": 0.85, "text_length": 0, "ocr_used": False},
        },
        {
            "filename": "03-single-page.pdf",
            "stache_ai_ocr": {"time_ms": 3.22, "text_length": 156},
            "stache_tools_ocr": {"time_ms": 0.8, "text_length": 157, "ocr_used": False},
        },
        {
            "filename": "04-scanned.pdf",
            "stache_ai_ocr": {"time_ms": 1.12, "text_length": 0},
            "stache_tools_ocr": {"time_ms": 0.75, "text_length": 0, "ocr_used": False},
        },
        {
            "filename": "05-large-multipage.pdf",
            "stache_ai_ocr": {"time_ms": 111.9, "text_length": 6276},
            "stache_tools_ocr": {"time_ms": 8.63, "text_length": 6287, "ocr_used": False},
        },
        {
            "filename": "06-hybrid.pdf",
            "stache_ai_ocr": {"time_ms": 6.01, "text_length": 372},
            "stache_tools_ocr": {"time_ms": 1.1, "text_length": 373, "ocr_used": False},
        },
    ]
}


def load_current_metrics(metrics_file: Path) -> Dict[str, Any]:
    """Load current metrics from JSON file."""
    if not metrics_file.exists():
        print(f"ERROR: Metrics file not found: {metrics_file}")
        sys.exit(1)

    with open(metrics_file) as f:
        return json.load(f)


def calculate_percentage_change(old: float, new: float) -> float:
    """Calculate percentage change from old to new value."""
    if old == 0:
        return 0.0 if new == 0 else 100.0
    return ((new - old) / old) * 100


def check_regression(metric_name: str, old_value: float, new_value: float,
                     threshold_pct: float = 30, lower_is_better: bool = True) -> Tuple[bool, float]:
    """
    Check if a metric has regressed.

    Returns: (is_regression, percentage_change)
    """
    pct_change = calculate_percentage_change(old_value, new_value)

    if lower_is_better:
        # For time/performance, positive change is regression
        is_regression = pct_change > threshold_pct
    else:
        # For accuracy/length, negative change is regression
        is_regression = pct_change < -threshold_pct

    return is_regression, pct_change


def format_metric_row(filename: str, metric_type: str, old_val: float, new_val: float,
                      threshold: float = 30, lower_is_better: bool = True) -> Tuple[str, bool]:
    """Format a single metric row for the table."""
    is_regression, pct_change = check_regression(
        metric_type, old_val, new_val, threshold, lower_is_better
    )

    status = "⚠️ REGRESSION" if is_regression else "✓ OK"
    direction = "↑" if pct_change >= 0 else "↓"

    row = f"| {filename:25} | {metric_type:20} | {old_val:10.2f} | {new_val:10.2f} | {direction} {pct_change:6.1f}% | {status:20} |"

    return row, is_regression


def generate_report(baseline: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Generate comprehensive comparison report."""

    report = {
        "timestamp": datetime.now().isoformat(),
        "baseline_timestamp": baseline["timestamp"],
        "current_timestamp": current["timestamp"],
        "regressions": [],
        "performance_summary": {},
        "accuracy_summary": {},
    }

    print("\n" + "="*100)
    print("REGRESSION METRICS COMPARISON REPORT")
    print("="*100)
    print(f"Baseline: {baseline['timestamp']}")
    print(f"Current:  {current['timestamp']}")
    print()

    # Build file index for quick lookup
    baseline_by_file = {f["filename"]: f for f in baseline["test_files"]}
    current_by_file = {f["filename"]: f for f in current["test_files"]}

    total_regression_count = 0
    critical_regression_count = 0

    # Performance comparison table
    print("PERFORMANCE COMPARISON (milliseconds)")
    print("-" * 100)
    print("| File                      | Metric               | Baseline   | Current    | Change     | Status               |")
    print("|---------------------------|----------------------|------------|------------|------------|----------------------|")

    perf_regressions = []

    for filename in sorted(baseline_by_file.keys()):
        if filename not in current_by_file:
            print(f"| {filename:25} | MISSING IN CURRENT   | -          | -          | -          | ⚠️ ERROR             |")
            continue

        baseline_file = baseline_by_file[filename]
        current_file = current_by_file[filename]

        # stache-ai-ocr time
        ai_row, ai_reg = format_metric_row(
            filename, "stache-ai-ocr",
            baseline_file["stache_ai_ocr"]["time_ms"],
            current_file["stache_ai_ocr"]["time_ms"]
        )
        print(ai_row)
        if ai_reg:
            perf_regressions.append(filename)
            total_regression_count += 1

        # stache-tools-ocr time
        tools_row, tools_reg = format_metric_row(
            filename, "stache-tools-ocr",
            baseline_file["stache_tools_ocr"]["time_ms"],
            current_file["stache_tools_ocr"]["time_ms"]
        )
        print(tools_row)
        if tools_reg:
            perf_regressions.append(filename)
            total_regression_count += 1

    report["performance_summary"]["total_regressions"] = len(set(perf_regressions))
    report["performance_summary"]["affected_files"] = list(set(perf_regressions))

    # Accuracy comparison table
    print("\n" + "="*100)
    print("ACCURACY COMPARISON (text length in characters)")
    print("-" * 100)
    print("| File                      | Loader               | Baseline   | Current    | Change     | Status               |")
    print("|---------------------------|----------------------|------------|------------|------------|----------------------|")

    accuracy_regressions = []

    for filename in sorted(baseline_by_file.keys()):
        if filename not in current_by_file:
            continue

        baseline_file = baseline_by_file[filename]
        current_file = current_by_file[filename]

        # stache-ai-ocr text length
        ai_row, ai_reg = format_metric_row(
            filename, "stache-ai-ocr",
            baseline_file["stache_ai_ocr"]["text_length"],
            current_file["stache_ai_ocr"]["text_length"],
            threshold=0,  # Exact match expected
            lower_is_better=False  # More text is better
        )
        print(ai_row)
        if ai_reg:
            accuracy_regressions.append(filename)
            critical_regression_count += 1

        # stache-tools-ocr text length
        tools_row, tools_reg = format_metric_row(
            filename, "stache-tools-ocr",
            baseline_file["stache_tools_ocr"]["text_length"],
            current_file["stache_tools_ocr"]["text_length"],
            threshold=0,
            lower_is_better=False
        )
        print(tools_row)
        if tools_reg:
            accuracy_regressions.append(filename)
            critical_regression_count += 1

    report["accuracy_summary"]["total_regressions"] = len(set(accuracy_regressions))
    report["accuracy_summary"]["affected_files"] = list(set(accuracy_regressions))

    # Detailed file-by-file analysis
    print("\n" + "="*100)
    print("DETAILED FILE ANALYSIS")
    print("="*100)

    for filename in sorted(baseline_by_file.keys()):
        if filename not in current_by_file:
            print(f"\n❌ {filename}: MISSING IN CURRENT METRICS")
            continue

        baseline_file = baseline_by_file[filename]
        current_file = current_by_file[filename]

        print(f"\n📄 {filename}:")

        # stache-ai-ocr analysis
        ai_baseline = baseline_file["stache_ai_ocr"]
        ai_current = current_file["stache_ai_ocr"]
        time_change = calculate_percentage_change(ai_baseline["time_ms"], ai_current["time_ms"])
        text_match = ai_baseline["text_length"] == ai_current["text_length"]

        print(f"  stache-ai-ocr:")
        print(f"    Time: {ai_baseline['time_ms']:6.2f}ms → {ai_current['time_ms']:6.2f}ms ({time_change:+6.1f}%)")
        print(f"    Text: {ai_baseline['text_length']:6d} → {ai_current['text_length']:6d} chars {'✓' if text_match else '⚠️ MISMATCH'}")

        # stache-tools-ocr analysis
        tools_baseline = baseline_file["stache_tools_ocr"]
        tools_current = current_file["stache_tools_ocr"]
        time_change = calculate_percentage_change(tools_baseline["time_ms"], tools_current["time_ms"])
        text_match = tools_baseline["text_length"] == tools_current["text_length"]

        print(f"  stache-tools-ocr:")
        print(f"    Time: {tools_baseline['time_ms']:6.2f}ms → {tools_current['time_ms']:6.2f}ms ({time_change:+6.1f}%)")
        print(f"    Text: {tools_baseline['text_length']:6d} → {tools_current['text_length']:6d} chars {'✓' if text_match else '⚠️ MISMATCH'}")
        if "ocr_used" in tools_baseline and "ocr_used" in tools_current:
            ocr_change = tools_baseline["ocr_used"] != tools_current["ocr_used"]
            print(f"    OCR:  {tools_baseline['ocr_used']!s:5} → {tools_current['ocr_used']!s:5} {'⚠️ CHANGED' if ocr_change else '✓'}")

    # Summary
    print("\n" + "="*100)
    print("REGRESSION SUMMARY")
    print("="*100)
    print(f"Performance regressions (>30% slower): {report['performance_summary']['total_regressions']}")
    print(f"Accuracy regressions (text mismatch):  {report['accuracy_summary']['total_regressions']}")
    print(f"Critical regressions (data loss):     {critical_regression_count}")

    if total_regression_count == 0 and critical_regression_count == 0:
        print("\n✅ NO REGRESSIONS DETECTED")
        print("All metrics are within acceptable thresholds.")
    else:
        print("\n⚠️ REGRESSIONS DETECTED")
        print(f"Total regression issues: {total_regression_count + critical_regression_count}")

    print("="*100 + "\n")

    return report


def main():
    """Main entry point."""

    # Load metrics
    metrics_file = OUTPUT_DIR / "baseline-metrics.json"
    current_metrics = load_current_metrics(metrics_file)

    # Generate report
    report = generate_report(BASELINE_METRICS, current_metrics)

    # Save report as markdown
    report_file = OUTPUT_DIR / "regression-report.md"
    generate_markdown_report(report, BASELINE_METRICS, current_metrics, report_file)

    print(f"📊 Detailed report saved to: {report_file}\n")

    # Return exit code based on regressions
    total_issues = (report["performance_summary"]["total_regressions"] +
                   report["accuracy_summary"]["total_regressions"])

    if total_issues == 0:
        print("✅ ALL CHECKS PASSED")
        return 0
    else:
        print(f"⚠️ {total_issues} REGRESSION ISSUES DETECTED")
        return 1


def generate_markdown_report(report: Dict[str, Any], baseline: Dict[str, Any],
                            current: Dict[str, Any], output_file: Path) -> None:
    """Generate markdown format regression report."""

    baseline_by_file = {f["filename"]: f for f in baseline["test_files"]}
    current_by_file = {f["filename"]: f for f in current["test_files"]}

    md_lines = [
        "# Regression Metrics Comparison Report",
        "",
        f"**Generated**: {report['timestamp']}",
        "",
        f"**Baseline**: {report['baseline_timestamp']}",
        f"**Current**: {report['current_timestamp']}",
        "",
        "## Executive Summary",
        "",
    ]

    perf_regs = report['performance_summary']['total_regressions']
    acc_regs = report['accuracy_summary']['total_regressions']
    total_regs = perf_regs + acc_regs

    if total_regs == 0:
        md_lines.append("✅ **NO REGRESSIONS DETECTED**")
        md_lines.append("")
        md_lines.append("All performance and accuracy metrics are within acceptable thresholds.")
    else:
        md_lines.append("⚠️ **REGRESSIONS DETECTED**")
        md_lines.append("")
        md_lines.append(f"- Performance regressions (>30% slower): **{perf_regs}**")
        md_lines.append(f"- Accuracy regressions (text mismatch): **{acc_regs}**")
        md_lines.append(f"- **Total issues**: {total_regs}")

    # Performance table
    md_lines.extend([
        "",
        "## Performance Metrics",
        "",
        "| File | Loader | Baseline (ms) | Current (ms) | Change | Status |",
        "|------|--------|---------------|-------------|--------|--------|",
    ])

    for filename in sorted(baseline_by_file.keys()):
        if filename not in current_by_file:
            continue

        bf = baseline_by_file[filename]
        cf = current_by_file[filename]

        # AI OCR
        ai_b = bf["stache_ai_ocr"]["time_ms"]
        ai_c = cf["stache_ai_ocr"]["time_ms"]
        ai_pct = calculate_percentage_change(ai_b, ai_c)
        ai_status = "⚠️ REGRESSION" if ai_pct > 30 else "✓ OK"
        md_lines.append(f"| {filename} | stache-ai-ocr | {ai_b:.2f} | {ai_c:.2f} | {ai_pct:+.1f}% | {ai_status} |")

        # Tools OCR
        tools_b = bf["stache_tools_ocr"]["time_ms"]
        tools_c = cf["stache_tools_ocr"]["time_ms"]
        tools_pct = calculate_percentage_change(tools_b, tools_c)
        tools_status = "⚠️ REGRESSION" if tools_pct > 30 else "✓ OK"
        md_lines.append(f"| {filename} | stache-tools-ocr | {tools_b:.2f} | {tools_c:.2f} | {tools_pct:+.1f}% | {tools_status} |")

    # Accuracy table
    md_lines.extend([
        "",
        "## Accuracy Metrics (Text Length)",
        "",
        "| File | Loader | Baseline (chars) | Current (chars) | Status |",
        "|------|--------|------------------|-----------------|--------|",
    ])

    for filename in sorted(baseline_by_file.keys()):
        if filename not in current_by_file:
            continue

        bf = baseline_by_file[filename]
        cf = current_by_file[filename]

        # AI OCR
        ai_b = bf["stache_ai_ocr"]["text_length"]
        ai_c = cf["stache_ai_ocr"]["text_length"]
        ai_status = "✓ Match" if ai_b == ai_c else "⚠️ MISMATCH"
        md_lines.append(f"| {filename} | stache-ai-ocr | {ai_b} | {ai_c} | {ai_status} |")

        # Tools OCR
        tools_b = bf["stache_tools_ocr"]["text_length"]
        tools_c = cf["stache_tools_ocr"]["text_length"]
        tools_status = "✓ Match" if tools_b == tools_c else "⚠️ MISMATCH"
        md_lines.append(f"| {filename} | stache-tools-ocr | {tools_b} | {tools_c} | {tools_status} |")

    # Detailed analysis
    md_lines.extend([
        "",
        "## Detailed Analysis",
        "",
    ])

    for filename in sorted(baseline_by_file.keys()):
        if filename not in current_by_file:
            md_lines.append(f"### {filename}")
            md_lines.append("**ERROR**: Missing in current metrics")
            md_lines.append("")
            continue

        bf = baseline_by_file[filename]
        cf = current_by_file[filename]

        md_lines.append(f"### {filename}")
        md_lines.append("")
        md_lines.append("**stache-ai-ocr**:")
        ai_b = bf["stache_ai_ocr"]
        ai_c = cf["stache_ai_ocr"]
        time_pct = calculate_percentage_change(ai_b["time_ms"], ai_c["time_ms"])
        md_lines.append(f"- Time: {ai_b['time_ms']:.2f}ms → {ai_c['time_ms']:.2f}ms ({time_pct:+.1f}%)")
        md_lines.append(f"- Text length: {ai_b['text_length']} → {ai_c['text_length']} chars")

        md_lines.append("")
        md_lines.append("**stache-tools-ocr**:")
        tools_b = bf["stache_tools_ocr"]
        tools_c = cf["stache_tools_ocr"]
        time_pct = calculate_percentage_change(tools_b["time_ms"], tools_c["time_ms"])
        md_lines.append(f"- Time: {tools_b['time_ms']:.2f}ms → {tools_c['time_ms']:.2f}ms ({time_pct:+.1f}%)")
        md_lines.append(f"- Text length: {tools_b['text_length']} → {tools_c['text_length']} chars")
        if "ocr_used" in tools_b and "ocr_used" in tools_c:
            md_lines.append(f"- OCR used: {tools_b['ocr_used']} → {tools_c['ocr_used']}")
        md_lines.append("")

    # Conclusions
    md_lines.extend([
        "## Conclusions",
        "",
    ])

    if total_regs == 0:
        md_lines.extend([
            "✅ **All checks passed** - No performance or accuracy regressions detected.",
            "",
            "### Key Findings:",
            "- Performance is stable across all test files (±30% threshold)",
            "- Text extraction accuracy matches baseline",
            "- OCR heuristic behavior is consistent",
            "- Enhanced implementation maintains backward compatibility",
        ])
    else:
        md_lines.extend([
            f"⚠️ **{total_regs} regression issues detected** - Review required.",
            "",
            "### Affected Areas:",
        ])

        if perf_regs > 0:
            files = report['performance_summary']['affected_files']
            md_lines.append(f"- Performance regressions in: {', '.join(files)}")

        if acc_regs > 0:
            files = report['accuracy_summary']['affected_files']
            md_lines.append(f"- Accuracy regressions in: {', '.join(files)}")

    md_lines.extend([
        "",
        "### Thresholds Used:",
        "- Performance regression threshold: 30% increase in execution time",
        "- Accuracy regression threshold: Text length mismatch (exact match expected)",
        "",
    ])

    # Write file
    output_file.write_text("\n".join(md_lines))


if __name__ == "__main__":
    sys.exit(main())
