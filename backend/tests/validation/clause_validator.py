"""Clause-level validation runner for the 2-stage pipeline.

Runs each golden testset case through the risk_screen stage (and optionally
deep_checks) and compares actual results against expected outcomes.

Can be used as:
- Pure unit test (no LLM, with mocked responses)
- Integration test (against real LLM)
- Standalone evaluation script
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.discovery.passes.risk_screen import (
    ClauseScreenResult,
    filter_problematic,
    _parse_screen_response,
    _default_non_problematic,
    PROBLEM_TYPES,
    DEEP_CHECK_DOMAINS,
)
from app.discovery.passes.deep_checks import (
    DeepCheckResult,
    merge_deep_checks_into_findings,
)
from app.discovery.chunking import Segment

from tests.validation.golden_loader import GoldenCase

# Severity ordering for comparison
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SEVERITY_GERMAN = {"low": "Niedrig", "medium": "Mittel", "high": "Hoch", "critical": "Kritisch"}


@dataclass
class CaseResult:
    """Result of validating one golden case."""
    case_id: str
    short_name: str
    expected_problematic: bool
    actual_problematic: bool
    # Classification
    is_true_positive: bool = False
    is_true_negative: bool = False
    is_false_positive: bool = False
    is_false_negative: bool = False
    # Details
    detected_problem_types: list[str] = field(default_factory=list)
    expected_problem_types: list[str] = field(default_factory=list)
    problem_type_overlap: float = 0.0
    detected_trigger_domains: list[str] = field(default_factory=list)
    expected_trigger_domains: list[str] = field(default_factory=list)
    trigger_domain_overlap: float = 0.0
    detected_severity: str = ""
    expected_severity_min: str = ""
    severity_ok: bool = True
    needs_deep_check: bool = False
    deep_check_domains: list[str] = field(default_factory=list)
    reason: str = ""
    evidence_text: str = ""
    notes: str = ""


@dataclass
class ValidationSummary:
    """Aggregate validation results across all golden cases."""
    total_cases: int = 0
    positive_cases: int = 0
    negative_cases: int = 0
    true_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0
    false_positives: int = 0
    # Rates
    recall: float = 0.0
    precision: float = 0.0
    noise_reduction_passed: bool = True
    # Coverage
    problem_type_coverage: dict[str, bool] = field(default_factory=dict)
    trigger_domain_coverage: dict[str, bool] = field(default_factory=dict)
    deep_check_escalation_rate: float = 0.0
    # Details
    false_negative_cases: list[str] = field(default_factory=list)
    false_positive_cases: list[str] = field(default_factory=list)
    case_results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_cases": self.total_cases,
            "positive_cases": self.positive_cases,
            "negative_cases": self.negative_cases,
            "true_positives": self.true_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "false_positives": self.false_positives,
            "recall": round(self.recall, 3),
            "precision": round(self.precision, 3),
            "noise_reduction_passed": self.noise_reduction_passed,
            "false_negative_cases": self.false_negative_cases,
            "false_positive_cases": self.false_positive_cases,
            "problem_type_coverage": self.problem_type_coverage,
            "trigger_domain_coverage": self.trigger_domain_coverage,
            "deep_check_escalation_rate": round(self.deep_check_escalation_rate, 3),
        }


def _case_to_segment(case: GoldenCase) -> Segment:
    """Convert a golden case to a Segment for pipeline consumption."""
    seg_id = f"val-{case.case_id}"
    return Segment(
        id=seg_id,
        text=case.clause_text,
        absatz_start=0,
        absatz_ende=0,
        fenster_text=case.clause_text,
    )


def validate_screen_result(
    case: GoldenCase,
    result: ClauseScreenResult,
) -> CaseResult:
    """Validate a single risk_screen result against the golden case expectation."""

    cr = CaseResult(
        case_id=case.case_id,
        short_name=case.short_name,
        expected_problematic=case.expected_problematic,
        actual_problematic=result.is_problematic,
        detected_problem_types=result.problem_types,
        expected_problem_types=case.expected_problem_types,
        detected_trigger_domains=result.trigger_domains,
        expected_trigger_domains=case.expected_trigger_domains,
        detected_severity=result.severity,
        expected_severity_min=case.expected_severity_min or "",
        needs_deep_check=result.needs_deep_check,
        deep_check_domains=result.deep_check_domains,
        reason=result.reason,
        evidence_text=result.evidence_text,
        notes=case.notes,
    )

    # Classification
    if case.expected_problematic and result.is_problematic:
        cr.is_true_positive = True
    elif case.expected_problematic and not result.is_problematic:
        cr.is_false_negative = True
    elif not case.expected_problematic and not result.is_problematic:
        cr.is_true_negative = True
    elif not case.expected_problematic and result.is_problematic:
        cr.is_false_positive = True

    # Problem type overlap
    if case.expected_problem_types and result.problem_types:
        expected_set = set(case.expected_problem_types)
        actual_set = set(result.problem_types)
        overlap = len(expected_set & actual_set)
        cr.problem_type_overlap = overlap / len(expected_set) if expected_set else 0.0

    # Trigger domain overlap
    if case.expected_trigger_domains and result.trigger_domains:
        expected_set = set(case.expected_trigger_domains)
        actual_set = set(result.trigger_domains)
        overlap = len(expected_set & actual_set)
        cr.trigger_domain_overlap = overlap / len(expected_set) if expected_set else 0.0

    # Severity check
    if case.expected_severity_min and result.severity:
        expected_rank = SEVERITY_ORDER.get(case.expected_severity_min, 0)
        actual_rank = SEVERITY_ORDER.get(result.severity, 0)
        cr.severity_ok = actual_rank >= expected_rank

    return cr


def build_summary(results: list[CaseResult]) -> ValidationSummary:
    """Build aggregate summary from individual case results."""

    summary = ValidationSummary(
        total_cases=len(results),
        case_results=results,
    )

    for r in results:
        if r.expected_problematic:
            summary.positive_cases += 1
        else:
            summary.negative_cases += 1

        if r.is_true_positive:
            summary.true_positives += 1
        elif r.is_false_negative:
            summary.false_negatives += 1
            summary.false_negative_cases.append(r.case_id)
        elif r.is_true_negative:
            summary.true_negatives += 1
        elif r.is_false_positive:
            summary.false_positives += 1
            summary.false_positive_cases.append(r.case_id)

    # Recall
    if summary.positive_cases > 0:
        summary.recall = summary.true_positives / summary.positive_cases

    # Precision
    detected_positive = summary.true_positives + summary.false_positives
    if detected_positive > 0:
        summary.precision = summary.true_positives / detected_positive

    # Noise reduction: passes if zero false positives
    summary.noise_reduction_passed = summary.false_positives == 0

    # Problem type coverage (across true positives only)
    all_expected_types: set[str] = set()
    all_detected_types: set[str] = set()
    for r in results:
        if r.is_true_positive:
            all_expected_types.update(r.expected_problem_types)
            all_detected_types.update(r.detected_problem_types)

    for pt in all_expected_types:
        summary.problem_type_coverage[pt] = pt in all_detected_types

    # Trigger domain coverage
    all_expected_domains: set[str] = set()
    all_detected_domains: set[str] = set()
    for r in results:
        if r.is_true_positive:
            all_expected_domains.update(r.expected_trigger_domains)
            all_detected_domains.update(r.detected_trigger_domains)

    for td in all_expected_domains:
        summary.trigger_domain_coverage[td] = td in all_detected_domains

    # Deep-check escalation rate
    tp_count = summary.true_positives
    deep_count = sum(1 for r in results if r.is_true_positive and r.needs_deep_check)
    if tp_count > 0:
        summary.deep_check_escalation_rate = deep_count / tp_count

    return summary


def format_summary_text(summary: ValidationSummary) -> str:
    """Format the validation summary as human-readable text."""
    lines = []
    lines.append("=" * 70)
    lines.append("PIPELINE VALIDATION SUMMARY")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Total cases:           {summary.total_cases}")
    lines.append(f"  Positive (must-detect): {summary.positive_cases}")
    lines.append(f"  Negative (must-drop):   {summary.negative_cases}")
    lines.append("")
    lines.append("--- Classification ---")
    lines.append(f"  True Positives:   {summary.true_positives}")
    lines.append(f"  True Negatives:   {summary.true_negatives}")
    lines.append(f"  False Negatives:  {summary.false_negatives}")
    lines.append(f"  False Positives:  {summary.false_positives}")
    lines.append("")
    lines.append(f"  RECALL:    {summary.recall:.1%}")
    lines.append(f"  PRECISION: {summary.precision:.1%}")
    lines.append(f"  Noise reduction passed: {summary.noise_reduction_passed}")
    lines.append("")

    if summary.false_negative_cases:
        lines.append("--- FALSE NEGATIVES (missed must-detect clauses) ---")
        for case_id in summary.false_negative_cases:
            cr = next(r for r in summary.case_results if r.case_id == case_id)
            lines.append(f"  {case_id}: {cr.short_name}")
            lines.append(f"    Expected types: {cr.expected_problem_types}")
            lines.append(f"    Notes: {cr.notes}")
        lines.append("")

    if summary.false_positive_cases:
        lines.append("--- FALSE POSITIVES (wrongly flagged neutral clauses) ---")
        for case_id in summary.false_positive_cases:
            cr = next(r for r in summary.case_results if r.case_id == case_id)
            lines.append(f"  {case_id}: {cr.short_name}")
            lines.append(f"    Detected types: {cr.detected_problem_types}")
            lines.append(f"    Reason: {cr.reason}")
        lines.append("")

    # Problem type coverage
    lines.append("--- Problem Type Coverage ---")
    for pt, covered in sorted(summary.problem_type_coverage.items()):
        status = "COVERED" if covered else "MISSING"
        lines.append(f"  [{status}] {pt}")
    lines.append("")

    # Trigger domain coverage
    lines.append("--- Trigger Domain Coverage ---")
    for td, covered in sorted(summary.trigger_domain_coverage.items()):
        status = "COVERED" if covered else "MISSING"
        lines.append(f"  [{status}] {td}")
    lines.append("")

    lines.append(f"Deep-check escalation rate: {summary.deep_check_escalation_rate:.0%}")
    lines.append("=" * 70)

    return "\n".join(lines)
