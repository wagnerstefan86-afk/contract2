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


# Shared quality rules appended to all pass prompts
QUALITAETS_REGELN = """
REGEL 1 – FINDINGS SPARSAM ERZEUGEN
Erstelle nur ein neues Finding, wenn wirklich ein eigener Risikokern vorliegt.
Wenn mehrere Textstellen denselben Risikotyp betreffen (z.B. Weisungsrecht, Auditpflichten, Berichtspflichten), dann:
- erstelle EIN Hauptfinding
- ergänze weitere Stellen als Unteraspekte in der Erklärung
NICHT mehrere separate Findings für denselben Risikotyp.

REGEL 2 – IGNORIERE UNKRITISCHE PASSAGEN
Ignoriere insbesondere:
- rein deklarative Vertragsformeln
- neutrale Definitionen
- Standardfloskeln ohne operative Folgen
- Wiederholungen bereits erkannter Risiken
- rein organisatorische Formulierungen ohne Risiko

REGEL 3 – VERMEIDE GENERISCHE KOMMENTARE
Formulierungen wie "Dies könnte problematisch sein", "Es wäre zu prüfen", "Es sollte geklärt werden" sind NICHT erlaubt.
Erkläre konkret: welches Risiko entsteht, warum es entsteht, für wen es entsteht, welche Konsequenz droht.

REGEL 4 – RISIKOSTUFEN
Bewerte jedes Finding nach realer Verhandlungsrelevanz:
- Kritisch: Existenzielle Risiken oder unbegrenzte Haftung
- Hoch: Deutliche wirtschaftliche oder operative Risiken
- Mittel: Verhandelbare, aber kontrollierbare Risiken
- Niedrig: Hinweis ohne unmittelbare Gefahr
Vermeide Risiko-Inflation. Nicht alles ist "hoch" oder "kritisch".

REGEL 5 – VERHANDLUNGSORIENTIERUNG
Zu jedem Finding musst du liefern:
1. Risikoerklärung (konkret, nicht generisch)
2. Konkrete Empfehlung
3. Mögliche Alternativformulierung (konkreter Textvorschlag)
4. Bieterfrage für die Verhandlung
5. Argumente, warum die Anpassung auch für den Auftraggeber sinnvoll ist

REGEL 6 – KEINE DOPPELTEN FINDINGS
Wenn eine ähnliche Klausel mehrfach vorkommt, füge sie als zusätzliche Textstelle zu einem bestehenden Finding hinzu.
Bei einem Vertrag von ca. 15 Seiten sollen typischerweise 20 bis maximal 80 Findings entstehen.
""".strip()

# Shared JSON schema instruction
FINDING_JSON_SCHEMA = """
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat diese Felder:
{
  "textstelle": "Originaltext aus dem Vertrag (möglichst wörtlich, MINDESTENS ein vollständiger Satz, besser der ganze relevante Absatz)",
  "kategorie": "z.B. Weisungsrecht, Audit, Haftung, Reporting, Compliance, SLA, Subunternehmer, Informationssicherheit, Datenschutz, Verfügbarkeit & Betrieb, Vertragsmanagement, Leistungsumfang & Abgrenzung, Personalanforderungen, Geistiges Eigentum, Implizite Pflichten",
  "kurzbeschreibung": "kurzer präziser Titel des Problems",
  "erklaerung": "KONKRETE Erklärung: (1) Welches Risiko entsteht? (2) Warum entsteht es? (3) Für wen entsteht es? (4) Welche Konsequenz droht? KEINE generischen Phrasen wie 'könnte problematisch sein' oder 'wäre zu prüfen'.",
  "empfehlung": "Was sollte konkret geändert werden",
  "risikostufe": "Kritisch oder Hoch oder Mittel oder Niedrig",
  "risiko_detail": "Welche konkreten Konsequenzen für den Auftragnehmer entstehen (z.B. unbegrenzte Kostenpflicht, Vertragsstrafe, regulatorisches Bußgeld, operative Überlastung). Für wen genau? In welchem Szenario?",
  "alternativformulierung": "Konkrete Vertragsformulierung als Textvorschlag, die das Risiko begrenzt ohne den Vertragszweck zu gefährden.",
  "bieterfrage": "Frage, die der Bieter im Vergabeverfahren stellen sollte, um Klarheit zu schaffen.",
  "verhandlungsargumente": ["Argument 1: warum die Anpassung auch im AG-Interesse liegt", "Argument 2: Marktüblichkeit oder Best Practice"]
}

Wenn du KEINE verhandlungsrelevanten Feststellungen findest, antworte mit einem leeren Array: []
""".strip()


def _format_verhandlungsargumente(value) -> str:
    """Convert verhandlungsargumente from list or string to a formatted string."""
    if isinstance(value, list):
        return "\n".join(f"- {arg}" for arg in value if arg)
    return str(value) if value else ""


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
                    verhandlungsargumente=_format_verhandlungsargumente(item.get("verhandlungsargumente", "")),
                ))
            except Exception:
                continue
        return findings
