"""Section Splitter — splits extracted text into structured sections/chunks.

Prefers paragraph / clause-block boundaries so that each section represents
one contractual paragraph or a small group of closely related short paragraphs
within the same numbered clause.

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

# Pattern for numbered sub-items that start a new contractual paragraph
# e.g. "(1)", "(a)", "(i)", "(aa)"
NUMBERED_ITEM_PATTERN = re.compile(
    r"^\s*\((?:\d+|[a-z]+|[ivxlc]+)\)\s",
    re.MULTILINE,
)

TABLE_INDICATORS = ["---|", "| ", "\t\t", "  |  "]

# Chunk size thresholds — lowered MIN to let individual paragraphs stand alone
MIN_CHUNK = 120          # individual paragraphs can be short
MERGE_THRESHOLD = 300    # only merge paragraphs below this if they share a clause
TARGET_CHUNK = 2000
MAX_CHUNK = 4000


def split_into_sections(
    text: str,
    seiten_map: list[dict] | None = None,
) -> list[Section]:
    """Split document text into structured sections.

    Strategy:
    1. Split on headings to get semantic blocks
    2. Within each heading block, split on paragraph boundaries
    3. Merge only very short paragraphs within the same clause
    4. Split oversized paragraphs if technically unavoidable
    5. Classify section types
    6. Compute page references
    """
    if not text or len(text.strip()) < 10:
        return []

    # Step 1: Split on headings
    raw_blocks = _split_on_headings(text)

    # Step 2: Split heading blocks into paragraphs, then merge/resize
    paragraph_blocks = _split_into_paragraphs(raw_blocks)

    # Step 3: Build section objects
    sections: list[Section] = []
    char_offset = 0

    for idx, (heading, block_text) in enumerate(paragraph_blocks):
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


def _split_into_paragraphs(
    blocks: list[tuple[str | None, str]],
) -> list[tuple[str | None, str]]:
    """Split each heading block into paragraph-level chunks.

    Within a heading block, paragraphs are separated by blank lines.
    Short paragraphs within the same clause are merged to avoid
    excessively tiny sections.  Oversized paragraphs are split only
    if they exceed MAX_CHUNK.
    """
    result: list[tuple[str | None, str]] = []

    for heading, block_text in blocks:
        # Split on blank lines to get raw paragraphs
        raw_paras = re.split(r"\n\s*\n", block_text)
        raw_paras = [p.strip() for p in raw_paras if p.strip()]

        if not raw_paras:
            continue

        if len(raw_paras) == 1:
            # Single paragraph — keep as-is or split if oversized
            para = raw_paras[0]
            if len(para) > MAX_CHUNK:
                for chunk in _split_oversized(para, TARGET_CHUNK, MAX_CHUNK):
                    result.append((heading, chunk))
            else:
                result.append((heading, para))
            continue

        # Multiple paragraphs — merge very short ones within same clause
        merged = _merge_short_paragraphs(raw_paras, heading)
        for para_text in merged:
            if len(para_text) > MAX_CHUNK:
                for chunk in _split_oversized(para_text, TARGET_CHUNK, MAX_CHUNK):
                    result.append((heading, chunk))
            else:
                result.append((heading, para_text))

    # Final pass: merge any tiny trailing sections (<MIN_CHUNK) with predecessor
    if len(result) > 1:
        compacted: list[tuple[str | None, str]] = [result[0]]
        for heading, text in result[1:]:
            prev_heading, prev_text = compacted[-1]
            if len(text) < MIN_CHUNK and len(prev_text) + len(text) + 2 <= MAX_CHUNK:
                compacted[-1] = (prev_heading, prev_text + "\n\n" + text)
            else:
                compacted.append((heading, text))
        result = compacted

    return result


def _merge_short_paragraphs(
    paragraphs: list[str],
    heading: str | None,
) -> list[str]:
    """Merge very short paragraphs that belong to the same clause block.

    Only merges paragraphs shorter than MERGE_THRESHOLD if:
    - they don't start with a numbered item pattern (which indicates a new clause point)
    - the combined size stays under TARGET_CHUNK
    """
    result: list[str] = []
    buffer = ""

    for para in paragraphs:
        is_new_item = bool(NUMBERED_ITEM_PATTERN.match(para))

        if not buffer:
            buffer = para
            continue

        # If the buffered text is short AND the new para doesn't start a new
        # numbered item AND the combined size is reasonable, merge them.
        if (
            len(buffer) < MERGE_THRESHOLD
            and not is_new_item
            and len(buffer) + len(para) + 2 <= TARGET_CHUNK
        ):
            buffer = buffer + "\n\n" + para
        else:
            result.append(buffer)
            buffer = para

    if buffer:
        result.append(buffer)

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
