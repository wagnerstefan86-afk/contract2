"""Context enrichment for findings.

After consolidation, enriches each finding with:
- Page number reference (from seiten_map)
- Nearest heading / clause label
- Surrounding context snippet (broader than just the textstelle)
- Structured recommendation fields packaged into a `detail` dict

All data is derived from the contract's stored text, paragraphs, and page map.
Does NOT call the LLM — pure text matching and heuristics.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


def anreichern(
    finding_text: str,
    full_text: str,
    absaetze: list[dict] | None,
    seiten_map: list[dict] | None,
    segment_ids: list[str] | None,
    raw_fields: dict | None = None,
) -> dict:
    """Build an enriched detail dict for a single finding.

    Args:
        finding_text: the textstelle of the finding
        full_text: the contract's full text
        absaetze: the contract's paragraph list
        seiten_map: page-to-char-offset map (from PDF extraction)
        segment_ids: which segments this finding came from
        raw_fields: structured fields from LLM (risiko_detail, etc.)

    Returns:
        dict with enriched context for storage in Fundstelle.detail
    """
    detail: dict = {}

    # 1. Locate the textstelle in the full text
    pos = _find_position(finding_text, full_text)
    detail["position_im_text"] = pos  # char offset or -1

    # 2. Derive page number
    if seiten_map and pos >= 0:
        seite = _seite_fuer_position(pos, seiten_map)
        detail["seite"] = seite
        detail["seite_unsicher"] = False
    elif seiten_map and segment_ids:
        # Approximate from segment position
        seite = _seite_aus_segment(segment_ids, absaetze, seiten_map, full_text)
        detail["seite"] = seite
        detail["seite_unsicher"] = True
    else:
        detail["seite"] = None
        detail["seite_unsicher"] = True

    # 3. Find nearest heading / clause label
    heading = _naechste_ueberschrift(pos, full_text)
    detail["ueberschrift"] = heading

    # 4. Build surrounding context (±500 chars around the match)
    if pos >= 0:
        ctx_start = max(0, pos - 500)
        ctx_end = min(len(full_text), pos + len(finding_text) + 500)
        # Extend to sentence boundaries
        while ctx_start > 0 and full_text[ctx_start] not in ".\n":
            ctx_start -= 1
        while ctx_end < len(full_text) and full_text[ctx_end] not in ".\n":
            ctx_end += 1
        kontext = full_text[ctx_start:ctx_end].strip()
        detail["kontext"] = kontext
        detail["kontext_start"] = ctx_start
        detail["kontext_ende"] = ctx_end
    else:
        # Fallback: use segment text if available
        detail["kontext"] = _kontext_aus_absaetzen(segment_ids, absaetze)
        detail["kontext_start"] = None
        detail["kontext_ende"] = None

    # 5. Paragraph / segment reference
    detail["segment_ids"] = segment_ids or []
    if absaetze and segment_ids:
        # Find which paragraph indices the segments cover
        abs_refs = _absatz_referenzen(segment_ids, absaetze)
        detail["absatz_referenzen"] = abs_refs
    else:
        detail["absatz_referenzen"] = []

    # 6. Structured recommendation fields from LLM
    if raw_fields:
        detail["risiko_detail"] = raw_fields.get("risiko_detail", "")
        detail["alternativformulierung"] = raw_fields.get("alternativformulierung", "")
        detail["bieterfrage"] = raw_fields.get("bieterfrage", "")
        detail["verhandlungsargumente"] = raw_fields.get("verhandlungsargumente", "")
    else:
        detail["risiko_detail"] = ""
        detail["alternativformulierung"] = ""
        detail["bieterfrage"] = ""
        detail["verhandlungsargumente"] = ""

    return detail


def _find_position(textstelle: str, full_text: str) -> int:
    """Find the character offset of textstelle in full_text.

    Tries exact match first, then fuzzy substring match.
    Returns -1 if not found.
    """
    if not textstelle or not full_text:
        return -1

    # Exact match
    idx = full_text.find(textstelle)
    if idx >= 0:
        return idx

    # Try case-insensitive
    idx = full_text.lower().find(textstelle.lower())
    if idx >= 0:
        return idx

    # Try first 100 chars as anchor (LLM may have slightly modified the quote)
    anchor = textstelle[:100]
    idx = full_text.find(anchor)
    if idx >= 0:
        return idx
    idx = full_text.lower().find(anchor.lower())
    if idx >= 0:
        return idx

    # Try first 50 chars
    anchor = textstelle[:50]
    idx = full_text.lower().find(anchor.lower())
    if idx >= 0:
        return idx

    return -1


def _seite_fuer_position(pos: int, seiten_map: list[dict]) -> int | None:
    """Look up which page a character position falls on."""
    for entry in seiten_map:
        if entry["start"] <= pos < entry["ende"]:
            return entry["seite"]
    # Fallback: find closest page
    if seiten_map:
        closest = min(seiten_map, key=lambda e: abs(e["start"] - pos))
        return closest["seite"]
    return None


def _seite_aus_segment(
    segment_ids: list[str],
    absaetze: list[dict] | None,
    seiten_map: list[dict],
    full_text: str,
) -> int | None:
    """Approximate page from segment position."""
    if not segment_ids or not absaetze:
        return None

    # Parse segment ID like "seg-3-5" to get paragraph range
    for sid in segment_ids:
        m = re.match(r"seg-(\d+)-(\d+)", sid)
        if m:
            start_idx = int(m.group(1))
            if start_idx < len(absaetze):
                # Use the paragraph text to find position
                para_text = absaetze[start_idx].get("text", "")[:80]
                pos = full_text.lower().find(para_text.lower())
                if pos >= 0:
                    return _seite_fuer_position(pos, seiten_map)

    # Very rough fallback: middle of document
    if seiten_map:
        return seiten_map[len(seiten_map) // 2]["seite"]
    return None


# Pattern for recognizing heading lines
_HEADING_PATTERN = re.compile(
    r"^(?:"
    r"\d+[\.\)]\s+\S"           # "1. Title" or "1) Title"
    r"|\d+\.\d+[\.\s]\s*\S"    # "1.1 Title" or "1.1. Title"
    r"|§\s*\d+"                 # "§ 1"
    r"|Artikel\s+\d+"           # "Artikel 1"
    r"|Abschnitt\s+\d+"         # "Abschnitt 1"
    r"|Präambel"                # "Präambel"
    r"|Anlage\s"                # "Anlage 1"
    r"|[A-ZÜÖÄ][A-ZÜÖÄ\s]{4,}$" # ALL-CAPS line
    r"|[IVXLC]+\.\s+\S"        # Roman numeral headings "I. Title"
    r")",
    re.MULTILINE,
)


def _naechste_ueberschrift(pos: int, full_text: str) -> str | None:
    """Find the nearest heading/clause label before the given position."""
    if pos < 0 or not full_text:
        return None

    # Search backwards from pos for the nearest heading-like line
    text_before = full_text[:pos]
    lines = text_before.split("\n")

    for line in reversed(lines):
        stripped = line.strip()
        if stripped and _HEADING_PATTERN.match(stripped):
            # Clean up and return
            return stripped[:120]  # Cap length

    return None


def _kontext_aus_absaetzen(
    segment_ids: list[str] | None,
    absaetze: list[dict] | None,
) -> str:
    """Build context from paragraph data when textstelle position is unknown."""
    if not segment_ids or not absaetze:
        return ""

    collected = []
    for sid in segment_ids:
        m = re.match(r"seg-(\d+)-(\d+)", sid)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            for i in range(max(0, start), min(end + 1, len(absaetze))):
                collected.append(absaetze[i].get("text", ""))

    return "\n\n".join(collected)[:2000]  # Cap at 2000 chars


def _absatz_referenzen(
    segment_ids: list[str],
    absaetze: list[dict],
) -> list[str]:
    """Return human-readable paragraph references from segment IDs."""
    refs = []
    for sid in segment_ids:
        m = re.match(r"seg-(\d+)-(\d+)", sid)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if start == end:
                refs.append(f"Absatz {start + 1}")
            else:
                refs.append(f"Absätze {start + 1}-{end + 1}")
    return refs
