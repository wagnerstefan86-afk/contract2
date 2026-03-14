"""Section Splitter — splits extracted text into structured sections/chunks.

Target chunk size: 1500-3000 characters.
Preserves heading paths for context.
Produces normalized text + hash for deduplication.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field


@dataclass
class Section:
    """A structured text section/chunk from a document."""
    index: int
    raw_text: str
    normalized_text: str
    hash: str
    section_type: str  # HEADING, BODY, TABLE, DEFINITION, etc.
    char_count: int
    token_estimate: int
    heading_path: str | None = None
    page_from: int | None = None
    page_to: int | None = None


# Heading patterns for German legal/contract documents
HEADING_PATTERN = re.compile(
    r"^(?:"
    r"(?:§\s*\d+|Artikel\s+\d+|Art\.\s*\d+)"  # § 1, Artikel 1, Art. 1
    r"|(?:\d+\.(?:\d+\.?)*)\s+[A-ZÄÖÜ]"        # 1. Foo, 1.2 Bar, 1.2.3 Baz
    r"|(?:[IVXLC]+\.)\s+[A-ZÄÖÜ]"              # I. Foo, II. Bar
    r"|(?:[A-Z]\.)\s+[A-ZÄÖÜ]"                 # A. Foo, B. Bar
    r")",
    re.MULTILINE,
)

TABLE_INDICATORS = ["---|", "| ", "\t\t", "  |  "]

# Target chunk sizes
MIN_CHUNK = 500
TARGET_CHUNK = 2000
MAX_CHUNK = 3500


def split_into_sections(
    text: str,
    seiten_map: list[dict] | None = None,
) -> list[Section]:
    """Split document text into structured sections.

    Strategy:
    1. Split on headings to get semantic blocks
    2. Merge small blocks, split oversized blocks
    3. Classify section types
    4. Compute page references
    """
    if not text or len(text.strip()) < 10:
        return []

    # Step 1: Split on headings
    raw_blocks = _split_on_headings(text)

    # Step 2: Merge small blocks and split oversized ones
    sized_blocks = _resize_blocks(raw_blocks)

    # Step 3: Build section objects
    sections: list[Section] = []
    char_offset = 0

    for idx, (heading, block_text) in enumerate(sized_blocks):
        normalized = _normalize(block_text)
        section_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        section_type = _classify_section(block_text, heading)
        char_count = len(block_text)
        token_est = char_count // 4  # rough estimate: 4 chars/token

        # Page references
        page_from = None
        page_to = None
        if seiten_map:
            page_from = _char_to_page(char_offset, seiten_map)
            page_to = _char_to_page(char_offset + char_count, seiten_map)

        sections.append(Section(
            index=idx,
            raw_text=block_text,
            normalized_text=normalized,
            hash=section_hash,
            section_type=section_type,
            char_count=char_count,
            token_estimate=token_est,
            heading_path=heading,
            page_from=page_from,
            page_to=page_to,
        ))

        char_offset += char_count

    return sections


def _split_on_headings(text: str) -> list[tuple[str | None, str]]:
    """Split text on heading patterns. Returns list of (heading, body) tuples."""
    blocks: list[tuple[str | None, str]] = []
    lines = text.split("\n")
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and HEADING_PATTERN.match(stripped) and len(stripped) < 200:
            # New heading found — flush current block
            if current_lines:
                block_text = "\n".join(current_lines).strip()
                if block_text:
                    blocks.append((current_heading, block_text))
            current_heading = stripped
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush last block
    if current_lines:
        block_text = "\n".join(current_lines).strip()
        if block_text:
            blocks.append((current_heading, block_text))

    return blocks if blocks else [(None, text)]


def _resize_blocks(blocks: list[tuple[str | None, str]]) -> list[tuple[str | None, str]]:
    """Merge small blocks and split oversized ones to hit target chunk size."""
    result: list[tuple[str | None, str]] = []

    buffer_heading: str | None = None
    buffer_text = ""

    for heading, text in blocks:
        combined = (buffer_text + "\n\n" + text).strip() if buffer_text else text

        if len(combined) < MIN_CHUNK:
            # Too small — buffer it
            buffer_text = combined
            if buffer_heading is None:
                buffer_heading = heading
            continue

        if len(combined) <= MAX_CHUNK:
            # Good size — emit
            result.append((buffer_heading or heading, combined))
            buffer_text = ""
            buffer_heading = None
            continue

        # Oversized — flush buffer first, then split current block
        if buffer_text and len(buffer_text) >= MIN_CHUNK:
            result.append((buffer_heading, buffer_text))
            buffer_text = ""
            buffer_heading = None

        # Split the oversized text
        chunks = _split_oversized(text, TARGET_CHUNK, MAX_CHUNK)
        for i, chunk in enumerate(chunks):
            chunk_heading = heading if i == 0 else f"{heading} (Fortsetzung)" if heading else None
            result.append((chunk_heading, chunk))

        buffer_text = ""
        buffer_heading = None

    # Flush remaining buffer
    if buffer_text.strip():
        result.append((buffer_heading, buffer_text.strip()))

    return result


def _split_oversized(text: str, target: int, max_size: int) -> list[str]:
    """Split oversized text into chunks near target size, preferring paragraph breaks."""
    if len(text) <= max_size:
        return [text]

    chunks: list[str] = []
    paragraphs = re.split(r"\n\s*\n", text)
    current = ""

    for para in paragraphs:
        if current and len(current) + len(para) + 2 > max_size:
            chunks.append(current.strip())
            current = para
        elif not current or len(current) + len(para) + 2 <= target:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            # Current is already near target — start new chunk
            chunks.append(current.strip())
            current = para

    if current.strip():
        chunks.append(current.strip())

    return chunks


def _classify_section(text: str, heading: str | None) -> str:
    """Classify section type based on content heuristics."""
    text_lower = text.lower()

    if heading and len(text.strip().split("\n")) <= 2 and len(text) < 200:
        return "HEADING"

    if any(ind in text for ind in TABLE_INDICATORS):
        return "TABLE"

    if heading:
        heading_lower = heading.lower()
        if any(kw in heading_lower for kw in ["definition", "begriffsbestimmung", "glossar"]):
            return "DEFINITION"
        if any(kw in heading_lower for kw in ["fußnote", "fußnoten", "anmerkung"]):
            return "FOOTNOTE"
        if any(kw in heading_lower for kw in ["anlage", "anhang", "annex"]):
            return "ANNEX_REFERENCE"

    return "BODY"


def _normalize(text: str) -> str:
    """Normalize text for hashing and comparison."""
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def _char_to_page(char_offset: int, seiten_map: list[dict]) -> int | None:
    """Map character offset to page number using seiten_map."""
    for entry in reversed(seiten_map):
        if char_offset >= entry["start"]:
            return entry["seite"]
    return seiten_map[0]["seite"] if seiten_map else None
