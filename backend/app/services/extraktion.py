"""Text extraction and normalization from uploaded contract files.

MVP: supports .txt, .pdf (via pdfplumber), .docx (via python-docx).
Falls back to treating file as UTF-8 text if extension is unknown.
"""

import os
import re


def text_aus_datei(dateipfad: str) -> str:
    """Extract plain text from a file. Returns normalized text."""
    ext = os.path.splitext(dateipfad)[1].lower()

    if ext == ".pdf":
        raw = _extract_pdf(dateipfad)
    elif ext in (".docx", ".doc"):
        raw = _extract_docx(dateipfad)
    else:
        # Fallback: read as plain text
        with open(dateipfad, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()

    return normalisiere_text(raw)


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


def _extract_pdf(dateipfad: str) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(dateipfad) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)
    return "\n\n".join(pages)


def _extract_docx(dateipfad: str) -> str:
    from docx import Document

    doc = Document(dateipfad)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)
