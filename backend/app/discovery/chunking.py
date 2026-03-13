"""Semantic-ish segmentation for contract text.

Key design: does NOT depend on headings. Splits by paragraph blocks,
then builds overlapping windows of neighboring segments for context.
Each segment gets a stable ID for traceability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Segment:
    """One text segment with its paragraph range and stable ID."""
    id: str
    text: str
    absatz_start: int  # inclusive
    absatz_ende: int   # inclusive
    # The full window text including neighbor overlap
    fenster_text: str = ""


def text_in_absaetze(text: str) -> list[dict]:
    """Split text into paragraph blocks. A paragraph is separated by blank lines.

    Returns list of {id, text, position} dicts matching the Vertrag.absaetze schema.
    """
    # Split on one or more blank lines
    raw_blocks = re.split(r"\n\s*\n", text)
    absaetze = []
    for i, block in enumerate(raw_blocks):
        cleaned = block.strip()
        if cleaned:
            absaetze.append({
                "id": f"abs-{i}",
                "text": cleaned,
                "position": i,
            })
    return absaetze


def absaetze_zu_segmente(
    absaetze: list[dict],
    group_size: int = 3,
    overlap: int = 1,
) -> list[Segment]:
    """Group paragraphs into segments with overlap.

    Args:
        absaetze: list of paragraph dicts from text_in_absaetze()
        group_size: how many paragraphs per segment
        overlap: how many paragraphs overlap with the next segment

    Returns a list of Segments, each with a window that includes
    +/- 1 neighboring segment's paragraphs for context.
    """
    if not absaetze:
        return []

    segments: list[Segment] = []
    step = max(1, group_size - overlap)

    for start in range(0, len(absaetze), step):
        end = min(start + group_size, len(absaetze))
        group = absaetze[start:end]

        seg_text = "\n\n".join(a["text"] for a in group)
        seg = Segment(
            id=f"seg-{start}-{end - 1}",
            text=seg_text,
            absatz_start=start,
            absatz_ende=end - 1,
        )
        segments.append(seg)

        if end >= len(absaetze):
            break

    # Build window text: current segment + neighbor context
    for i, seg in enumerate(segments):
        parts = []
        if i > 0:
            parts.append(f"[Vorheriger Kontext]\n{segments[i - 1].text}")
        parts.append(f"[Aktueller Abschnitt: {seg.id}]\n{seg.text}")
        if i < len(segments) - 1:
            parts.append(f"[Nachfolgender Kontext]\n{segments[i + 1].text}")
        seg.fenster_text = "\n\n---\n\n".join(parts)

    return segments
