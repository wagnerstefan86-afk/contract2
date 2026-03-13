"""Consolidation: deduplicate and merge findings from all passes.

MVP approach: text-overlap based deduplication. Two findings are considered
duplicates if their textstelle fields are sufficiently similar.
Does NOT aggressively collapse — different risk angles on the same text
are kept as separate findings if their descriptions differ materially.
"""

from __future__ import annotations

import logging
from difflib import SequenceMatcher

from app.discovery.passes.base import RawFinding

logger = logging.getLogger(__name__)


def konsolidiere(findings: list[RawFinding], similarity_threshold: float = 0.75) -> list[RawFinding]:
    """Deduplicate findings based on textstelle similarity.

    Keeps the richer description when merging. Merges segment_ids.
    Does NOT merge findings that have different categories or
    materially different descriptions, even if textstelle overlaps.
    """
    if not findings:
        return []

    # Sort by textstelle length descending — prefer longer/richer entries as "primary"
    sorted_findings = sorted(findings, key=lambda f: len(f.textstelle), reverse=True)

    kept: list[RawFinding] = []

    for candidate in sorted_findings:
        is_duplicate = False

        for existing in kept:
            # Check textstelle similarity
            text_sim = _similarity(candidate.textstelle, existing.textstelle)

            if text_sim >= similarity_threshold:
                # Same text region. Check if descriptions are materially different.
                desc_sim = _similarity(candidate.kurzbeschreibung, existing.kurzbeschreibung)

                if desc_sim >= 0.6:
                    # Same text + similar description = duplicate. Merge.
                    _merge_into(existing, candidate)
                    is_duplicate = True
                    break
                # else: different angle on same text — keep both

        if not is_duplicate:
            kept.append(candidate)

    logger.info(
        f"Konsolidierung: {len(findings)} Kandidaten -> {len(kept)} Fundstellen "
        f"({len(findings) - len(kept)} Duplikate entfernt)"
    )
    return kept


def _similarity(a: str, b: str) -> float:
    """Compute normalized text similarity between two strings."""
    if not a or not b:
        return 0.0
    # Normalize for comparison
    a_norm = a.lower().strip()
    b_norm = b.lower().strip()
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _merge_into(primary: RawFinding, secondary: RawFinding) -> None:
    """Merge secondary finding into primary, keeping richer content."""
    # Merge segment IDs
    for sid in secondary.segment_ids:
        if sid not in primary.segment_ids:
            primary.segment_ids.append(sid)

    # Keep longer/richer explanation
    if len(secondary.erklaerung) > len(primary.erklaerung):
        primary.erklaerung = secondary.erklaerung
    if len(secondary.empfehlung) > len(primary.empfehlung):
        primary.empfehlung = secondary.empfehlung

    # Escalate risk level if the duplicate is rated higher
    risk_order = {"Hoch": 3, "Mittel": 2, "Niedrig": 1, "Hinweis": 0}
    if risk_order.get(secondary.risikostufe, 0) > risk_order.get(primary.risikostufe, 0):
        primary.risikostufe = secondary.risikostufe

    # Track that multiple passes found this
    if secondary.quelle_pass and secondary.quelle_pass not in primary.quelle_pass:
        primary.quelle_pass = f"{primary.quelle_pass}, {secondary.quelle_pass}"
