"""Consolidation: deduplicate and merge findings from all passes.

MVP approach: text-overlap based deduplication. Two findings are considered
duplicates if their textstelle fields are sufficiently similar.
Does NOT aggressively collapse — different risk angles on the same text
are kept as separate findings if their descriptions differ materially.

Produces a merge log for every kept finding so consolidation decisions
are fully transparent and debuggable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.discovery.passes.base import RawFinding

logger = logging.getLogger(__name__)


@dataclass
class ConsolidatedFinding:
    """A finding after consolidation, with merge provenance."""
    finding: RawFinding
    # Merge log: list of raw candidates that were merged into this finding
    merged_from: list[dict] = field(default_factory=list)
    # How many raw candidates contributed (including self)
    raw_count: int = 1

    def merge_info(self) -> dict:
        """Return a serializable summary of the merge provenance."""
        return {
            "anzahl_roh_kandidaten": self.raw_count,
            "ueberlebt_als": "unverändert" if self.raw_count == 1 else "zusammengeführt",
            "zusammengefuehrte_quellen": self.merged_from,
        }


def konsolidiere(findings: list[RawFinding], similarity_threshold: float = 0.75) -> list[ConsolidatedFinding]:
    """Deduplicate findings based on textstelle similarity.

    Returns ConsolidatedFinding objects with full merge provenance.
    """
    if not findings:
        return []

    # Sort by textstelle length descending — prefer longer/richer entries as "primary"
    sorted_findings = sorted(findings, key=lambda f: len(f.textstelle), reverse=True)

    kept: list[ConsolidatedFinding] = []

    for candidate in sorted_findings:
        is_duplicate = False

        for existing in kept:
            # Check textstelle similarity
            text_sim = _similarity(candidate.textstelle, existing.finding.textstelle)

            if text_sim >= similarity_threshold:
                # Same text region. Check if descriptions are materially different.
                desc_sim = _similarity(candidate.kurzbeschreibung, existing.finding.kurzbeschreibung)

                if desc_sim >= 0.6:
                    # Same text + similar description = duplicate. Merge.
                    _merge_into(existing, candidate, text_sim, desc_sim)
                    is_duplicate = True
                    break
                # else: different angle on same text — keep both

        if not is_duplicate:
            cf = ConsolidatedFinding(
                finding=candidate,
                merged_from=[{
                    "quelle_pass": candidate.quelle_pass,
                    "kurzbeschreibung": candidate.kurzbeschreibung,
                    "risikostufe": candidate.risikostufe,
                    "segment_ids": candidate.segment_ids,
                    "status": "primär",
                }],
                raw_count=1,
            )
            kept.append(cf)

    logger.info(
        f"Konsolidierung: {len(findings)} Kandidaten -> {len(kept)} Fundstellen "
        f"({len(findings) - len(kept)} Duplikate zusammengeführt)"
    )
    return kept


def _similarity(a: str, b: str) -> float:
    """Compute normalized text similarity between two strings."""
    if not a or not b:
        return 0.0
    a_norm = a.lower().strip()
    b_norm = b.lower().strip()
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _merge_into(primary: ConsolidatedFinding, secondary: RawFinding,
                text_sim: float, desc_sim: float) -> None:
    """Merge secondary raw finding into primary consolidated finding."""
    pf = primary.finding

    # Record the merge
    primary.merged_from.append({
        "quelle_pass": secondary.quelle_pass,
        "kurzbeschreibung": secondary.kurzbeschreibung,
        "risikostufe": secondary.risikostufe,
        "segment_ids": secondary.segment_ids,
        "text_aehnlichkeit": round(text_sim, 3),
        "beschreibung_aehnlichkeit": round(desc_sim, 3),
        "status": "zusammengeführt",
    })
    primary.raw_count += 1

    # Merge segment IDs
    for sid in secondary.segment_ids:
        if sid not in pf.segment_ids:
            pf.segment_ids.append(sid)

    # Keep longer/richer explanation
    if len(secondary.erklaerung) > len(pf.erklaerung):
        pf.erklaerung = secondary.erklaerung
    if len(secondary.empfehlung) > len(pf.empfehlung):
        pf.empfehlung = secondary.empfehlung

    # Escalate risk level if the duplicate is rated higher
    risk_order = {"Kritisch": 4, "Hoch": 3, "Mittel": 2, "Niedrig": 1, "Hinweis": 0}
    if risk_order.get(secondary.risikostufe, 0) > risk_order.get(pf.risikostufe, 0):
        pf.risikostufe = secondary.risikostufe

    # Track that multiple passes found this
    if secondary.quelle_pass and secondary.quelle_pass not in pf.quelle_pass:
        pf.quelle_pass = f"{pf.quelle_pass}, {secondary.quelle_pass}"

    # Keep longer/richer structured fields
    for attr in ("risiko_detail", "alternativformulierung", "bieterfrage", "verhandlungsargumente"):
        sec_val = getattr(secondary, attr, "")
        pf_val = getattr(pf, attr, "")
        if len(sec_val) > len(pf_val):
            setattr(pf, attr, sec_val)

    # Preserve evidence fields: keep longer/richer scope_text and merge trigger_spans
    sec_scope = getattr(secondary, "scope_text", "") or ""
    pf_scope = getattr(pf, "scope_text", "") or ""
    if len(sec_scope) > len(pf_scope):
        pf.scope_text = secondary.scope_text
        pf.scope_type = secondary.scope_type or pf.scope_type
    if not pf.scope_type and secondary.scope_type:
        pf.scope_type = secondary.scope_type
    # Merge trigger_spans (deduplicated)
    existing_spans = set(pf.trigger_spans) if pf.trigger_spans else set()
    for span in (secondary.trigger_spans or []):
        if span not in existing_spans:
            pf.trigger_spans.append(span)
            existing_spans.add(span)
    # Keep longer evidence_heading_path
    sec_heading = getattr(secondary, "evidence_heading_path", "") or ""
    pf_heading = getattr(pf, "evidence_heading_path", "") or ""
    if len(sec_heading) > len(pf_heading):
        pf.evidence_heading_path = secondary.evidence_heading_path
