"""Early semantic deduplication for cross-pass raw findings.

Two-phase dedup that runs BEFORE consolidation. Operates purely on
RawFinding objects — does not touch the database.

Phase 1 (within-segment):
- Group findings by segment_id
- Remove duplicates with same category + similar description (> 0.85)
- Enforce per-paragraph limit of 2

Phase 2 (cross-segment):
- Group ALL findings by normalized category
- Within each category group, remove findings with description
  similarity > 0.90 across different segments
- Keep highest severity / longest scope_text / earliest segment position
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.discovery.passes.base import RawFinding

logger = logging.getLogger(__name__)

# Severity ordering for tie-breaking
_RISK_ORDER = {"Kritisch": 4, "Hoch": 3, "Mittel": 2, "Niedrig": 1, "Hinweis": 0}

# Similarity threshold for within-segment description comparison
_DESC_SIMILARITY_THRESHOLD = 0.85

# Similarity threshold for cross-segment description comparison (stricter)
_CROSS_SEG_SIMILARITY_THRESHOLD = 0.90

# Maximum findings to keep per paragraph/segment
MAX_FINDINGS_PER_PARAGRAPH = 2


@dataclass
class DedupResult:
    """Result of the early deduplication stage."""
    findings: list[RawFinding]
    raw_before: int
    after_pass_dedup: int
    after_cross_dedup: int
    raw_after: int
    duplicates_removed: int


def _similarity(a: str, b: str) -> float:
    """Compute normalized text similarity between two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _finding_sort_key(f: RawFinding) -> tuple:
    """Sort key: higher severity, longer scope_text, longer description, earlier pass/segment."""
    # Pass ordering: earlier passes get lower numbers (preferred)
    pass_order = 0
    qp = f.quelle_pass.lower()
    if "breit" in qp:
        pass_order = 0
    elif "perspektive" in qp or "perspektivische" in qp:
        pass_order = 1
    elif "implizit" in qp:
        pass_order = 2
    elif "bank" in qp or "regulatorik" in qp:
        pass_order = 3
    else:
        pass_order = 4

    # Segment position: extract numeric suffix for ordering (e.g. "seg-3" -> 3)
    seg_pos = 0
    if f.segment_ids:
        try:
            seg_pos = int(f.segment_ids[0].rsplit("-", 1)[-1])
        except (ValueError, IndexError):
            pass

    return (
        -_RISK_ORDER.get(f.risikostufe, 0),  # higher severity first
        -len(f.scope_text or ""),              # longer scope_text first
        -len(f.erklaerung or f.kurzbeschreibung),  # longer description first
        pass_order,                            # earlier pass first
        seg_pos,                               # earlier segment first
    )


def _normalize_category(cat: str) -> str:
    """Normalize category for comparison (lowercase, strip whitespace)."""
    return cat.strip().lower() if cat else ""


def _dedup_within_segments(findings: list[RawFinding]) -> list[RawFinding]:
    """Phase 1: Remove duplicates within each segment (same paragraph, same pass overlap)."""
    by_segment: dict[str, list[RawFinding]] = defaultdict(list)
    no_segment: list[RawFinding] = []

    for f in findings:
        if f.segment_ids:
            by_segment[f.segment_ids[0]].append(f)
        else:
            no_segment.append(f)

    deduplicated: list[RawFinding] = []

    for seg_id, group in by_segment.items():
        if len(group) <= 1:
            deduplicated.extend(group)
            continue

        group.sort(key=_finding_sort_key)

        kept: list[RawFinding] = []
        for candidate in group:
            is_dup = False
            cand_cat = _normalize_category(candidate.kategorie)

            for existing in kept:
                exist_cat = _normalize_category(existing.kategorie)
                cats_match = (cand_cat == exist_cat
                              or _similarity(cand_cat, exist_cat) > 0.7)
                if not cats_match:
                    continue

                desc_a = candidate.erklaerung or candidate.kurzbeschreibung
                desc_b = existing.erklaerung or existing.kurzbeschreibung
                desc_sim = _similarity(desc_a, desc_b)

                if desc_sim > _DESC_SIMILARITY_THRESHOLD:
                    is_dup = True
                    logger.debug(
                        f"Pass-dedup: '{candidate.kurzbeschreibung[:60]}' "
                        f"({candidate.quelle_pass}) dup of "
                        f"'{existing.kurzbeschreibung[:60]}' "
                        f"({existing.quelle_pass}) — "
                        f"desc_sim={desc_sim:.2f}"
                    )
                    break

            if not is_dup:
                kept.append(candidate)

        # Enforce per-paragraph limit
        if len(kept) > MAX_FINDINGS_PER_PARAGRAPH:
            removed = len(kept) - MAX_FINDINGS_PER_PARAGRAPH
            logger.debug(
                f"Pass-dedup: Segment {seg_id}: {len(kept)} → "
                f"{MAX_FINDINGS_PER_PARAGRAPH} (truncated {removed})"
            )
            kept = kept[:MAX_FINDINGS_PER_PARAGRAPH]

        deduplicated.extend(kept)

    deduplicated.extend(no_segment)
    return deduplicated


def _dedup_across_segments(findings: list[RawFinding]) -> list[RawFinding]:
    """Phase 2: Remove semantically identical findings across different segments.

    Groups by normalized category, then within each group removes findings
    whose descriptions are > 0.90 similar — keeping the best one.
    This targets compliance/regulatory findings that repeat across paragraphs.
    """
    # Group by normalized category
    by_category: dict[str, list[RawFinding]] = defaultdict(list)
    for f in findings:
        by_category[_normalize_category(f.kategorie)].append(f)

    kept_all: list[RawFinding] = []

    for cat, group in by_category.items():
        if len(group) <= 1:
            kept_all.extend(group)
            continue

        # Sort by quality (best first)
        group.sort(key=_finding_sort_key)

        kept: list[RawFinding] = []
        for candidate in group:
            is_dup = False

            for existing in kept:
                # Skip same-segment pairs (already handled by phase 1)
                if (candidate.segment_ids and existing.segment_ids
                        and candidate.segment_ids[0] == existing.segment_ids[0]):
                    continue

                desc_a = candidate.erklaerung or candidate.kurzbeschreibung
                desc_b = existing.erklaerung or existing.kurzbeschreibung
                desc_sim = _similarity(desc_a, desc_b)

                if desc_sim > _CROSS_SEG_SIMILARITY_THRESHOLD:
                    is_dup = True
                    logger.debug(
                        f"Cross-dedup: '{candidate.kurzbeschreibung[:60]}' "
                        f"(seg={candidate.segment_ids[:1]}) dup of "
                        f"'{existing.kurzbeschreibung[:60]}' "
                        f"(seg={existing.segment_ids[:1]}) — "
                        f"desc_sim={desc_sim:.2f}, cat='{cat}'"
                    )
                    break

            if not is_dup:
                kept.append(candidate)

        kept_all.extend(kept)

    return kept_all


def deduplicate_raw_findings(findings: list[RawFinding]) -> DedupResult:
    """Remove semantic duplicates in two phases.

    Phase 1: Within-segment dedup (same paragraph, different passes)
    Phase 2: Cross-segment dedup (same risk across different paragraphs)
    """
    raw_before = len(findings)

    if not findings:
        return DedupResult(
            findings=[], raw_before=0, after_pass_dedup=0,
            after_cross_dedup=0, raw_after=0, duplicates_removed=0,
        )

    # Phase 1: within-segment dedup
    after_phase1 = _dedup_within_segments(findings)
    after_pass_dedup = len(after_phase1)
    logger.info(
        f"Pass-dedup: {raw_before} → {after_pass_dedup} findings "
        f"({raw_before - after_pass_dedup} removed)"
    )

    # Phase 2: cross-segment dedup
    after_phase2 = _dedup_across_segments(after_phase1)
    after_cross_dedup = len(after_phase2)
    logger.info(
        f"Cross-dedup: {after_pass_dedup} → {after_cross_dedup} findings "
        f"({after_pass_dedup - after_cross_dedup} removed)"
    )

    duplicates_removed = raw_before - after_cross_dedup

    return DedupResult(
        findings=after_phase2,
        raw_before=raw_before,
        after_pass_dedup=after_pass_dedup,
        after_cross_dedup=after_cross_dedup,
        raw_after=after_cross_dedup,
        duplicates_removed=duplicates_removed,
    )
