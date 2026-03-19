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

C. Orchestrator enrichment safety
  12. Ambiguous title recovery must NOT enrich
  13. Unique title recovery enriches correctly
  14. Missing provenance stays unresolved through full pipeline

D. Edge cases and end-to-end
  15. Fingerprint collision with resolution attempt
  16. End-to-end pipeline with mixed provenance
  17. Telemetry consistency

E. No hidden fallback regression
  18. No title-based matching in resolver
  19. No fuzzy matching anywhere in linkage
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


# =============================================================================
# C. ORCHESTRATOR ENRICHMENT SAFETY
# =============================================================================

def _simulate_enrichment(all_raw_findings, topic_clusters):
    """Simulate the orchestrator's two-pass enrichment logic.

    Reproduces the exact enrichment code from orchestrator._run_pipeline
    (Step 6b pre-resolution enrichment) so we can test it in isolation
    without running the full async pipeline.
    """
    # Build title→raw_indices lookup (same as orchestrator)
    title_to_raw_indices: dict[str, list[int]] = {}
    for idx, raw in enumerate(all_raw_findings):
        key = raw.kurzbeschreibung.lower().strip()
        if key:
            title_to_raw_indices.setdefault(key, []).append(idx)

    for cluster in topic_clusters:
        for ref in cluster.evidence_refs:
            # Pass 1: Direct index → fingerprint
            if ref.source_fingerprint:
                continue
            if ref.source_raw_index is not None and ref.source_raw_index < len(all_raw_findings):
                raw = all_raw_findings[ref.source_raw_index]
                if raw.source_fingerprint:
                    ref.source_fingerprint = raw.source_fingerprint
                continue

            # Pass 2: Recover from title (only if unambiguous)
            if ref.source_title:
                title_key = ref.source_title.lower().strip()
                matching_indices = title_to_raw_indices.get(title_key, [])
                if len(matching_indices) == 1:
                    raw_idx = matching_indices[0]
                    raw = all_raw_findings[raw_idx]
                    ref.source_raw_index = raw_idx
                    ref.source_fingerprint = raw.source_fingerprint


class TestOrchestratorEnrichmentAmbiguity:
    """Task 2: Ambiguous title recovery must NOT enrich or link."""

    def test_ambiguous_title_no_enrichment(self):
        """Two RawFindings with identical kurzbeschreibung → no enrichment."""
        raw_a = _make_raw_finding(
            "Klausel über Haftung.", ["seg1"],
            kurzbeschreibung="Unbeschränkte Haftung",
        )
        raw_b = _make_raw_finding(
            "Andere Klausel über Haftung.", ["seg2"],
            kurzbeschreibung="Unbeschränkte Haftung",
        )
        all_raw = [raw_a, raw_b]

        # Ref has only source_title (LLM omitted finding_nr)
        ref = TopicEvidenceRef(source_title="Unbeschränkte Haftung")
        cluster = _make_cluster("Haftungsthema", [ref])

        _simulate_enrichment(all_raw, [cluster])

        # Enrichment must NOT have assigned provenance
        assert ref.source_raw_index is None
        assert ref.source_fingerprint is None
        assert ref.has_deterministic_provenance() is False

    def test_ambiguous_title_stays_unresolved_in_resolver(self):
        """After failed enrichment, resolver must leave ref unresolved."""
        raw_a = _make_raw_finding(
            "Klausel A.", ["seg1"], kurzbeschreibung="Shared Title",
        )
        raw_b = _make_raw_finding(
            "Klausel B.", ["seg2"], kurzbeschreibung="Shared Title",
        )
        all_raw = [raw_a, raw_b]

        ref = TopicEvidenceRef(source_title="Shared Title")
        cluster = _make_cluster("Topic", [ref])

        # Enrichment step
        _simulate_enrichment(all_raw, [cluster])

        # Build fundstellen for resolution
        fs_a = _make_fundstelle("Shared Title", textstelle="Klausel A.", absatz_ids=["seg1"])
        fs_b = _make_fundstelle("Shared Title", textstelle="Klausel B.", absatz_ids=["seg2"])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs_a, fs_b],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1
        assert stats.refs_missing_provenance == 1

    def test_unique_title_enriches_correctly(self):
        """Single matching RawFinding → enrichment proceeds."""
        raw = _make_raw_finding(
            "Einzigartige Klausel.", ["seg1"],
            kurzbeschreibung="Unique Finding Title",
        )
        all_raw = [raw]

        ref = TopicEvidenceRef(source_title="Unique Finding Title")
        cluster = _make_cluster("Topic", [ref])

        _simulate_enrichment(all_raw, [cluster])

        assert ref.source_raw_index == 0
        assert ref.source_fingerprint == raw.source_fingerprint
        assert ref.has_deterministic_provenance() is True

    def test_case_insensitive_ambiguity_detection(self):
        """Title comparison is case-insensitive for ambiguity."""
        raw_a = _make_raw_finding("Text A.", ["seg1"], kurzbeschreibung="Haftung")
        raw_b = _make_raw_finding("Text B.", ["seg2"], kurzbeschreibung="haftung")
        all_raw = [raw_a, raw_b]

        ref = TopicEvidenceRef(source_title="HAFTUNG")
        cluster = _make_cluster("Topic", [ref])

        _simulate_enrichment(all_raw, [cluster])

        # Case-insensitive matching means both match → ambiguous → no enrichment
        assert ref.source_raw_index is None
        assert ref.source_fingerprint is None


# =============================================================================
# D. EDGE CASES AND END-TO-END
# =============================================================================

class TestMissingProvenanceStaysUnresolved:
    """Task 3: Refs with no provenance and no valid enrichment remain unresolved."""

    def test_no_index_no_fingerprint_no_title(self):
        """Completely empty ref → unresolved, no crash."""
        ref = TopicEvidenceRef()
        cluster = _make_cluster("Topic", [ref])

        _simulate_enrichment([], [cluster])

        assert ref.source_raw_index is None
        assert ref.source_fingerprint is None

        _, stats = resolve_topic_fundstellen(
            [cluster], [_make_fundstelle("Anything")],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )
        assert stats.unresolved_references == 1
        assert stats.refs_missing_provenance == 1

    def test_title_only_no_matching_raw(self):
        """Title that doesn't match any raw finding → no enrichment → unresolved."""
        raw = _make_raw_finding("Some text.", ["seg1"], kurzbeschreibung="Different Title")
        ref = TopicEvidenceRef(source_title="No Match")
        cluster = _make_cluster("Topic", [ref])

        _simulate_enrichment([raw], [cluster])

        assert ref.source_raw_index is None
        assert ref.source_fingerprint is None

        _, stats = resolve_topic_fundstellen(
            [cluster], [_make_fundstelle("No Match")],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )
        assert stats.unresolved_references == 1
        assert stats.refs_missing_provenance == 1


class TestFingerprintCollisionSafety:
    """Task 4: Fingerprint collisions are handled safely."""

    def test_forced_collision_not_auto_linked(self):
        """Two Fundstellen with same fingerprint → ambiguous → no link."""
        # Force identical fingerprint by using identical textstelle + absatz_ids
        text = "Identische Vertragsklausel über Haftung."
        fp = build_source_fingerprint(text, ["seg1"])

        fs_a = _make_fundstelle("A", textstelle=text, absatz_ids=["seg1"])
        fs_b = _make_fundstelle("B", textstelle=text, absatz_ids=["seg1"])

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
        assert stats.fingerprint_collisions == 1

    def test_collision_does_not_affect_unique_fingerprints(self):
        """A collision on one fingerprint doesn't block resolution of another."""
        text_collision = "Shared clause text."
        fp_collision = build_source_fingerprint(text_collision, ["seg1"])
        text_unique = "Unique clause text."
        fp_unique = build_source_fingerprint(text_unique, ["seg2"])

        fs_a = _make_fundstelle("A", textstelle=text_collision, absatz_ids=["seg1"])
        fs_b = _make_fundstelle("B", textstelle=text_collision, absatz_ids=["seg1"])
        fs_c = _make_fundstelle("C", textstelle=text_unique, absatz_ids=["seg2"])

        ref_ambiguous = TopicEvidenceRef(source_fingerprint=fp_collision)
        ref_unique = TopicEvidenceRef(source_fingerprint=fp_unique)
        cluster = _make_cluster("Topic", [ref_ambiguous, ref_unique])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs_a, fs_b, fs_c],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={
                fp_collision: [fs_a, fs_b],
                fp_unique: [fs_c],
            },
        )

        assert len(result[0][1]) == 1  # Only the unique one links
        assert stats.ambiguous_fingerprints == 1
        assert stats.source_fingerprint_matches == 1
        assert stats.unresolved_references == 1


class TestEndToEndPipeline:
    """Task 5: End-to-end pipeline test with realistic mixed provenance."""

    def test_mixed_provenance_pipeline(self):
        """Simulate a realistic pipeline with 8 raw findings and mixed provenance."""
        # --- Create 8 RawFindings with varied characteristics ---
        raws = [
            _make_raw_finding("Haftung unbeschränkt.", ["seg1"], kurzbeschreibung="Unbeschränkte Haftung"),
            _make_raw_finding("Audit-Rechte ohne Vorankündigung.", ["seg2"], kurzbeschreibung="Audit-Rechte"),
            _make_raw_finding("SLA-Rahmen unklar.", ["seg3"], kurzbeschreibung="Unklare SLAs"),
            _make_raw_finding("Exit-Klausel fehlt.", ["seg4"], kurzbeschreibung="Fehlende Exit-Regelung"),
            _make_raw_finding("Subunternehmer unbegrenzt.", ["seg5"], kurzbeschreibung="Subunternehmer"),
            _make_raw_finding("Datenschutz ungeregelt.", ["seg6"], kurzbeschreibung="Datenschutz"),
            _make_raw_finding("Weisungsrecht einseitig.", ["seg7"], kurzbeschreibung="Weisungsrecht"),
            _make_raw_finding("Compliance ohne Kosten.", ["seg8"], kurzbeschreibung="Compliance"),
        ]

        # Build Fundstellen (one per raw, as if consolidation was 1:1)
        fundstellen = []
        raw_index_to_fs: dict[int, list] = {}
        fp_to_fs: dict[str, list] = {}
        for i, raw in enumerate(raws):
            fs = _make_fundstelle(
                raw.kurzbeschreibung,
                textstelle=raw.textstelle,
                absatz_ids=raw.segment_ids,
            )
            fundstellen.append(fs)
            raw_index_to_fs[i] = [fs]
            fp = build_source_fingerprint(raw.textstelle, raw.segment_ids)
            fp_to_fs.setdefault(fp, []).append(fs)

        # --- Build topic clusters with mixed provenance ---
        clusters = [
            # Topic 1: two refs with valid index provenance
            _make_cluster("Haftungsrisiken", [
                _make_ref(1, "Unbeschränkte Haftung"),  # index=0
                _make_ref(5, "Subunternehmer"),          # index=4
            ], risikostufe="Hoch"),

            # Topic 2: one ref with fingerprint only, one with index
            _make_cluster("Operative Risiken", [
                TopicEvidenceRef(
                    source_fingerprint=build_source_fingerprint(
                        "Audit-Rechte ohne Vorankündigung.", ["seg2"]
                    ),
                ),  # fingerprint only
                _make_ref(3, "Unklare SLAs"),  # index=2
            ], risikostufe="Mittel"),

            # Topic 3: ref with title only (unique → enrichment should work)
            _make_cluster("Exit-Risiken", [
                TopicEvidenceRef(source_title="Fehlende Exit-Regelung"),
            ], risikostufe="Hoch"),

            # Topic 4: ref with no provenance at all
            _make_cluster("Compliance-Risiken", [
                TopicEvidenceRef(),  # completely empty → must stay unresolved
            ], risikostufe="Niedrig"),
        ]

        # --- Run enrichment ---
        _simulate_enrichment(raws, clusters)

        # Verify enrichment results
        # Topic 3 ref should have been enriched (unique title match)
        assert clusters[2].evidence_refs[0].source_raw_index == 3
        assert clusters[2].evidence_refs[0].source_fingerprint is not None
        # Topic 4 ref should NOT have been enriched
        assert clusters[3].evidence_refs[0].source_raw_index is None
        assert clusters[3].evidence_refs[0].source_fingerprint is None

        # --- Run resolution ---
        result, stats = resolve_topic_fundstellen(
            clusters, fundstellen,
            raw_index_to_fundstelle=raw_index_to_fs,
            fingerprint_to_fundstelle=fp_to_fs,
        )

        # Topic 1: 2 index matches
        assert len(result[0][1]) == 2
        # Topic 2: 1 fingerprint + 1 index
        assert len(result[1][1]) == 2
        # Topic 3: 1 enriched → should resolve via index
        assert len(result[2][1]) == 1
        # Topic 4: empty ref → 0
        assert len(result[3][1]) == 0

        # Telemetry consistency checks
        assert stats.direct_index_matches >= 3  # At least topics 1 (x2), 2 (x1), 3 (x1 via enrichment)
        assert stats.source_fingerprint_matches >= 0
        assert stats.unresolved_references == 1  # Topic 4 empty ref
        assert stats.refs_missing_provenance == 1  # Topic 4 empty ref
        assert stats.total_references == 6
        assert (
            stats.direct_index_matches
            + stats.source_fingerprint_matches
            + stats.unresolved_references
            + stats.ambiguous_fingerprints
            + stats.duplicate_reference_collisions
            == stats.total_references
        )

    def test_no_final_themes_with_zero_fundstellen(self):
        """Simulate the invariant check: themes with 0 Fundstellen get dropped."""
        # Topic with valid provenance
        ref_good = _make_ref(1, "F1")
        cluster_good = _make_cluster("Good Topic", [ref_good])

        # Topic with empty ref (will have 0 Fundstellen)
        ref_bad = TopicEvidenceRef()
        cluster_bad = _make_cluster("Bad Topic", [ref_bad])

        fs = _make_fundstelle("F1")
        result, stats = resolve_topic_fundstellen(
            [cluster_good, cluster_bad], [fs],
            raw_index_to_fundstelle={0: [fs]},
            fingerprint_to_fundstelle={},
        )

        # Simulate the invariant check from orchestrator
        themes_dropped = 0
        for cluster, linked_fs in result:
            if len(linked_fs) == 0:
                themes_dropped += 1

        assert themes_dropped == 1  # Bad Topic has 0 fundstellen
        assert len(result[0][1]) == 1  # Good Topic has 1


# =============================================================================
# E. NO HIDDEN FALLBACK REGRESSION
# =============================================================================

class TestTelemetrySanity:
    """Task 7: Telemetry fields are correct and consistent."""

    def test_exact_title_fallback_matches_does_not_exist(self):
        """The removed field must not appear in LinkageStats or to_dict."""
        stats = LinkageStats()
        assert not hasattr(stats, "exact_title_fallback_matches")
        assert "exact_title_fallback_matches" not in stats.to_dict()

    def test_refs_missing_provenance_correct(self):
        """Missing provenance is counted correctly for mixed refs."""
        ref_with_index = _make_ref(1, "A")
        ref_with_fp = TopicEvidenceRef(source_fingerprint="abc")
        ref_with_both = TopicEvidenceRef(source_raw_index=0, source_fingerprint="def")
        ref_title_only = TopicEvidenceRef(source_title="Title")
        ref_empty = TopicEvidenceRef()

        cluster = _make_cluster("Topic", [
            ref_with_index, ref_with_fp, ref_with_both,
            ref_title_only, ref_empty,
        ])

        _, stats = resolve_topic_fundstellen(
            [cluster], [],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert stats.refs_missing_provenance == 2  # title_only + empty
        assert stats.total_references == 5

    def test_total_references_equals_sum(self):
        """total_references must equal the sum of all outcome counters."""
        text = "Test clause."
        fp = build_source_fingerprint(text, ["seg1"])
        fs = _make_fundstelle("F", textstelle=text, absatz_ids=["seg1"])

        ref_index = _make_ref(1, "F1")
        ref_fp = TopicEvidenceRef(source_fingerprint=fp)
        ref_empty = TopicEvidenceRef()

        cluster = _make_cluster("Topic", [ref_index, ref_fp, ref_empty])

        _, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={0: [fs]},
            fingerprint_to_fundstelle={fp: [fs]},
        )

        outcomes = (
            stats.direct_index_matches
            + stats.source_fingerprint_matches
            + stats.unresolved_references
            + stats.ambiguous_fingerprints
            + stats.duplicate_reference_collisions
        )
        assert outcomes == stats.total_references

    def test_ambiguous_fingerprints_counted_correctly(self):
        """Ambiguous fingerprint is counted once per attempt, not per candidate."""
        fp = build_source_fingerprint("same", ["seg1"])
        fs_a = _make_fundstelle("A", textstelle="same", absatz_ids=["seg1"])
        fs_b = _make_fundstelle("B", textstelle="same", absatz_ids=["seg1"])

        # Two refs trying the same ambiguous fingerprint
        ref1 = TopicEvidenceRef(source_fingerprint=fp)
        ref2 = TopicEvidenceRef(source_fingerprint=fp)
        cluster = _make_cluster("Topic", [ref1, ref2])

        _, stats = resolve_topic_fundstellen(
            [cluster], [fs_a, fs_b],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={fp: [fs_a, fs_b]},
        )

        assert stats.ambiguous_fingerprints == 2  # Each ref attempt counts
        assert stats.source_fingerprint_matches == 0
        assert stats.unresolved_references == 2


class TestNoHiddenFallback:
    """Task 6: Verify no title-based or fuzzy matching exists in the resolver."""

    def test_resolver_ignores_matching_title(self):
        """Even with a perfectly matching title, resolver must not link without provenance."""
        fs = _make_fundstelle("Perfect Match Title")
        ref = TopicEvidenceRef(source_title="Perfect Match Title")
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1

    def test_resolver_ignores_partial_title_match(self):
        """Partial title overlap must not trigger any matching."""
        fs = _make_fundstelle("Unbeschränkte Haftung des Auftragnehmers")
        ref = TopicEvidenceRef(source_title="Unbeschränkte Haftung")
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1

    def test_resolver_ignores_case_variant_title(self):
        """Case-variant title must not trigger matching without provenance."""
        fs = _make_fundstelle("HAFTUNG")
        ref = TopicEvidenceRef(source_title="haftung")
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs],
            raw_index_to_fundstelle={},
            fingerprint_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_references == 1
