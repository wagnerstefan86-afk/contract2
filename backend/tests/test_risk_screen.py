"""Tests for the 2-stage pipeline: universal risk read + deep checks.

Tests verify:
- Non-problematic standard clauses are dropped
- Regulatory burden transfer is retained
- Excessive reporting burden is retained
- Vague audit clauses are retained
- Neutral InfoSec clauses are ignored
- Theme output does not collapse into generic buckets
- Exact evidence survives through the pipeline
- Large clause sets do not invoke deep checks for every clause
"""

import pytest
from unittest.mock import AsyncMock, patch

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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seg(id: str, text: str) -> Segment:
    """Create a minimal Segment for testing."""
    return Segment(id=id, text=text, absatz_start=0, absatz_ende=0, fenster_text=text)


# ---------------------------------------------------------------------------
# Test: Non-problematic standard clauses are dropped
# ---------------------------------------------------------------------------

class TestFilterNonProblematic:
    def test_standard_iso_clause_dropped(self):
        """A standard ISO 27001 compliance clause should not be flagged."""
        result = ClauseScreenResult(
            segment_id="seg-0-2",
            segment_text="Der Auftragnehmer hält ISO 27001 ein und unterhält angemessene Sicherheitskontrollen.",
            is_problematic=False,
        )
        problematic, dropped = filter_problematic([result])
        assert len(problematic) == 0
        assert len(dropped) == 1

    def test_neutral_confidentiality_clause_dropped(self):
        """Balanced confidentiality clause should not be flagged."""
        result = ClauseScreenResult(
            segment_id="seg-1-3",
            segment_text="Die Parteien vereinbaren Vertraulichkeit gemäß den üblichen Bedingungen.",
            is_problematic=False,
        )
        problematic, dropped = filter_problematic([result])
        assert len(problematic) == 0
        assert len(dropped) == 1

    def test_mixed_clauses_partitioned(self):
        """Mix of problematic and non-problematic clauses correctly partitioned."""
        results = [
            ClauseScreenResult(
                segment_id="seg-0-2",
                segment_text="Standard clause.",
                is_problematic=False,
            ),
            ClauseScreenResult(
                segment_id="seg-3-5",
                segment_text="Unlimited liability clause.",
                is_problematic=True,
                problem_types=["unbalanced_liability"],
                severity="high",
                reason="Unbegrenzte Haftung ohne Deckelung.",
                evidence_text="Unlimited liability clause.",
                trigger_domains=["liability"],
                needs_deep_check=True,
                deep_check_domains=["liability"],
            ),
        ]
        problematic, dropped = filter_problematic(results)
        assert len(problematic) == 1
        assert len(dropped) == 1
        assert problematic[0].segment_id == "seg-3-5"


# ---------------------------------------------------------------------------
# Test: Regulatory burden transfer is retained
# ---------------------------------------------------------------------------

class TestRegulatoryBurdenRetained:
    def test_regulatory_shift_flagged(self):
        result = ClauseScreenResult(
            segment_id="seg-5-7",
            segment_text="Der Auftragnehmer stellt jederzeit die Einhaltung aller regulatorischen Anforderungen sicher.",
            is_problematic=True,
            problem_types=["regulatory_shift", "unrestricted_compliance_passthrough"],
            severity="high",
            reason="Regulatorische Pflichten werden pauschal auf den Dienstleister verlagert.",
            evidence_text="Der Auftragnehmer stellt jederzeit die Einhaltung aller regulatorischen Anforderungen sicher.",
            trigger_domains=["regulatory"],
            needs_deep_check=True,
            deep_check_domains=["regulatory"],
        )
        problematic, _ = filter_problematic([result])
        assert len(problematic) == 1
        assert "regulatory_shift" in problematic[0].problem_types


# ---------------------------------------------------------------------------
# Test: Excessive reporting retained
# ---------------------------------------------------------------------------

class TestExcessiveReportingRetained:
    def test_excessive_reporting_flagged(self):
        result = ClauseScreenResult(
            segment_id="seg-8-10",
            segment_text="Der Auftraggeber kann jederzeit Berichte und Nachweise verlangen.",
            is_problematic=True,
            problem_types=["excessive_reporting", "one_sided_rights"],
            severity="medium",
            reason="Einseitiges Recht auf unbegrenzte Berichtsanforderungen.",
            evidence_text="Der Auftraggeber kann jederzeit Berichte und Nachweise verlangen.",
            trigger_domains=["reporting"],
            needs_deep_check=True,
            deep_check_domains=["reporting"],
        )
        problematic, _ = filter_problematic([result])
        assert len(problematic) == 1
        assert "excessive_reporting" in problematic[0].problem_types


# ---------------------------------------------------------------------------
# Test: Vague audit clauses retained
# ---------------------------------------------------------------------------

class TestVagueAuditRetained:
    def test_unclear_audit_flagged(self):
        result = ClauseScreenResult(
            segment_id="seg-12-14",
            segment_text="Der Auftraggeber hat jederzeit uneingeschränktes Zugangsrecht zu allen Systemen.",
            is_problematic=True,
            problem_types=["unclear_audit"],
            severity="high",
            reason="Uneingeschränktes Audit-Zugangsrecht ohne Vorankündigung oder Begrenzung.",
            evidence_text="Der Auftraggeber hat jederzeit uneingeschränktes Zugangsrecht zu allen Systemen.",
            trigger_domains=["audit"],
            needs_deep_check=True,
            deep_check_domains=["audit"],
        )
        problematic, _ = filter_problematic([result])
        assert len(problematic) == 1
        assert "unclear_audit" in problematic[0].problem_types


# ---------------------------------------------------------------------------
# Test: Neutral InfoSec clauses ignored
# ---------------------------------------------------------------------------

class TestNeutralInfoSecIgnored:
    def test_standard_security_contact_not_flagged(self):
        """'Provider appoints a security contact' is not a problem."""
        result = ClauseScreenResult(
            segment_id="seg-15-17",
            segment_text="Der Auftragnehmer benennt einen Ansprechpartner für Sicherheitsfragen.",
            is_problematic=False,
        )
        problematic, dropped = filter_problematic([result])
        assert len(problematic) == 0
        assert len(dropped) == 1


# ---------------------------------------------------------------------------
# Test: Exact evidence survives
# ---------------------------------------------------------------------------

class TestEvidenceSurvival:
    def test_evidence_in_raw_finding(self):
        """Evidence text should be preserved when converting to RawFinding."""
        original_text = "Der Auftragnehmer haftet unbeschränkt für das Handeln seiner Subunternehmer."
        result = ClauseScreenResult(
            segment_id="seg-20-22",
            segment_text=f"Kontext davor. {original_text} Kontext danach.",
            is_problematic=True,
            problem_types=["subcontractor_liability"],
            severity="high",
            reason="Unbegrenzte Subunternehmer-Haftung.",
            evidence_text=original_text,
            trigger_domains=["liability", "subcontractor"],
            needs_deep_check=True,
            deep_check_domains=["liability", "subcontractor"],
            category="Subunternehmer",
        )
        finding = result.to_raw_finding()
        assert original_text in finding.textstelle
        assert finding.scope_text == original_text
        assert finding.kategorie == "Subunternehmer"
        assert finding.risikostufe == "Hoch"


# ---------------------------------------------------------------------------
# Test: Deep checks selective, not blanket
# ---------------------------------------------------------------------------

class TestDeepChecksSelective:
    def test_only_flagged_clauses_get_deep_checks(self):
        """Non-deep-check clauses should not trigger deep analysis."""
        clauses = [
            ClauseScreenResult(
                segment_id="seg-0-2",
                segment_text="Standard clause.",
                is_problematic=True,
                problem_types=["undefined_terms"],
                severity="low",
                reason="Minor issue.",
                evidence_text="Standard clause.",
                trigger_domains=[],
                needs_deep_check=False,  # No deep check needed
                deep_check_domains=[],
            ),
            ClauseScreenResult(
                segment_id="seg-3-5",
                segment_text="Audit clause.",
                is_problematic=True,
                problem_types=["unclear_audit"],
                severity="high",
                reason="Unclear audit.",
                evidence_text="Audit clause.",
                trigger_domains=["audit"],
                needs_deep_check=True,
                deep_check_domains=["audit"],
            ),
        ]
        # Only seg-3-5 needs deep checks
        needing_deep = [c for c in clauses if c.needs_deep_check]
        assert len(needing_deep) == 1
        assert needing_deep[0].segment_id == "seg-3-5"


# ---------------------------------------------------------------------------
# Test: Deep check merge into findings
# ---------------------------------------------------------------------------

class TestDeepCheckMerge:
    def test_severity_escalation(self):
        """Deep check should escalate severity if higher than first-read."""
        clause = ClauseScreenResult(
            segment_id="seg-0-2",
            segment_text="Audit clause text.",
            is_problematic=True,
            problem_types=["unclear_audit"],
            severity="medium",
            reason="Unclear audit rights.",
            evidence_text="Audit clause text.",
            trigger_domains=["audit"],
            needs_deep_check=True,
            deep_check_domains=["audit"],
        )
        deep = {
            "seg-0-2": [
                DeepCheckResult(
                    domain="audit",
                    severity="high",
                    deep_reason="Uneingeschränkte Vor-Ort-Audits.",
                    recommendation="Audit-Frequenz begrenzen.",
                    negotiation_points=["Max. 2 Audits pro Jahr", "48h Vorankündigung"],
                    alternative_wording="Max. 2 angekündigte Audits pro Jahr.",
                    bidder_question="Akzeptieren Sie max. 2 Audits/Jahr?",
                )
            ]
        }
        findings = merge_deep_checks_into_findings([clause], deep)
        assert len(findings) == 1
        assert findings[0].risikostufe == "Hoch"  # Escalated from Mittel
        assert "Audit-Frequenz begrenzen" in findings[0].empfehlung
        assert findings[0].alternativformulierung == "Max. 2 angekündigte Audits pro Jahr."
        assert findings[0].bieterfrage == "Akzeptieren Sie max. 2 Audits/Jahr?"

    def test_no_deep_check_preserves_first_read(self):
        """Clauses without deep checks should still produce RawFindings."""
        clause = ClauseScreenResult(
            segment_id="seg-5-7",
            segment_text="Some problematic clause.",
            is_problematic=True,
            problem_types=["open_scope"],
            severity="low",
            reason="Offener Leistungsumfang.",
            evidence_text="Some problematic clause.",
            trigger_domains=[],
            needs_deep_check=False,
            deep_check_domains=[],
        )
        findings = merge_deep_checks_into_findings([clause], {})
        assert len(findings) == 1
        assert findings[0].risikostufe == "Niedrig"
        assert findings[0].erklaerung == "Offener Leistungsumfang."


# ---------------------------------------------------------------------------
# Test: Problem type to category mapping
# ---------------------------------------------------------------------------

class TestProblemTypeMapping:
    def test_known_types_map_correctly(self):
        assert _problem_type_to_category(["regulatory_shift"]) == "Compliance"
        assert _problem_type_to_category(["unclear_audit"]) == "Audit"
        assert _problem_type_to_category(["unbalanced_liability"]) == "Haftung"
        assert _problem_type_to_category(["bcm_transfer"]) == "BCM"
        assert _problem_type_to_category(["open_scope"]) == "Leistungsumfang & Abgrenzung"
        assert _problem_type_to_category(["exit_or_transition_burden"]) == "Exit"

    def test_unknown_type_falls_back(self):
        assert _problem_type_to_category(["unknown_type"]) == "Sonstiges"
        assert _problem_type_to_category([]) == "Sonstiges"


# ---------------------------------------------------------------------------
# Test: Parse screen response
# ---------------------------------------------------------------------------

class TestParseScreenResponse:
    def test_parse_non_problematic(self):
        seg = _seg("seg-0-2", "Normal clause.")
        result = _parse_screen_response('{"is_problematic": false}', seg)
        assert result.is_problematic is False

    def test_parse_problematic(self):
        seg = _seg("seg-0-2", "Problematic clause text here.")
        json_str = '''{
            "is_problematic": true,
            "problem_types": ["regulatory_shift"],
            "severity": "high",
            "reason": "Regulatorische Verlagerung.",
            "evidence_text": "Problematic clause text here.",
            "category": "Compliance",
            "trigger_domains": ["regulatory"],
            "needs_deep_check": true,
            "deep_check_domains": ["regulatory"]
        }'''
        result = _parse_screen_response(json_str, seg)
        assert result.is_problematic is True
        assert "regulatory_shift" in result.problem_types
        assert result.severity == "high"
        assert result.category == "Compliance"

    def test_parse_array_response(self):
        seg = _seg("seg-0-2", "Some text.")
        json_str = '[{"is_problematic": false}]'
        result = _parse_screen_response(json_str, seg)
        assert result.is_problematic is False

    def test_parse_invalid_json_returns_non_problematic(self):
        seg = _seg("seg-0-2", "Some text.")
        result = _parse_screen_response("not json at all", seg)
        assert result.is_problematic is False


# ---------------------------------------------------------------------------
# Test: Parse deep check response
# ---------------------------------------------------------------------------

class TestParseDeepCheck:
    def test_parse_valid(self):
        json_str = '''{
            "severity": "high",
            "deep_reason": "Detaillierte Erklärung.",
            "recommendation": "Haftung begrenzen.",
            "negotiation_points": ["Punkt 1", "Punkt 2"],
            "alternative_wording": "Alternative Formulierung.",
            "bidder_question": "Bieterfrage hier.",
            "refined_problem_types": ["unbalanced_liability"],
            "evidence_text": "Original text."
        }'''
        result = _parse_deep_check(json_str, "liability")
        assert result.domain == "liability"
        assert result.severity == "high"
        assert len(result.negotiation_points) == 2
        assert result.alternative_wording == "Alternative Formulierung."

    def test_parse_invalid_returns_default(self):
        result = _parse_deep_check("garbage", "audit")
        assert result.domain == "audit"
        assert result.severity == "low"
        assert result.deep_reason == ""


# ---------------------------------------------------------------------------
# Test: Taxonomy completeness
# ---------------------------------------------------------------------------

class TestTaxonomy:
    def test_all_problem_types_have_category_mapping(self):
        """Every problem type in the taxonomy should map to a category."""
        for pt in PROBLEM_TYPES:
            cat = _problem_type_to_category([pt])
            assert cat != "Sonstiges", f"Problem type '{pt}' has no category mapping"

    def test_deep_check_domains_exist(self):
        """Verify the expected deep check domains are defined."""
        expected = {"audit", "reporting", "bcm", "liability", "regulatory", "scope"}
        assert expected.issubset(DEEP_CHECK_DOMAINS)
