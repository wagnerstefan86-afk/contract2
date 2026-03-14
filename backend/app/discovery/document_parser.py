"""Document Parser — extracts text from uploaded documents and classifies document type.

Wraps the existing extraction service and adds document classification via
heuristic keyword matching on filenames and content.
"""

from __future__ import annotations

import hashlib
import logging
import os

from app.services.extraktion import extrahiere_mit_seitenmap, ExtraktionErgebnis
from app.models.enums import DocumentType

logger = logging.getLogger(__name__)

# Heuristic mapping: filename/content keywords → document type
FILENAME_HINTS: list[tuple[list[str], DocumentType]] = [
    (["hauptvertrag", "rahmenvertrag", "dienstleistungsvertrag", "outsourcing",
      "main_contract", "master_agreement"], DocumentType.MAIN_CONTRACT),
    (["agb", "allgemeine geschäftsbedingungen", "terms", "conditions",
      "terms_and_conditions"], DocumentType.TERMS_AND_CONDITIONS),
    (["sla", "service_level", "servicelevel"], DocumentType.SLA),
    (["leistungsbeschreibung", "service_description", "leistungsschein",
      "leistungsverzeichnis"], DocumentType.SERVICE_DESCRIPTION),
    (["preis", "pricing", "vergütung", "entgelt", "preisblatt"], DocumentType.PRICING),
    (["avv", "dpa", "auftragsverarbeitung", "datenschutz"], DocumentType.DPA),
    (["tom", "technische und organisatorische"], DocumentType.TOM),
    (["sicherheit", "security", "informationssicherheit"], DocumentType.SECURITY_APPENDIX),
    (["subunternehmer", "subprocessor", "unterauftragnehmer"], DocumentType.SUBPROCESSOR_LIST),
    (["exit", "transition", "herausgabe"], DocumentType.EXIT_APPENDIX),
    (["anlage", "anhang", "annex", "appendix"], DocumentType.ANNEX),
]

# Document type priority: higher = more important for analysis
DOCUMENT_ROLE_RANKS: dict[DocumentType, int] = {
    DocumentType.MAIN_CONTRACT: 100,
    DocumentType.SECURITY_APPENDIX: 90,
    DocumentType.SLA: 85,
    DocumentType.SERVICE_DESCRIPTION: 80,
    DocumentType.TOM: 75,
    DocumentType.EXIT_APPENDIX: 70,
    DocumentType.TERMS_AND_CONDITIONS: 60,
    DocumentType.DPA: 55,
    DocumentType.SUBPROCESSOR_LIST: 50,
    DocumentType.PRICING: 40,
    DocumentType.ANNEX: 30,
    DocumentType.OTHER: 10,
}


def parse_document(file_path: str) -> ExtraktionErgebnis:
    """Extract text and page map from a document file.

    Delegates to the existing extraction service.
    """
    return extrahiere_mit_seitenmap(file_path)


def compute_sha256(file_path: str) -> str:
    """Compute SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def classify_document(filename: str, text_preview: str = "") -> tuple[DocumentType, int]:
    """Classify document type from filename and text preview.

    Returns (DocumentType, role_rank).
    """
    fn_lower = filename.lower()
    text_lower = text_preview[:3000].lower() if text_preview else ""
    combined = fn_lower + " " + text_lower

    for keywords, doc_type in FILENAME_HINTS:
        for kw in keywords:
            if kw in combined:
                rank = DOCUMENT_ROLE_RANKS.get(doc_type, 10)
                return doc_type, rank

    return DocumentType.OTHER, DOCUMENT_ROLE_RANKS[DocumentType.OTHER]


def detect_language(text: str) -> str:
    """Simple heuristic language detection (de/en)."""
    text_sample = text[:5000].lower()
    german_indicators = ["der", "die", "das", "und", "oder", "ist", "wird", "nicht", "für", "mit"]
    english_indicators = ["the", "and", "or", "is", "will", "not", "for", "with", "shall", "may"]

    de_count = sum(1 for w in german_indicators if f" {w} " in text_sample)
    en_count = sum(1 for w in english_indicators if f" {w} " in text_sample)

    return "de" if de_count >= en_count else "en"
