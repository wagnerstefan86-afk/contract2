"""Base interface for discovery passes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig


@dataclass
class RawFinding:
    """A single raw finding from a discovery pass, before consolidation."""
    textstelle: str          # Exact quoted text from the contract
    kategorie: str           # Category label
    kurzbeschreibung: str    # Short description / title
    erklaerung: str          # Detailed explanation
    empfehlung: str          # Recommendation for the Auftragnehmer
    risikostufe: str         # Hoch / Mittel / Niedrig / Hinweis
    segment_ids: list[str] = field(default_factory=list)
    quelle_pass: str = ""    # Which pass found this


# Shared JSON schema instruction appended to all pass prompts
FINDING_JSON_SCHEMA = """
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat diese Felder:
{
  "textstelle": "exaktes Zitat aus dem Vertrag",
  "kategorie": "eine der Kategorien: Informationssicherheit, Datenschutz, Compliance & Regulatorik, Verfügbarkeit & Betrieb, Haftung & Gewährleistung, Audit & Berichtswesen, Vertragsmanagement, Leistungsumfang & Abgrenzung, Personalanforderungen, Geistiges Eigentum, Implizite Pflichten",
  "kurzbeschreibung": "kurzer Titel der Feststellung",
  "erklaerung": "warum dies ein Risiko für den Auftragnehmer ist",
  "empfehlung": "was der Auftragnehmer tun sollte",
  "risikostufe": "Hoch oder Mittel oder Niedrig oder Hinweis"
}

Wenn du KEINE Feststellungen findest, antworte mit einem leeren Array: []
""".strip()


class DiscoveryPass(ABC):
    """Abstract base for a discovery pass."""

    name: str = "Unbekannter Pass"

    @abstractmethod
    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        """Run this pass and return raw findings."""
        ...

    def _parse_findings(self, items: list[dict], pass_name: str, segment_ids: list[str]) -> list[RawFinding]:
        """Parse LLM JSON output into RawFinding objects."""
        findings = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                findings.append(RawFinding(
                    textstelle=str(item.get("textstelle", "")),
                    kategorie=str(item.get("kategorie", "Sonstiges")),
                    kurzbeschreibung=str(item.get("kurzbeschreibung", "")),
                    erklaerung=str(item.get("erklaerung", "")),
                    empfehlung=str(item.get("empfehlung", "")),
                    risikostufe=str(item.get("risikostufe", "Hinweis")),
                    segment_ids=segment_ids,
                    quelle_pass=pass_name,
                ))
            except Exception:
                continue
        return findings
