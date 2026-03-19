"""Tests for the structured evidence linkage model (TopicEvidenceRef).

Covers:
- TopicEvidenceRef construction from LLM output
- Evidence ref integrity through refinement pipeline
- resolve_topic_fundstellen() with direct index and exact title strategies
- LinkageStats correctness
- Deduplication preserves evidence_refs atomicity
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

import pytest

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


# --- Helpers ---

def _make_ref(nr: int, title: str = "") -> TopicEvidenceRef:
    return TopicEvidenceRef(
        finding_nr=nr,
        source_title=title or f"Finding {nr}",
        source_raw_index=nr - 1,
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


# --- TopicEvidenceRef construction ---

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


# --- _parse_clusters builds TopicEvidenceRef ---

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
        assert c.evidence_refs[0].source_title == "Titel A"
        assert c.evidence_refs[0].source_raw_index == 0  # 1-based → 0-based
        assert c.evidence_refs[1].finding_nr == 3
        assert c.evidence_refs[1].source_raw_index == 2

    def test_missing_finding_nr(self):
        """Evidence with title but no finding_nr still creates a ref."""
        items = [
            {
                "topic_title": "Test",
                "category": "Cat",
                "risk_level": "Mittel",
                "beschreibung": "Desc",
                "evidence": [
                    {"ursprungstitel": "Only Title"},
                ],
            }
        ]
        clusters = _parse_clusters(items)
        assert clusters is not None
        ref = clusters[0].evidence_refs[0]
        assert ref.finding_nr is None
        assert ref.source_title == "Only Title"
        assert ref.source_raw_index is None

    def test_empty_evidence_skipped(self):
        """Evidence with no title and no finding_nr is skipped."""
        items = [
            {
                "topic_title": "Test",
                "category": "Cat",
                "risk_level": "Mittel",
                "beschreibung": "Desc",
                "evidence": [
                    {"ursprungstitel": "", "finding_nr": None},
                    {},
                ],
            }
        ]
        clusters = _parse_clusters(items)
        assert clusters is not None
        assert len(clusters[0].evidence_refs) == 0


# --- Refinement functions preserve evidence_refs ---

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
        """Same finding_nr in two clusters → kept in higher-risk cluster."""
        ref1 = _make_ref(1, "Finding 1")
        ref1_dup = _make_ref(1, "Finding 1")
        ref2 = _make_ref(2, "Finding 2")

        c1 = _make_cluster("High Risk", [ref1, ref2], risikostufe="Hoch")
        c2 = _make_cluster("Low Risk", [ref1_dup], risikostufe="Niedrig")

        result = _deduplicate_evidence([c1, c2])

        # c1 keeps finding_nr=1, c2 loses it
        assert len(result[0].evidence_refs) == 2
        assert len(result[1].evidence_refs) == 0

    def test_dedup_by_title_when_no_nr(self):
        """Same source_title, no finding_nr → deduped by title."""
        ref_a = TopicEvidenceRef(source_title="Same Title")
        ref_b = TopicEvidenceRef(source_title="Same Title")
        ref_c = TopicEvidenceRef(source_title="Different")

        c1 = _make_cluster("A", [ref_a, ref_c], risikostufe="Hoch")
        c2 = _make_cluster("B", [ref_b], risikostufe="Niedrig")

        result = _deduplicate_evidence([c1, c2])

        assert len(result[0].evidence_refs) == 2
        assert len(result[1].evidence_refs) == 0


# --- resolve_topic_fundstellen ---

class TestResolveTopicFundstellen:
    def test_direct_index_resolution(self):
        """Strategy 1: resolve via raw_index_to_fundstelle mapping."""
        fs0 = _make_fundstelle("Finding 1")
        fs1 = _make_fundstelle("Finding 2")

        cluster = _make_cluster("Topic", [
            _make_ref(1, "Finding 1"),
            _make_ref(2, "Finding 2"),
        ])

        raw_map = {0: [fs0], 1: [fs1]}
        result, stats = resolve_topic_fundstellen(
            [cluster], [fs0, fs1], raw_index_to_fundstelle=raw_map,
        )

        assert len(result) == 1
        assert len(result[0][1]) == 2
        assert stats.direct_index_matches == 2
        assert stats.exact_title_matches == 0
        assert stats.unresolved_evidences == 0

    def test_exact_title_fallback(self):
        """Strategy 2: resolve via exact kurzbeschreibung match."""
        fs = _make_fundstelle("Haftungsklausel ohne Deckelung")

        ref = TopicEvidenceRef(
            finding_nr=None,
            source_title="Haftungsklausel ohne Deckelung",
            source_raw_index=None,
        )
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs], raw_index_to_fundstelle={},
        )

        assert len(result[0][1]) == 1
        assert stats.direct_index_matches == 0
        assert stats.exact_title_matches == 1

    def test_unresolved_evidence(self):
        """No match → counted as unresolved, not linked."""
        ref = _make_ref(99, "Nonexistent")
        cluster = _make_cluster("Topic", [ref])

        result, stats = resolve_topic_fundstellen(
            [cluster], [], raw_index_to_fundstelle={},
        )

        assert len(result[0][1]) == 0
        assert stats.unresolved_evidences == 1
        assert stats.total_evidences == 1

    def test_duplicate_prevention(self):
        """Same Fundstelle cannot be assigned to two topics."""
        fs = _make_fundstelle("Finding 1")

        c1 = _make_cluster("Topic A", [_make_ref(1, "Finding 1")])
        c2 = _make_cluster("Topic B", [_make_ref(1, "Finding 1")])

        raw_map = {0: [fs]}
        result, stats = resolve_topic_fundstellen(
            [c1, c2], [fs], raw_index_to_fundstelle=raw_map,
        )

        # First topic gets it, second cannot resolve (already assigned)
        assert len(result[0][1]) == 1
        assert len(result[1][1]) == 0
        assert stats.direct_index_matches == 1
        # Second ref is unresolved because the only candidate was already assigned
        assert stats.unresolved_evidences == 1

    def test_fingerprint_filled_on_resolution(self):
        """source_fingerprint is populated after successful resolution."""
        fs = _make_fundstelle("Finding 1", textstelle="contract clause text")

        ref = _make_ref(1, "Finding 1")
        assert ref.source_fingerprint is None

        cluster = _make_cluster("Topic", [ref])
        raw_map = {0: [fs]}

        resolve_topic_fundstellen(
            [cluster], [fs], raw_index_to_fundstelle=raw_map,
        )

        assert ref.source_fingerprint is not None
        assert len(ref.source_fingerprint) == 16  # sha256[:16]

    def test_mixed_strategies(self):
        """Some refs resolve by index, others by title."""
        fs0 = _make_fundstelle("Finding A", textstelle="text a")
        fs1 = _make_fundstelle("Finding B", textstelle="text b")

        ref_by_index = _make_ref(1, "Finding A")
        ref_by_title = TopicEvidenceRef(
            source_title="Finding B",
            source_raw_index=None,
        )

        cluster = _make_cluster("Topic", [ref_by_index, ref_by_title])
        raw_map = {0: [fs0]}

        result, stats = resolve_topic_fundstellen(
            [cluster], [fs0, fs1], raw_index_to_fundstelle=raw_map,
        )

        assert len(result[0][1]) == 2
        assert stats.direct_index_matches == 1
        assert stats.exact_title_matches == 1


# --- LinkageStats ---

class TestLinkageStats:
    def test_to_dict_uses_correct_field_names(self):
        stats = LinkageStats(
            direct_index_matches=5,
            exact_title_matches=2,
            unresolved_evidences=1,
            duplicate_references=0,
            total_evidences=8,
        )
        d = stats.to_dict()
        assert "exact_title_matches" in d
        assert "fingerprint_matches" not in d
        assert d["exact_title_matches"] == 2
        assert d["direct_index_matches"] == 5


# --- _build_fingerprint ---

class TestBuildFingerprint:
    def test_deterministic(self):
        fp1 = _build_fingerprint("some text", ["seg1", "seg2"])
        fp2 = _build_fingerprint("some text", ["seg1", "seg2"])
        assert fp1 == fp2

    def test_different_text_different_fp(self):
        fp1 = _build_fingerprint("text a", ["seg1"])
        fp2 = _build_fingerprint("text b", ["seg1"])
        assert fp1 != fp2

    def test_segment_order_independent(self):
        fp1 = _build_fingerprint("text", ["seg2", "seg1"])
        fp2 = _build_fingerprint("text", ["seg1", "seg2"])
        assert fp1 == fp2
