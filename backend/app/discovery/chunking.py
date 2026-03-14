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
    """Split text into paragraph blocks.

    Primary split: blank lines (double newline).
    Secondary split: if a block is very long (>800 chars), split further on
    single newlines that look like paragraph boundaries (e.g. a line starting
    with a number, letter+), section heading pattern, or bullet).
    This improves granularity for PDFs where pdfplumber joins paragraphs
    with single newlines.

    Returns list of {id, text, position} dicts matching the Vertrag.absaetze schema.
    """
    # Split on one or more blank lines
    raw_blocks = re.split(r"\n\s*\n", text)

    # Further split oversized blocks on structural single-newline boundaries
    refined_blocks: list[str] = []
    # Pattern: line starts with a numbered clause (e.g. "1.", "1.1", "(a)", "(1)"),
    # a bullet, or an ALL-CAPS / typical heading line
    _split_pattern = re.compile(
        r"\n(?="
        r"\d+[\.\)]\s"           # "1. " or "1) "
        r"|\(\d+\)\s"           # "(1) "
        r"|\([a-z]\)\s"         # "(a) "
        r"|[A-ZÜÖÄ][A-ZÜÖÄ\s]{4,}\n"  # ALL-CAPS heading line
        r"|- "                  # bullet
        r")"
    )
    for block in raw_blocks:
        stripped = block.strip()
        if not stripped:
            continue
        if len(stripped) > 800:
            sub_blocks = _split_pattern.split(stripped)
            for sb in sub_blocks:
                sb = sb.strip()
                if sb:
                    refined_blocks.append(sb)
        else:
            refined_blocks.append(stripped)

    absaetze = []
    for i, block in enumerate(refined_blocks):
        absaetze.append({
            "id": f"abs-{i}",
            "text": block,
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
