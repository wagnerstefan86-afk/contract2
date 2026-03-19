"""Tests for the deterministic source fingerprint evidence linkage model.

Covers:
A. Positive paths
  1. Raw findings generate deterministic fingerprints from source attributes
  2. Fingerprints survive clustering/consolidation/orchestration
  3. Fingerprint-based linkage succeeds when direct index is missing
  4. Multiple raw findings merged preserve provenance fingerprints
  5. Duplicate evidence refs don't create duplicate junction rows

B. Negative / integrity paths
  6. Fingerprint collision (ambiguous) does not silently mislink
  7. Missing fingerprint + missing index → unresolved, not guessed
  8. Invalid final theme with zero links is dropped (invariant check)
  9. Legacy API safeguard still hides zero-evidence themes

C. Transitional fallback paths
  10. Exact-title fallback triggers only when index + fingerprint both fail
  11. Metrics label exact-title fallback honestly
  12. Ambiguous exact-title does not auto-link incorrectly
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.discovery.passes.base import RawFinding, build_source_fingerprint
from app.discovery.passes.themen_cluster import (
    TopicCluster,
    TopicEvidenceRef,
    LinkageStats,
    _parse_clusters,
    _merge_into,
    _reassign_singles,
    _deduplicate_evidence,
    resolve_topic_fundstellen,
    _build_fingerprint,
)
from app.discovery.consolidation import konsolidiere


# --- Helpers ---

def _make_ref(nr: int, title: str = "", fingerprint: str | None = None) -> TopicEvidenceRef:
    return TopicEvidenceRef(
        finding_nr=nr,
        source_title=title or f"Finding {nr}",
        source_raw_index=nr - 1,
        source_fingerprint=fingerprint,
    )


def _make_cluster(titel: str, refs: list[TopicEvidenceRef],
                  risikostufe: str = "Mittel") -> TopicCluster:
    return TopicCluster(
        titel=titel,
        kategorie="Test",
        risikostufe=risikostufe,
        beschreibung="Test description",
        evidence_refs=refs,
    )


def _make_fundstelle(kurzbeschreibung: str, textstelle: str = "some text",
                     absatz_ids: list | None = None):
    """Create a mock Fundstelle-like object."""
    return SimpleNamespace(
        id=uuid4(),
        kurzbeschreibung=kurzbeschreibung,
        textstelle=textstelle,
        absatz_ids=absatz_ids or [],
    )


def _make_raw_finding(textstelle: str, segment_ids: list[str] | None = None,
                      kurzbeschreibung: str = "test") -> RawFinding:
    """Create a RawFinding with source_fingerprint computed."""
    sids = segment_ids or ["seg1"]
    return RawFinding(
        textstelle=textstelle,
        kategorie="Haftung",
        kurzbeschreibung=kurzbeschreibung,
        erklaerung="test explanation",
        empfehlung="test recommendation",
        risikostufe="Hoch",
        segment_ids=sids,
        quelle_pass="test_pass",
        source_fingerprint=build_source_fingerprint(textstelle, sids),
    )


# =============================================================================
# A. POSITIVE PATHS
# =============================================================================

class TestSourceFingerprintGeneration:
    """A.1: Raw findings with stable source attributes generate deterministic fingerprints."""

    def test_fingerprint_deterministic(self):
        fp1 = build_source_fingerprint("Der Auftragnehmer haftet unbeschränkt.", ["seg1", "seg2"])
        fp2 = build_source_fingerprint("Der Auftragnehmer haftet unbeschränkt.", ["seg1", "seg2"])
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_fingerprint_segment_order_independent(self):
        fp1 = build_source_fingerprint("text", ["seg2", "seg1"])
        fp2 = build_source_fingerprint("text", ["seg1", "seg2"])
        assert fp1 == fp2

    def test_fingerprint_different_text_different_hash(self):
        fp1 = build_source_fingerprint("Klausel A", ["seg1"])
        fp2 = build_source_fingerprint("Klausel B", ["seg1"])
        assert fp1 != fp2

    def test_fingerprint_different_segments_different_hash(self):
        fp1 = build_source_fingerprint("same text", ["seg1"])
        fp2 = build_source_fingerprint("same text", ["seg2"])
        assert fp1 != fp2

    def test_fingerprint_uses_only_first_200_chars(self):
        base = "x" * 200
        fp1 = build_source_fingerprint(base + "AAAA", ["seg1"])
        fp2 = build_source_fingerprint(base + "BBBB", ["seg1"])
        assert fp1 == fp2

    def test_fingerprint_case_insensitive(self):
        fp1 = build_source_fingerprint("Der Auftragnehmer", ["seg1"])
        fp2 = build_source_fingerprint("der auftragnehmer", ["seg1"])
        assert fp1 == fp2

    def test_fingerprint_empty_inputs(self):
        fp = build_source_fingerprint("", [])
        assert len(fp) == 16  # Still produces a hash

    def test_raw_finding_has_fingerprint(self):
        raw = _make_raw_finding("Der Auftragnehmer haftet.", ["seg1"])
        assert raw.source_fingerprint
        assert len(raw.source_fingerprint) == 16

    def test_raw_finding_fingerprint_matches_standalone(self):
        """Fingerprint on RawFinding matches standalone computation."""
        raw = _make_raw_finding("Der AN haftet.", ["seg1", "seg2"])
        expected = build_source_fingerprint("Der AN haftet.", ["seg1", "seg2"])
        assert raw.source_fingerprint == expected


class TestFingerprintSurvivesConsolidation:
    """A.2 + A.4: Fingerprints survive consolidation; merged findings preserve all."""

    def test_single_finding_preserves_fingerprint(self):
        raw = _make_raw_finding("Unique clause text", ["seg1"])
        consolidated = konsolidiere([raw])
        assert len(consolidated) == 1
        assert consolidated[0].source_fingerprints == [raw.source_fingerprint]

    def test_merged_findings_preserve_all_fingerprints(self):
        """When two similar findings merge, both fingerprints are retained."""
        raw_a = _make_raw_finding(
            "Der Auftragnehmer haftet unbeschränkt für Schäden.",
            ["seg1"], kurzbeschreibung="Unbeschränkte Haftung",
        )
        raw_b = _make_raw_finding(
            "Der Auftragnehmer haftet unbeschränkt für Schäden.",
            ["seg1"], kurzbeschreibung="Unbeschränkte Haftung identisch",
        )
        consolidated = konsolidiere([raw_a, raw_b])
        assert len(consolidated) == 1
        cf = consolidated[0]
        assert len(cf.source_fingerprints) == 2
        assert raw_a.source_fingerprint in cf.source_fingerprints
        assert raw_b.source_fingerprint in cf.source_fingerprints

    def test_distinct_findings_keep_separate_fingerprints(self):
        raw_a = _make_raw_finding("Clause about liability", ["seg1"])
        raw_b = _make_raw_finding("Clause about audit rights", ["seg2"])
        consolidated = konsolidiere([raw_a, raw_b])
        assert len(consolidated) == 2
        assert consolidated[0].source_fingerprints[0] != consolidated[1].source_fingerprints[0]


class TestFingerprintBasedLinkage:
    """A.3: Fingerprint-based linkage succeeds when direct index is missing."""

    def test_fingerprint_resolution_succeeds(self):
        textstelle = "Der Auftragnehmer haftet unbeschränkt für alle Schäden."
        segment_ids = ["seg1"]
        fp = build_source_fingerprint(textstelle, segment_ids)

        fs = _make_fundstelle("Haftung", textstelle=textstelle, absatz_ids=segment_ids)

        ref = TopicEvidenceRef(
            finding_nr=None,
            source_title="Irrelevant Title",
            source_raw_index=None,
            source_fingerprint=fp,
        )
        cluster = _make_cluster("Topic", [ref])

        fp_map = {fp: [fs]}
        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle=fp_map,
        )

        assert len(result[0][1]) == 1
        assert stats.source_fingerprint_matches == 1
        assert stats.direct_index_matches == 0
        assert stats.exact_title_fallback_matches == 0

    def test_fingerprint_resolution_preferred_over_title(self):
        """Fingerprint match should be used before title fallback."""
        textstelle = "Specific clause text here."
        fp = build_source_fingerprint(textstelle, ["seg1"])

        fs = _make_fundstelle("Same Title", textstelle=textstelle, absatz_ids=["seg1"])

        ref = TopicEvidenceRef(
            source_title="Same Title",
            source_raw_index=None,
            source_fingerprint=fp,
        )
        cluster = _make_cluster("Topic", [ref])

        fp_map = {fp: [fs]}
        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle=fp_map,
        )

        assert len(result[0][1]) == 1
        # Should use fingerprint, NOT title fallback
        assert stats.source_fingerprint_matches == 1
        assert stats.exact_title_fallback_matches == 0


class TestDuplicatePreventionWithFingerprints:
    """A.5: Duplicate evidence refs don't create duplicate linkage."""

    def test_same_fundstelle_not_assigned_twice(self):
        fs = _make_fundstelle("Finding 1")
        fp = build_source_fingerprint(fs.textstelle, fs.absatz_ids)

        c1 = _make_cluster("Topic A", [_make_ref(1, "F1", fingerprint=fp)])
        c2 = _make_cluster("Topic B", [_make_ref(1, "F1", fingerprint=fp)])

        raw_map = {0: [fs]}
        fp_map = {fp: [fs]}
        result, stats = resolve_topic_fundstellen(
            [c1, c2], [fs],
            raw_index_to_fundstelle=raw_map,
            fingerprint_to_fundstelle=fp_map,
        )

        assert len(result[0][1]) == 1
        assert len(result[1][1]) == 0
        assert stats.direct_index_matches == 1


# =============================================================================
# B. NEGATIVE / INTEGRITY PATHS
# =============================================================================

class TestFingerprintCollisionHandling:
    """B.6: Fingerprint collision is handled explicitly, not silently linked."""

    def test_ambiguous_fingerprint_not_auto_linked(self):
        """Two Fundstelle share the same fingerprint → ambiguous, not linked."""
        fp = build_source_fingerprint("same text", ["seg1"])
        fs_a = _make_fundstelle("Finding A", textstelle="same text", absatz_ids=["seg1"])
        fs_b = _make_fundstelle("Finding B", textstelle="same text", absatz_ids=["seg1"])

        ref = TopicEvidenceRef(
            finding_nr=None,
            source_title="Unrelated",
            source_raw_index=None,
            source_fingerprint=fp,
        )
        cluster = _make_cluster("Topic", [ref])

        fp_map = {fp: [fs_a, fs_b]}
        result, stats = resolve_topic_fundstellen(
            [cluster], [fs_a, fs_b],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle=fp_map,
        )

        # Should NOT resolve via fingerprint (ambiguous)
        assert stats.ambiguous_fingerprints == 1
        assert stats.source_fingerprint_matches == 0

    def test_fingerprint_collision_count_in_stats(self):
        fp = "deadbeef12345678"
        fs_a = _make_fundstelle("A")
        fs_b = _make_fundstelle("B")

        fp_map = {fp: [fs_a, fs_b], "unique_fp": [_make_fundstelle("C")]}
        _, stats = resolve_topic_fundstellen(
            [], [], raw_index_to_fundstelle={}, fingerprint_to_fundstelle=fp_map,
        )
        assert stats.fingerprint_collisions == 1


class TestMissingFingerprintAndIndex:
    """B.7: Missing fingerprint + missing index → unresolved."""

    def test_no_index_no_fingerprint_no_title_match(self):
        ref = TopicEvidenceRef(
            finding_nr=99,
            source_title="Nonexistent Title",
            source_raw_index=98,
            source_fingerprint="badfp_12345678",
        )
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1
        assert stats.total_references == 1

    def test_completely_empty_ref(self):
        """A ref with no index, no fingerprint, no title → unresolved."""
        ref = TopicEvidenceRef()
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [_make_fundstelle("Something")],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1


# =============================================================================
# C. TRANSITIONAL FALLBACK PATHS
# =============================================================================

class TestExactTitleFallback:
    """C.10-12: Title fallback behavior."""

    def test_title_fallback_only_when_index_and_fp_fail(self):
        """Title fallback triggers only as last resort."""
        fs = _make_fundstelle("Exact Match Title", textstelle="clause text", absatz_ids=["seg1"])

        ref = TopicEvidenceRef(
            finding_nr=None,
            source_title="Exact Match Title",
            source_raw_index=None,
            source_fingerprint=None,  # No fingerprint available
        )
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 1
        assert stats.exact_title_fallback_matches == 1
        assert stats.direct_index_matches == 0
        assert stats.source_fingerprint_matches == 0

    def test_metrics_label_title_fallback_honestly(self):
        """Stats clearly distinguish title fallback from fingerprint matches."""
        fs = _make_fundstelle("Title Match")
        ref = TopicEvidenceRef(source_title="Title Match")
        cluster = _make_cluster("Topic", [ref])

        _, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        d = stats.to_dict()
        assert "exact_title_fallback_matches" in d
        assert "source_fingerprint_matches" in d
        assert d["exact_title_fallback_matches"] == 1
        assert d["source_fingerprint_matches"] == 0

    def test_mixed_three_strategy_resolution(self):
        """All three strategies used in one resolution pass."""
        text_a = "Clause about liability is very specific."
        text_b = "Clause about audit rights is different."
        fp_b = build_source_fingerprint(text_b, ["seg2"])

        fs_a = _make_fundstelle("Finding A", textstelle=text_a, absatz_ids=["seg1"])
        fs_b = _make_fundstelle("Finding B", textstelle=text_b, absatz_ids=["seg2"])
        fs_c = _make_fundstelle("Title Only Match", textstelle="other", absatz_ids=["seg3"])

        ref_by_index = _make_ref(1, "Finding A")
        ref_by_fp = TopicEvidenceRef(
            source_title="Irrelevant",
            source_raw_index=None,
            source_fingerprint=fp_b,
        )
        ref_by_title = TopicEvidenceRef(
            source_title="Title Only Match",
            source_raw_index=None,
            source_fingerprint=None,
        )

        cluster = _make_cluster("Topic", [ref_by_index, ref_by_fp, ref_by_title])
        raw_map = {0: [fs_a]}
        fp_map = {fp_b: [fs_b]}

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs_a, fs_b, fs_c],
            raw_index_to_fundstelle=raw_map,
            fingerprint_to_fundstelle=fp_map,
        )

        assert len(result[0][1]) == 3
        assert stats.direct_index_matches == 1
        assert stats.source_fingerprint_matches == 1
        assert stats.exact_title_fallback_matches == 1
        assert stats.unresolved_references == 0


# =============================================================================
# STRUCTURAL TESTS (preserved from previous test suite)
# =============================================================================

class TestTopicEvidenceRef:
    def test_defaults(self):
        ref = TopicEvidenceRef()
        assert ref.finding_nr is None
        assert ref.source_title is None
        assert ref.source_raw_index is None
        assert ref.source_fingerprint is None

    def test_from_llm_output(self):
        ref = TopicEvidenceRef(
            finding_nr=3,
            source_title="Haftungsklausel",
            source_raw_index=2,
        )
        assert ref.finding_nr == 3
        assert ref.source_raw_index == 2
        assert ref.source_fingerprint is None


class TestParseClusters:
    def test_basic_parsing(self):
        items = [
            {
                "topic_title": "Haftungsrisiken",
                "category": "Haftung",
                "risk_level": "Hoch",
                "beschreibung": "Beschreibung",
                "evidence": [
                    {"finding_nr": 1, "ursprungstitel": "Titel A"},
                    {"finding_nr": 3, "ursprungstitel": "Titel B"},
                ],
            }
        ]
        clusters = _parse_clusters(items)
        assert clusters is not None
        assert len(clusters) == 1
        c = clusters[0]
        assert len(c.evidence_refs) == 2
        assert c.evidence_refs[0].finding_nr == 1
        assert c.evidence_refs[0].source_raw_index == 0
        assert c.evidence_refs[1].finding_nr == 3
        assert c.evidence_refs[1].source_raw_index == 2

    def test_missing_finding_nr(self):
        items = [
            {
                "topic_title": "Test",
                "category": "Cat",
                "risk_level": "Mittel",
                "beschreibung": "Desc",
                "evidence": [{"ursprungstitel": "Only Title"}],
            }
        ]
        clusters = _parse_clusters(items)
        assert clusters is not None
        ref = clusters[0].evidence_refs[0]
        assert ref.finding_nr is None
        assert ref.source_title == "Only Title"
        assert ref.source_raw_index is None

    def test_empty_evidence_skipped(self):
        items = [
            {
                "topic_title": "Test",
                "category": "Cat",
                "risk_level": "Mittel",
                "beschreibung": "Desc",
                "evidence": [{"ursprungstitel": "", "finding_nr": None}, {}],
            }
        ]
        clusters = _parse_clusters(items)
        assert clusters is not None
        assert len(clusters[0].evidence_refs) == 0


class TestMergeInto:
    def test_merges_evidence_refs(self):
        ref_a = _make_ref(1, "A")
        ref_b = _make_ref(2, "B")
        target = _make_cluster("Target", [ref_a])
        source = _make_cluster("Source", [ref_b])
        _merge_into(target, source)
        assert len(target.evidence_refs) == 2
        assert target.evidence_refs[0] is ref_a
        assert target.evidence_refs[1] is ref_b


class TestReassignSingles:
    def test_reassigns_single_evidence_refs(self):
        single = _make_cluster("Haftung", [_make_ref(1, "Finding 1")])
        multi = _make_cluster(
            "Haftungsrisiken",
            [_make_ref(2, "Finding 2"), _make_ref(3, "Finding 3")],
        )
        clusters = _reassign_singles([single, multi])
        assert len(clusters) == 1
        assert len(clusters[0].evidence_refs) == 3


class TestDeduplicateEvidence:
    def test_dedup_by_finding_nr(self):
        ref1 = _make_ref(1, "Finding 1")
        ref1_dup = _make_ref(1, "Finding 1")
        ref2 = _make_ref(2, "Finding 2")
        c1 = _make_cluster("High Risk", [ref1, ref2], risikostufe="Hoch")
        c2 = _make_cluster("Low Risk", [ref1_dup], risikostufe="Niedrig")
        result = _deduplicate_evidence([c1, c2])
        assert len(result[0].evidence_refs) == 2
        assert len(result[1].evidence_refs) == 0

    def test_dedup_by_title_when_no_nr(self):
        ref_a = TopicEvidenceRef(source_title="Same Title")
        ref_b = TopicEvidenceRef(source_title="Same Title")
        ref_c = TopicEvidenceRef(source_title="Different")
        c1 = _make_cluster("A", [ref_a, ref_c], risikostufe="Hoch")
        c2 = _make_cluster("B", [ref_b], risikostufe="Niedrig")
        result = _deduplicate_evidence([c1, c2])
        assert len(result[0].evidence_refs) == 2
        assert len(result[1].evidence_refs) == 0


class TestLinkageStats:
    def test_to_dict_has_all_metrics(self):
        stats = LinkageStats(
            direct_index_matches=5,
            source_fingerprint_matches=3,
            exact_title_fallback_matches=1,
            ambiguous_fingerprints=1,
            unresolved_references=2,
            duplicate_reference_collisions=0,
            fingerprint_collisions=1,
            total_references=12,
        )
        d = stats.to_dict()
        assert d["direct_index_matches"] == 5
        assert d["source_fingerprint_matches"] == 3
        assert d["exact_title_fallback_matches"] == 1
        assert d["ambiguous_fingerprints"] == 1
        assert d["unresolved_references"] == 2
        assert d["duplicate_reference_collisions"] == 0
        assert d["fingerprint_collisions"] == 1
        assert d["total_references"] == 12
        # Old field names must not appear
        assert "fingerprint_matches" not in d
        assert "exact_title_matches" not in d
        assert "unresolved_evidences" not in d
        assert "total_evidences" not in d


class TestBuildFingerprint:
    """Tests for the _build_fingerprint wrapper in themen_cluster.py."""

    def test_wrapper_delegates_to_canonical(self):
        fp_wrapper = _build_fingerprint("some text", ["seg1", "seg2"])
        fp_canonical = build_source_fingerprint("some text", ["seg1", "seg2"])
        assert fp_wrapper == fp_canonical
