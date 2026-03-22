"""Pytest-based validation runner for the 2-stage pipeline.

Runs golden testset cases through the risk_screen parser (unit-level)
and through mock LLM responses to validate classification logic.

These tests do NOT call the actual LLM — they test the pipeline's
classification/parsing/filtering logic with controlled inputs.
"""

from __future__ import annotations

import json
import pytest

from app.discovery.passes.risk_screen import (
    ClauseScreenResult,
    filter_problematic,
    _parse_screen_response,
    _default_non_problematic,
    _problem_type_to_category,
    PROBLEM_TYPES,
    DEEP_CHECK_DOMAINS,
)
from app.discovery.passes.deep_checks import (
    DeepCheckResult,
    merge_deep_checks_into_findings,
    _parse_deep_check,
)
from app.discovery.chunking import Segment

from tests.validation.golden_loader import (
    load_golden_cases, positive_cases, negative_cases, GoldenCase,
)
from tests.validation.clause_validator import (
    _case_to_segment,
    validate_screen_result,
    build_summary,
    format_summary_text,
    CaseResult,
    ValidationSummary,
)
from tests.validation.theme_quality import (
    is_generic_theme,
    check_theme_quality,
)
from tests.validation.calibration import (
    build_calibration_report,
)


# ───────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────

@pytest.fixture
def golden_cases():
    return load_golden_cases()


@pytest.fixture
def golden_positive(golden_cases):
    return [c for c in golden_cases if c.expected_problematic]


@pytest.fixture
def golden_negative(golden_cases):
    return [c for c in golden_cases if not c.expected_problematic]


def _make_screen_result_for_positive(case: GoldenCase) -> ClauseScreenResult:
    """Simulate a correct LLM response for a positive case."""
    return ClauseScreenResult(
        segment_id=f"val-{case.case_id}",
        segment_text=case.clause_text,
        is_problematic=True,
        problem_types=case.expected_problem_types,
        severity=case.expected_severity_min or "medium",
        reason=f"Simulated reason for {case.case_id}",
        evidence_text=case.clause_text[:200],
        trigger_domains=case.expected_trigger_domains,
        needs_deep_check=len(case.expected_trigger_domains) > 0,
        deep_check_domains=case.expected_trigger_domains,
    )


def _make_screen_result_for_negative(case: GoldenCase) -> ClauseScreenResult:
    """Simulate a correct LLM response for a negative case."""
    return ClauseScreenResult(
        segment_id=f"val-{case.case_id}",
        segment_text=case.clause_text,
        is_problematic=False,
    )


# ───────────────────────────────────────────────────────────────────
# Test: Golden testset loads correctly
# ───────────────────────────────────────────────────────────────────

class TestGoldenTestsetIntegrity:
    def test_cases_load(self, golden_cases):
        assert len(golden_cases) >= 20, f"Expected ≥20 cases, got {len(golden_cases)}"

    def test_positive_cases_exist(self, golden_positive):
        assert len(golden_positive) >= 12, f"Expected ≥12 positive cases, got {len(golden_positive)}"

    def test_negative_cases_exist(self, golden_negative):
        assert len(golden_negative) >= 6, f"Expected ≥6 negative cases, got {len(golden_negative)}"

    def test_case_ids_unique(self, golden_cases):
        ids = [c.case_id for c in golden_cases]
        assert len(ids) == len(set(ids)), "Duplicate case IDs found"

    def test_positive_cases_have_expected_types(self, golden_positive):
        for case in golden_positive:
            assert len(case.expected_problem_types) > 0, (
                f"Positive case {case.case_id} has no expected_problem_types"
            )

    def test_positive_cases_have_valid_types(self, golden_positive):
        for case in golden_positive:
            for pt in case.expected_problem_types:
                assert pt in PROBLEM_TYPES, (
                    f"Case {case.case_id}: unknown problem_type '{pt}'"
                )

    def test_positive_cases_have_valid_domains(self, golden_positive):
        for case in golden_positive:
            for td in case.expected_trigger_domains:
                assert td in DEEP_CHECK_DOMAINS, (
                    f"Case {case.case_id}: unknown trigger_domain '{td}'"
                )

    def test_clause_texts_nonempty(self, golden_cases):
        for case in golden_cases:
            assert len(case.clause_text.strip()) > 20, (
                f"Case {case.case_id} has too-short clause_text"
            )


# ───────────────────────────────────────────────────────────────────
# Test: Problem type coverage in golden set
# ───────────────────────────────────────────────────────────────────

class TestProblemTypeCoverage:
    """Verify that the golden set covers the most important problem types."""

    MUST_COVER = [
        "regulatory_shift",
        "bcm_transfer",
        "unclear_audit",
        "excessive_reporting",
        "unbalanced_liability",
        "subcontractor_liability",
        "open_scope",
        "one_sided_rights",
        "exit_or_transition_burden",
        "unreasonable_response_or_restore_commitment",
    ]

    def test_all_critical_types_covered(self, golden_positive):
        all_types = set()
        for case in golden_positive:
            all_types.update(case.expected_problem_types)

        for pt in self.MUST_COVER:
            assert pt in all_types, (
                f"Critical problem type '{pt}' not covered by any golden case"
            )


# ───────────────────────────────────────────────────────────────────
# Test: Validator logic with simulated results
# ───────────────────────────────────────────────────────────────────

class TestValidatorLogicSimulated:
    """Test the validator with simulated perfect LLM responses."""

    def test_perfect_positive_detection(self, golden_positive):
        """All positive cases detected → recall = 1.0"""
        results = []
        for case in golden_positive:
            screen = _make_screen_result_for_positive(case)
            cr = validate_screen_result(case, screen)
            results.append(cr)

        summary = build_summary(results)
        assert summary.recall == 1.0
        assert summary.false_negatives == 0

    def test_perfect_negative_rejection(self, golden_negative):
        """All negative cases correctly dropped → zero false positives"""
        results = []
        for case in golden_negative:
            screen = _make_screen_result_for_negative(case)
            cr = validate_screen_result(case, screen)
            results.append(cr)

        summary = build_summary(results)
        assert summary.false_positives == 0
        assert summary.noise_reduction_passed is True

    def test_full_golden_set_perfect(self, golden_cases):
        """Full golden set with perfect responses → recall=1.0, precision=1.0"""
        results = []
        for case in golden_cases:
            if case.expected_problematic:
                screen = _make_screen_result_for_positive(case)
            else:
                screen = _make_screen_result_for_negative(case)
            results.append(validate_screen_result(case, screen))

        summary = build_summary(results)
        assert summary.recall == 1.0
        assert summary.precision == 1.0
        assert summary.noise_reduction_passed is True

    def test_one_false_negative_lowers_recall(self, golden_positive):
        """Missing one positive case should lower recall."""
        results = []
        for i, case in enumerate(golden_positive):
            if i == 0:
                # Simulate FN: model says non-problematic
                screen = _make_screen_result_for_negative(case)
            else:
                screen = _make_screen_result_for_positive(case)
            results.append(validate_screen_result(case, screen))

        summary = build_summary(results)
        assert summary.false_negatives == 1
        assert summary.recall < 1.0
        assert golden_positive[0].case_id in summary.false_negative_cases

    def test_one_false_positive_fails_noise(self, golden_negative):
        """One false positive should fail noise reduction."""
        results = []
        for i, case in enumerate(golden_negative):
            if i == 0:
                # Simulate FP: model wrongly flags as problematic
                screen = ClauseScreenResult(
                    segment_id=f"val-{case.case_id}",
                    segment_text=case.clause_text,
                    is_problematic=True,
                    problem_types=["undefined_terms"],
                    severity="low",
                    reason="False positive simulation",
                )
            else:
                screen = _make_screen_result_for_negative(case)
            results.append(validate_screen_result(case, screen))

        summary = build_summary(results)
        assert summary.false_positives == 1
        assert summary.noise_reduction_passed is False


# ───────────────────────────────────────────────────────────────────
# Test: Summary formatting
# ───────────────────────────────────────────────────────────────────

class TestSummaryFormatting:
    def test_format_produces_text(self, golden_cases):
        results = []
        for case in golden_cases:
            if case.expected_problematic:
                screen = _make_screen_result_for_positive(case)
            else:
                screen = _make_screen_result_for_negative(case)
            results.append(validate_screen_result(case, screen))

        summary = build_summary(results)
        text = format_summary_text(summary)
        assert "RECALL" in text
        assert "PRECISION" in text
        assert "True Positives" in text

    def test_summary_to_dict(self, golden_cases):
        results = []
        for case in golden_cases:
            if case.expected_problematic:
                screen = _make_screen_result_for_positive(case)
            else:
                screen = _make_screen_result_for_negative(case)
            results.append(validate_screen_result(case, screen))

        summary = build_summary(results)
        d = summary.to_dict()
        assert "recall" in d
        assert "precision" in d
        assert "false_negative_cases" in d
        assert isinstance(d["recall"], float)


# ───────────────────────────────────────────────────────────────────
# Test: Parse screen response with golden case texts
# ───────────────────────────────────────────────────────────────────

class TestParseScreenWithGoldenCases:
    """Test _parse_screen_response with realistic LLM outputs for golden cases."""

    def test_parse_problematic_json(self):
        seg = Segment(id="val-P01", text="test", absatz_start=0, absatz_ende=0, fenster_text="test")
        json_str = json.dumps({
            "is_problematic": True,
            "problem_types": ["regulatory_shift"],
            "severity": "high",
            "reason": "Regulatorische Verlagerung.",
            "evidence_text": "test",
            "trigger_domains": ["regulatory"],
            "needs_deep_check": True,
            "deep_check_domains": ["regulatory"],
        })
        result = _parse_screen_response(json_str, seg)
        assert result.is_problematic is True
        assert "regulatory_shift" in result.problem_types

    def test_parse_non_problematic_json(self):
        seg = Segment(id="val-N01", text="test", absatz_start=0, absatz_ende=0, fenster_text="test")
        result = _parse_screen_response('{"is_problematic": false}', seg)
        assert result.is_problematic is False

    def test_parse_garbage_returns_non_problematic(self):
        seg = Segment(id="val-X01", text="test", absatz_start=0, absatz_ende=0, fenster_text="test")
        result = _parse_screen_response("This is not JSON at all", seg)
        assert result.is_problematic is False


# ───────────────────────────────────────────────────────────────────
# Test: Theme quality checks
# ───────────────────────────────────────────────────────────────────

class TestThemeQuality:
    """Theme genericness detection."""

    def test_generic_single_words(self):
        assert is_generic_theme("Compliance") is True
        assert is_generic_theme("Audit") is True
        assert is_generic_theme("BCM") is True
        assert is_generic_theme("Haftung") is True
        assert is_generic_theme("Informationssicherheit") is True
        assert is_generic_theme("Exit") is True

    def test_generic_two_word_titles(self):
        assert is_generic_theme("Allgemeine Haftung") is True
        assert is_generic_theme("Die Compliance") is True

    def test_specific_titles_pass(self):
        assert is_generic_theme("Einseitige Compliance-Anpassungspflichten ohne Kostengrenze") is False
        assert is_generic_theme("Unklare Audit- und Nachweispflichten ohne Begrenzung") is False
        assert is_generic_theme("Übertragung von BCM-Verantwortung auf den Dienstleister") is False
        assert is_generic_theme("Unbegrenzte Haftungsdurchreichung für Subunternehmer") is False
        assert is_generic_theme("Dynamische regulatorische Anpassungspflichten ohne Kostenregelung") is False

    def test_short_without_risk_word_is_generic(self):
        assert is_generic_theme("Haftung und Pflichten") is True
        assert is_generic_theme("Audit und Kontrolle") is True

    def test_short_with_risk_word_passes(self):
        assert is_generic_theme("Unbegrenzte Haftung ohne Deckelung") is False
        assert is_generic_theme("Einseitige Audit-Rechte ohne Begrenzung") is False
        # "Einseitige Audit-Rechte" (2 tokens after split) is too short — correctly generic

    def test_check_theme_quality_report(self):
        titles = [
            "Einseitige Compliance-Anpassungspflichten ohne Kostengrenze",
            "Compliance",
            "Unklare Audit- und Nachweispflichten ohne Begrenzung",
            "Übertragung von BCM-Verantwortung auf den Dienstleister",
            "Unbegrenzte Haftungsdurchreichung für Subunternehmer",
        ]
        report = check_theme_quality(titles)
        assert report.total_themes == 5
        assert report.generic_count == 1  # "Compliance"
        assert report.generic_rate == 0.2
        assert report.passed is True  # 20% is at threshold

    def test_all_generic_fails(self):
        titles = ["Compliance", "Audit", "BCM", "Haftung"]
        report = check_theme_quality(titles)
        assert report.passed is False
        assert report.generic_rate == 1.0
        assert "FAILING" in report.verdict


# ───────────────────────────────────────────────────────────────────
# Test: Calibration metrics
# ───────────────────────────────────────────────────────────────────

class TestCalibrationMetrics:
    def test_healthy_pipeline(self):
        report = build_calibration_report(
            total_clauses_read=50,
            clauses_flagged_problematic=12,
            clauses_dropped_non_problematic=38,
            deep_checks_run_total=15,
            problems_after_dedup=10,
            themes_before_editorial=8,
            themes_after_editorial=6,
            counts_by_problem_type={
                "regulatory_shift": 3, "unclear_audit": 2,
                "open_scope": 2, "unbalanced_liability": 2,
                "excessive_reporting": 1, "bcm_transfer": 2,
            },
            counts_by_trigger_domain={
                "regulatory": 3, "audit": 2, "scope": 2,
                "liability": 2, "reporting": 1, "bcm": 2,
            },
            generic_theme_count=0,
            total_themes=6,
        )
        assert report.overall_verdict in ("HEALTHY", "HEALTHY_WITH_NOTES")
        assert all(m.verdict != "FAILING" for m in report.metrics)

    def test_too_many_flagged(self):
        report = build_calibration_report(
            total_clauses_read=20,
            clauses_flagged_problematic=18,
            clauses_dropped_non_problematic=2,
            deep_checks_run_total=50,
            problems_after_dedup=15,
            themes_before_editorial=10,
            themes_after_editorial=8,
            counts_by_problem_type={"open_scope": 18},
            counts_by_trigger_domain={"scope": 18},
            generic_theme_count=5,
            total_themes=8,
        )
        # Should flag at least problematic_rate and generic_theme_rate
        failing = [m for m in report.metrics if m.verdict == "FAILING"]
        assert len(failing) >= 1

    def test_too_few_flagged(self):
        report = build_calibration_report(
            total_clauses_read=100,
            clauses_flagged_problematic=2,
            clauses_dropped_non_problematic=98,
            deep_checks_run_total=1,
            problems_after_dedup=1,
            themes_before_editorial=1,
            themes_after_editorial=1,
        )
        needs_review = [m for m in report.metrics if m.verdict == "NEEDS_REVIEW"]
        assert len(needs_review) >= 1

    def test_report_to_dict(self):
        report = build_calibration_report(
            total_clauses_read=30,
            clauses_flagged_problematic=8,
            clauses_dropped_non_problematic=22,
            deep_checks_run_total=10,
            problems_after_dedup=7,
            themes_before_editorial=5,
            themes_after_editorial=4,
        )
        d = report.to_dict()
        assert "overall_verdict" in d
        assert "metrics" in d
        assert len(d["metrics"]) >= 5


# ───────────────────────────────────────────────────────────────────
# Test: Filter logic with golden cases
# ───────────────────────────────────────────────────────────────────

class TestFilterWithGoldenCases:
    def test_filter_separates_positive_negative(self, golden_cases):
        """All positive screen results go to problematic, negatives to dropped."""
        results = []
        for case in golden_cases:
            if case.expected_problematic:
                results.append(_make_screen_result_for_positive(case))
            else:
                results.append(_make_screen_result_for_negative(case))

        problematic, dropped = filter_problematic(results)
        expected_pos = sum(1 for c in golden_cases if c.expected_problematic)
        expected_neg = sum(1 for c in golden_cases if not c.expected_problematic)
        assert len(problematic) == expected_pos
        assert len(dropped) == expected_neg


# ───────────────────────────────────────────────────────────────────
# Test: Deep check merge preserves golden case evidence
# ───────────────────────────────────────────────────────────────────

class TestDeepCheckMergeWithGoldenCases:
    def test_merge_preserves_evidence(self, golden_positive):
        """Deep check merge should preserve original evidence text."""
        for case in golden_positive[:3]:
            screen = _make_screen_result_for_positive(case)
            # No deep checks — merge should still produce finding
            findings = merge_deep_checks_into_findings([screen], {})
            assert len(findings) == 1
            assert case.clause_text[:100] in findings[0].textstelle or case.clause_text[:100] in findings[0].scope_text
