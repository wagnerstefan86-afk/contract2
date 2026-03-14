"""Text extraction and normalization from uploaded contract files.

MVP: supports .txt, .pdf (via pdfplumber), .docx (via python-docx).
Falls back to treating file as UTF-8 text if extension is unknown.

Also builds a page map (seiten_map) for PDFs so findings can reference
approximate page numbers.
"""

import os
import re
from dataclasses import dataclass, field


@dataclass
class ExtraktionErgebnis:
    """Result of text extraction with page map."""
    text: str
    # Page map: list of {seite: int, start: int, ende: int} char offsets
    seiten_map: list[dict] = field(default_factory=list)


def text_aus_datei(dateipfad: str) -> str:
    """Extract plain text from a file. Returns normalized text."""
    ergebnis = extrahiere_mit_seitenmap(dateipfad)
    return ergebnis.text


def extrahiere_mit_seitenmap(dateipfad: str) -> ExtraktionErgebnis:
    """Extract text with page-level character offsets (for PDFs)."""
    ext = os.path.splitext(dateipfad)[1].lower()

    if ext == ".pdf":
        return _extract_pdf_with_pages(dateipfad)
    elif ext in (".docx", ".doc"):
        raw = _extract_docx(dateipfad)
        return ExtraktionErgebnis(text=normalisiere_text(raw))
    else:
        with open(dateipfad, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        return ExtraktionErgebnis(text=normalisiere_text(raw))


def normalisiere_text(text: str) -> str:
    """Normalize whitespace, bullet artifacts, repeated blank lines."""
    # Replace common bullet/list artifacts
    text = re.sub(r"[•●■◦▪►▸‣⁃]", "-", text)
    # Normalize various dash types to standard hyphen-minus
    text = re.sub(r"[–—―]", "-", text)
    # Collapse runs of whitespace within lines (but keep newlines)
    text = re.sub(r"[^\S\n]+", " ", text)
    # Remove trailing whitespace per line
    text = re.sub(r" +\n", "\n", text)
    # Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace
    text = text.strip()
    return text


def _extract_pdf_with_pages(dateipfad: str) -> ExtraktionErgebnis:
    """Extract PDF text and build a page-to-character-offset map."""
    import pdfplumber

    page_texts: list[str] = []
    with pdfplumber.open(dateipfad) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            page_texts.append(page_text if page_text else "")

    raw = "\n\n".join(page_texts)
    normalized = normalisiere_text(raw)

    # Build seiten_map by finding where each page's content starts in normalized text
    seiten_map: list[dict] = []
    search_from = 0
    for i, pt in enumerate(page_texts):
        if not pt or not pt.strip():
            continue
        # Use first 80 chars of page as anchor to find offset in normalized text
        anchor = normalisiere_text(pt)[:80]
        if not anchor:
            continue
        idx = normalized.find(anchor, max(0, search_from - 200))
        if idx == -1:
            # Fallback: approximate based on proportional position
            idx = int(len(normalized) * i / max(len(page_texts), 1))
        seiten_map.append({
            "seite": i + 1,
            "start": idx,
            "ende": idx + len(normalisiere_text(pt)),
        })
        search_from = idx + len(anchor)

    return ExtraktionErgebnis(text=normalized, seiten_map=seiten_map)


def _extract_docx(dateipfad: str) -> str:
    from docx import Document

    doc = Document(dateipfad)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)
