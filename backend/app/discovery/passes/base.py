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
    # Structured recommendation fields (populated by LLM when available)
    risiko_detail: str = ""          # Specific risk: what, for whom, consequence
    alternativformulierung: str = "" # Suggested alternative contract wording
    bieterfrage: str = ""            # Question to raise during bid/negotiation
    verhandlungsargumente: str = ""  # Arguments for negotiation


# Shared recall-maximizing instruction block appended to all pass prompts
RECALL_INSTRUCTION = """
KRITISCH — RECALL-MAXIMIERUNG:
- Dein Ziel ist es, MÖGLICHST VIELE potenziell problematische Stellen zu finden, nicht nur die "wichtigsten" oder "offensichtlichsten".
- Erstelle KEINE priorisierte Kurzliste. Erstelle eine VOLLSTÄNDIGE Liste.
- Auch Stellen mit niedrigem Risiko oder bloßem Hinweischarakter MÜSSEN aufgenommen werden.
- Wenn eine Formulierung auch nur MÖGLICHERWEISE ein Risiko darstellt, nimm sie auf.
- Fehlende Regelungen (z.B. keine Haftungsobergrenze) sind AUCH Fundstellen.
- Einseitige Rechte des Auftraggebers sind IMMER eine Fundstelle.
- Verweise auf externe Dokumente, Anlagen oder Standards sind IMMER eine Fundstelle.
- Vage Formulierungen ("angemessen", "marktüblich", "Stand der Technik") sind IMMER eine Fundstelle.
- Liefere lieber 20 Fundstellen als 5. Überinklusion wird NICHT bestraft, Unterinklusion SCHON.
""".strip()

# Shared JSON schema instruction
FINDING_JSON_SCHEMA = """
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat diese Felder:
{
  "textstelle": "exaktes Zitat aus dem Vertrag (möglichst wörtlich, MINDESTENS ein vollständiger Satz, besser der ganze relevante Absatz)",
  "kategorie": "eine der Kategorien: Informationssicherheit, Datenschutz, Compliance & Regulatorik, Verfügbarkeit & Betrieb, Haftung & Gewährleistung, Audit & Berichtswesen, Vertragsmanagement, Leistungsumfang & Abgrenzung, Personalanforderungen, Geistiges Eigentum, Implizite Pflichten",
  "kurzbeschreibung": "kurzer Titel der Feststellung",
  "erklaerung": "KONKRETE Erklärung: (1) Was genau ist das Risiko? (2) Warum ist das für einen IT-Dienstleister/Auftragnehmer problematisch? (3) Welche operative, vertragliche oder regulatorische Konsequenz droht konkret? Keine generischen Phrasen.",
  "empfehlung": "Konkrete Handlungsempfehlung für den Auftragnehmer",
  "risikostufe": "Hoch oder Mittel oder Niedrig oder Hinweis",
  "risiko_detail": "Präzise Einordnung: Welche konkrete Gefahr droht (z.B. unbegrenzte Kostenpflicht, Vertragsstrafe, regulatorisches Bußgeld, operative Überlastung)? Für wen genau? In welchem Szenario wird das Risiko schlagend?",
  "alternativformulierung": "Vorschlag für eine faire Alternativformulierung der Vertragsklausel, die das Risiko für den AN begrenzt, ohne den Vertragszweck zu gefährden. Konkreter Textvorschlag.",
  "bieterfrage": "Frage, die der Bieter/AN im Vergabeverfahren oder in der Verhandlung stellen sollte, um Klarheit zu schaffen. Kurz und präzise.",
  "verhandlungsargumente": "1-3 sachliche Argumente, warum eine Anpassung dieser Klausel auch im Interesse des AG liegt oder marktüblich wäre."
}

Wenn du KEINE Feststellungen findest, antworte mit einem leeren Array: []
ABER: Es ist extrem unwahrscheinlich, dass ein Vertragsabschnitt KEINE Fundstelle enthält. Prüfe nochmals, bevor du ein leeres Array zurückgibst.
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
                    risiko_detail=str(item.get("risiko_detail", "")),
                    alternativformulierung=str(item.get("alternativformulierung", "")),
                    bieterfrage=str(item.get("bieterfrage", "")),
                    verhandlungsargumente=str(item.get("verhandlungsargumente", "")),
                ))
            except Exception:
                continue
        return findings
