"""Tests for the deterministic source fingerprint evidence linkage model.

Covers:
A. Deterministic-only resolution
  1. Deterministic fingerprints from source attributes
  2. Fingerprints survive consolidation
  3. Fingerprint-based linkage when index missing
  4. Merged findings preserve provenance fingerprints
  5. Duplicate prevention
  6. Missing provenance → unresolved (no fallback)
  7. refs_missing_provenance counted correctly
  8. Ambiguous fingerprints not auto-linked

B. Regression / structural tests
  9. Parse clusters, merge, dedup, reassign unchanged
  10. has_deterministic_provenance() helper
  11. LinkageStats includes all metrics
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
    return SimpleNamespace(
        id=uuid4(),
        kurzbeschreibung=kurzbeschreibung,
        textstelle=textstelle,
        absatz_ids=absatz_ids or [],
    )


def _make_raw_finding(textstelle: str, segment_ids: list[str] | None = None,
                      kurzbeschreibung: str = "test") -> RawFinding:
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
# A. DETERMINISTIC-ONLY RESOLUTION
# =============================================================================

class TestHasDeterministicProvenance:
    """TopicEvidenceRef.has_deterministic_provenance() helper."""

    def test_with_index(self):
        ref = TopicEvidenceRef(source_raw_index=0)
        assert ref.has_deterministic_provenance() is True

    def test_with_fingerprint(self):
        ref = TopicEvidenceRef(source_fingerprint="abc123")
        assert ref.has_deterministic_provenance() is True

    def test_with_both(self):
        ref = TopicEvidenceRef(source_raw_index=0, source_fingerprint="abc123")
        assert ref.has_deterministic_provenance() is True

    def test_with_title_only(self):
        ref = TopicEvidenceRef(source_title="Some Title")
        assert ref.has_deterministic_provenance() is False

    def test_completely_empty(self):
        ref = TopicEvidenceRef()
        assert ref.has_deterministic_provenance() is False


class TestDeterministicResolution:
    """Title-only refs must NOT resolve. Only index and fingerprint work."""

    def test_title_only_ref_is_unresolved(self):
        """Ref with source_title but no index/fingerprint → unresolved."""
        fs = _make_fundstelle("Exact Match Title")
        ref = TopicEvidenceRef(source_title="Exact Match Title")
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1
        assert stats.refs_missing_provenance == 1

    def test_index_resolution_works(self):
        fs0 = _make_fundstelle("F1")
        fs1 = _make_fundstelle("F2")
        cluster = _make_cluster("Topic", [_make_ref(1, "F1"), _make_ref(2, "F2")])

        raw_map = {0: [fs0], 1: [fs1]}
        result, stats = resolve_topic_fundstellen(
            [cluster], [fs0, fs1],
            raw_index_to_fundstelle=raw_map,
        )

        assert len(result[0][1]) == 2
        assert stats.direct_index_matches == 2

    def test_fingerprint_resolution_works(self):
        text = "Der Auftragnehmer haftet."
        fp = build_source_fingerprint(text, ["seg1"])
        fs = _make_fundstelle("X", textstelle=text, absatz_ids=["seg1"])

        ref = TopicEvidenceRef(source_fingerprint=fp)
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={fp: [fs]},
        )

        assert len(result[0][1]) == 1
        assert stats.source_fingerprint_matches == 1

    def test_refs_missing_provenance_counted(self):
        """Refs without index AND without fingerprint are counted."""
        ref_good = _make_ref(1, "Good", fingerprint="fp123")
        ref_bad = TopicEvidenceRef(source_title="Title Only")
        ref_empty = TopicEvidenceRef()

        cluster = _make_cluster("Topic", [ref_good, ref_bad, ref_empty])

        _, stats = resolve_topic_fundstellen(
            [cluster], [],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert stats.refs_missing_provenance == 2
        assert stats.total_references == 3


class TestFingerprintResolution:
    """Fingerprint-based resolution paths."""

    def test_fingerprint_succeeds_when_index_missing(self):
        text = "Unique clause text."
        fp = build_source_fingerprint(text, ["seg1"])
        fs = _make_fundstelle("X", textstelle=text, absatz_ids=["seg1"])

        ref = TopicEvidenceRef(source_fingerprint=fp, source_raw_index=None)
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={fp: [fs]},
        )

        assert len(result[0][1]) == 1
        assert stats.source_fingerprint_matches == 1
        assert stats.direct_index_matches == 0

    def test_ambiguous_fingerprint_not_auto_linked(self):
        fp = build_source_fingerprint("same text", ["seg1"])
        fs_a = _make_fundstelle("A", textstelle="same text", absatz_ids=["seg1"])
        fs_b = _make_fundstelle("B", textstelle="same text", absatz_ids=["seg1"])

        ref = TopicEvidenceRef(source_fingerprint=fp)
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs_a, fs_b],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={fp: [fs_a, fs_b]},
        )

        assert len(result[0][1]) == 0
        assert stats.ambiguous_fingerprints == 1
        assert stats.source_fingerprint_matches == 0
        assert stats.unresolved_references == 1

    def test_fingerprint_collision_count(self):
        fp_map = {
            "colliding_fp": [_make_fundstelle("A"), _make_fundstelle("B")],
            "unique_fp": [_make_fundstelle("C")],
        }
        _, stats = resolve_topic_fundstellen(
            [], [], raw_index_to_fundstelle={}, fingerprint_to_fundstelle=fp_map,
        )
        assert stats.fingerprint_collisions == 1


class TestDuplicatePrevention:
    """Same Fundstelle cannot be assigned to two topics."""

    def test_duplicate_prevented(self):
        fs = _make_fundstelle("F1")
        c1 = _make_cluster("A", [_make_ref(1)])
        c2 = _make_cluster("B", [_make_ref(1)])

        raw_map = {0: [fs]}
        result, stats = resolve_topic_fundstellen(
            [c1, c2], [fs], raw_index_to_fundstelle=raw_map,
        )

        assert len(result[0][1]) == 1
        assert len(result[1][1]) == 0
        assert stats.direct_index_matches == 1


class TestCompletelyEmptyRef:
    """Ref with nothing → unresolved."""

    def test_empty_ref(self):
        ref = TopicEvidenceRef()
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [_make_fundstelle("Something")],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1
        assert stats.refs_missing_provenance == 1



# =============================================================================
# B. REGRESSION / STRUCTURAL TESTS
# =============================================================================

class TestSourceFingerprintGeneration:
    def test_deterministic(self):
        fp1 = build_source_fingerprint("Der AN haftet.", ["seg1", "seg2"])
        fp2 = build_source_fingerprint("Der AN haftet.", ["seg1", "seg2"])
        assert fp1 == fp2
        assert len(fp1) == 16

    def test_segment_order_independent(self):
        fp1 = build_source_fingerprint("text", ["seg2", "seg1"])
        fp2 = build_source_fingerprint("text", ["seg1", "seg2"])
        assert fp1 == fp2

    def test_different_text_different_hash(self):
        fp1 = build_source_fingerprint("Klausel A", ["seg1"])
        fp2 = build_source_fingerprint("Klausel B", ["seg1"])
        assert fp1 != fp2

    def test_different_segments_different_hash(self):
        fp1 = build_source_fingerprint("same text", ["seg1"])
        fp2 = build_source_fingerprint("same text", ["seg2"])
        assert fp1 != fp2

    def test_uses_only_first_200_chars(self):
        base = "x" * 200
        fp1 = build_source_fingerprint(base + "AAAA", ["seg1"])
        fp2 = build_source_fingerprint(base + "BBBB", ["seg1"])
        assert fp1 == fp2

    def test_case_insensitive(self):
        fp1 = build_source_fingerprint("Der Auftragnehmer", ["seg1"])
        fp2 = build_source_fingerprint("der auftragnehmer", ["seg1"])
        assert fp1 == fp2

    def test_raw_finding_has_fingerprint(self):
        raw = _make_raw_finding("Der AN haftet.", ["seg1"])
        assert raw.source_fingerprint
        assert len(raw.source_fingerprint) == 16

    def test_raw_finding_fingerprint_matches_standalone(self):
        raw = _make_raw_finding("Der AN haftet.", ["seg1", "seg2"])
        expected = build_source_fingerprint("Der AN haftet.", ["seg1", "seg2"])
        assert raw.source_fingerprint == expected


class TestFingerprintSurvivesConsolidation:
    def test_single_preserves(self):
        raw = _make_raw_finding("Unique clause text", ["seg1"])
        consolidated = konsolidiere([raw])
        assert len(consolidated) == 1
        assert consolidated[0].source_fingerprints == [raw.source_fingerprint]

    def test_merged_preserves_all(self):
        raw_a = _make_raw_finding(
            "Der AN haftet unbeschränkt für Schäden.",
            ["seg1"], kurzbeschreibung="Unbeschränkte Haftung",
        )
        raw_b = _make_raw_finding(
            "Der AN haftet unbeschränkt für Schäden.",
            ["seg1"], kurzbeschreibung="Unbeschränkte Haftung identisch",
        )
        consolidated = konsolidiere([raw_a, raw_b])
        assert len(consolidated) == 1
        cf = consolidated[0]
        assert len(cf.source_fingerprints) == 2
        assert raw_a.source_fingerprint in cf.source_fingerprints
        assert raw_b.source_fingerprint in cf.source_fingerprints

    def test_distinct_keep_separate(self):
        raw_a = _make_raw_finding("Clause about liability", ["seg1"])
        raw_b = _make_raw_finding("Clause about audit rights", ["seg2"])
        consolidated = konsolidiere([raw_a, raw_b])
        assert len(consolidated) == 2
        assert consolidated[0].source_fingerprints[0] != consolidated[1].source_fingerprints[0]


class TestParseClusters:
    def test_basic_parsing(self):
        items = [{
            "topic_title": "Haftungsrisiken", "category": "Haftung",
            "risk_level": "Hoch", "beschreibung": "Beschreibung",
            "evidence": [
                {"finding_nr": 1, "ursprungstitel": "Titel A"},
                {"finding_nr": 3, "ursprungstitel": "Titel B"},
            ],
        }]
        clusters = _parse_clusters(items)
        assert clusters is not None
        c = clusters[0]
        assert len(c.evidence_refs) == 2
        assert c.evidence_refs[0].finding_nr == 1
        assert c.evidence_refs[0].source_raw_index == 0
        assert c.evidence_refs[1].finding_nr == 3
        assert c.evidence_refs[1].source_raw_index == 2

    def test_missing_finding_nr(self):
        items = [{
            "topic_title": "Test", "category": "Cat",
            "risk_level": "Mittel", "beschreibung": "Desc",
            "evidence": [{"ursprungstitel": "Only Title"}],
        }]
        clusters = _parse_clusters(items)
        ref = clusters[0].evidence_refs[0]
        assert ref.finding_nr is None
        assert ref.source_title == "Only Title"
        assert ref.source_raw_index is None
        assert ref.has_deterministic_provenance() is False

    def test_empty_evidence_skipped(self):
        items = [{
            "topic_title": "Test", "category": "Cat",
            "risk_level": "Mittel", "beschreibung": "Desc",
            "evidence": [{"ursprungstitel": "", "finding_nr": None}, {}],
        }]
        clusters = _parse_clusters(items)
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
    def test_reassigns(self):
        single = _make_cluster("Haftung", [_make_ref(1, "F1")])
        multi = _make_cluster("Haftungsrisiken", [_make_ref(2, "F2"), _make_ref(3, "F3")])
        clusters = _reassign_singles([single, multi])
        assert len(clusters) == 1
        assert len(clusters[0].evidence_refs) == 3


class TestDeduplicateEvidence:
    def test_dedup_by_finding_nr(self):
        c1 = _make_cluster("High", [_make_ref(1), _make_ref(2)], risikostufe="Hoch")
        c2 = _make_cluster("Low", [_make_ref(1)], risikostufe="Niedrig")
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
            ambiguous_fingerprints=1,
            unresolved_references=2,
            duplicate_reference_collisions=0,
            fingerprint_collisions=1,
            refs_missing_provenance=2,
            total_references=13,
        )
        d = stats.to_dict()
        assert d["direct_index_matches"] == 5
        assert d["source_fingerprint_matches"] == 3
        assert d["ambiguous_fingerprints"] == 1
        assert d["unresolved_references"] == 2
        assert d["duplicate_reference_collisions"] == 0
        assert d["fingerprint_collisions"] == 1
        assert d["refs_missing_provenance"] == 2
        assert d["total_references"] == 13
        # Removed fields must not appear
        assert "exact_title_fallback_matches" not in d
        assert "fingerprint_matches" not in d
        assert "exact_title_matches" not in d
        assert "unresolved_evidences" not in d
        assert "total_evidences" not in d


class TestBuildFingerprintWrapper:
    def test_delegates_to_canonical(self):
        fp_wrapper = _build_fingerprint("some text", ["seg1", "seg2"])
        fp_canonical = build_source_fingerprint("some text", ["seg1", "seg2"])
        assert fp_wrapper == fp_canonical
