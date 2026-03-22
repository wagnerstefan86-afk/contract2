#!/usr/bin/env python3
"""Standalone clause validation runner.

Runs the golden testset through the risk_screen parser logic
(without LLM) and produces a full validation + calibration report.

Usage:
    python backend/tests/run_clause_validation.py

For LLM-integrated runs, use the pytest suite:
    python -m pytest backend/tests/test_validation_runner.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tests.validation.golden_loader import load_golden_cases, GoldenCase
from tests.validation.clause_validator import (
    ClauseScreenResult,
    validate_screen_result,
    build_summary,
    format_summary_text,
)
from tests.validation.theme_quality import (
    is_generic_theme,
    check_theme_quality,
)
from tests.validation.calibration import build_calibration_report


def _simulate_screen_result(case: GoldenCase) -> ClauseScreenResult:
    """Simulate a correct LLM response for validation purposes.

    This tests the validator framework, not the LLM.
    For real LLM validation, use the pytest integration tests.
    """
    if case.expected_problematic:
        return ClauseScreenResult(
            segment_id=f"val-{case.case_id}",
            segment_text=case.clause_text,
            is_problematic=True,
            problem_types=case.expected_problem_types,
            severity=case.expected_severity_min or "medium",
            reason=f"Simulated: {case.notes}",
            evidence_text=case.clause_text[:200],
            trigger_domains=case.expected_trigger_domains,
            needs_deep_check=len(case.expected_trigger_domains) > 0,
            deep_check_domains=case.expected_trigger_domains,
        )
    else:
        return ClauseScreenResult(
            segment_id=f"val-{case.case_id}",
            segment_text=case.clause_text,
            is_problematic=False,
        )


def main():
    print("Loading golden testset...")
    cases = load_golden_cases()
    print(f"  Loaded {len(cases)} cases ({sum(1 for c in cases if c.expected_problematic)} positive, "
          f"{sum(1 for c in cases if not c.expected_problematic)} negative)")
    print()

    # --- Run validation ---
    print("Running validation (simulated responses)...")
    results = []
    for case in cases:
        screen = _simulate_screen_result(case)
        cr = validate_screen_result(case, screen)
        results.append(cr)

    summary = build_summary(results)
    print(format_summary_text(summary))
    print()

    # --- Theme quality ---
    print("=" * 70)
    print("THEME QUALITY CHECK")
    print("=" * 70)

    # Simulate theme titles (in a real run these come from clustering)
    sample_titles = [
        "Einseitige Compliance-Anpassungspflichten ohne Kostengrenze",
        "Unklare Audit- und Nachweispflichten ohne Begrenzung",
        "Übertragung von BCM-Verantwortung auf den Dienstleister",
        "Unbegrenzte Haftungsdurchreichung für Subunternehmer",
        "Offener Leistungsumfang mit einseitigem Erweiterungsrecht",
        "Einseitiges Weisungs- und Änderungsrecht ohne Zumutbarkeitsgrenzen",
        "Unverhältnismäßige Exit- und Transitionspflichten",
        "Übermäßige Berichts- und Nachweispflichten ohne Vergütung",
    ]
    tq_report = check_theme_quality(sample_titles)
    print(f"  Total themes: {tq_report.total_themes}")
    print(f"  Generic count: {tq_report.generic_count}")
    print(f"  Generic rate: {tq_report.generic_rate:.0%}")
    print(f"  Passed: {tq_report.passed}")
    print(f"  Verdict: {tq_report.verdict}")
    for r in tq_report.results:
        status = "GENERIC" if r.is_generic else "OK"
        print(f"    [{status}] {r.title}")
        if r.reason:
            print(f"           → {r.reason}")
    print()

    # --- Calibration ---
    print("=" * 70)
    print("PIPELINE CALIBRATION REPORT")
    print("=" * 70)

    pos_count = sum(1 for c in cases if c.expected_problematic)
    neg_count = sum(1 for c in cases if not c.expected_problematic)
    deep_count = sum(
        1 for cr in results
        if cr.is_true_positive and cr.needs_deep_check
    )

    # Collect problem type and domain counts from results
    pt_counts: dict[str, int] = {}
    td_counts: dict[str, int] = {}
    for cr in results:
        if cr.is_true_positive:
            for pt in cr.detected_problem_types:
                pt_counts[pt] = pt_counts.get(pt, 0) + 1
            for td in cr.detected_trigger_domains:
                td_counts[td] = td_counts.get(td, 0) + 1

    cal_report = build_calibration_report(
        total_clauses_read=len(cases),
        clauses_flagged_problematic=pos_count,
        clauses_dropped_non_problematic=neg_count,
        deep_checks_run_total=deep_count,
        problems_after_dedup=pos_count,  # no dedup in simulation
        themes_before_editorial=tq_report.total_themes,
        themes_after_editorial=tq_report.total_themes - tq_report.generic_count,
        counts_by_problem_type=pt_counts,
        counts_by_trigger_domain=td_counts,
        generic_theme_count=tq_report.generic_count,
        total_themes=tq_report.total_themes,
    )

    print(f"  Overall: {cal_report.overall_verdict}")
    print(f"  Summary: {cal_report.summary}")
    print()
    for m in cal_report.metrics:
        print(f"  [{m.verdict}] {m.name}: {m.value} {m.unit}")
        print(f"    → {m.explanation}")
    print()

    # --- JSON export ---
    output = {
        "validation": summary.to_dict(),
        "theme_quality": {
            "total_themes": tq_report.total_themes,
            "generic_count": tq_report.generic_count,
            "generic_rate": tq_report.generic_rate,
            "passed": tq_report.passed,
            "verdict": tq_report.verdict,
        },
        "calibration": cal_report.to_dict(),
    }
    print("=" * 70)
    print("JSON EXPORT")
    print("=" * 70)
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
