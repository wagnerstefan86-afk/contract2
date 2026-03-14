"""Pass 1: Breite Ersterfassung — broad initial scan.

Goal: scan every segment for clauses that create real obligations, risks,
liabilities, restrictions, or commitments for the Auftragnehmer.
Focus on verhandlungsrelevante findings, not exhaustive coverage.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, FINDING_JSON_SCHEMA, QUALITAETS_REGELN

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""Du bist ein erfahrener Vertragsjurist und IT-Sourcing-Spezialist mit Fokus auf Managed Services, Outsourcing, Cloud-Verträge und regulatorische Anforderungen (BAIT, MaRisk, DORA, ISO 27001).
Deine Aufgabe ist es, einen Vertrag aus Sicht eines Auftragnehmers (Dienstleister) zu prüfen.

WICHTIG: Du sollst NICHT jede Klausel kommentieren.
Du sollst nur solche Punkte identifizieren, die für den Auftragnehmer:
- ein rechtliches Risiko
- ein wirtschaftliches Risiko
- eine operative Überlastung
- ein einseitiges Machtgefälle
- oder eine regulatorische Haftungsübertragung
darstellen.

ZIEL: Ein Reviewer soll aus deiner Analyse schnell erkennen, welche Punkte tatsächlich verhandlungsrelevant sind.

Achte besonders auf:
  * Fristen und Reaktionszeiten (unrealistisch kurz?)
  * Strafklauseln und Pönalen (unverhältnismäßig?)
  * Haftungsregelungen (fehlt eine Obergrenze? unbeschränkt?)
  * Zusicherungen und Gewährleistungen (zu weitgehend?)
  * Pflichten und Einschränkungen (einseitig?)
  * Einseitige Rechte des Auftraggebers (Kündigung, Änderung, Weisung?)
  * Verweise auf externe Dokumente oder Standards (unkontrollierbar?)
  * Fehlende Regelungen (was fehlt, kann gefährlich sein)
  * Automatische Verlängerungen und lange Bindungsfristen
  * Transitionspflichten und Mitwirkungspflichten bei Vertragsende

{QUALITAETS_REGELN}

{FINDING_JSON_SCHEMA}"""


class BreitPass(DiscoveryPass):
    name = "Breite Ersterfassung"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []

        for seg in segments:
            logger.info(f"Breit-Pass: Segment {seg.id}")
            user_prompt = (
                f"Analysiere den folgenden Vertragsabschnitt. "
                f"Identifiziere nur tatsächlich verhandlungsrelevante Risiken für den Auftragnehmer. "
                f"Fasse ähnliche Risiken zusammen. Ignoriere unkritische Standardpassagen.\n\n"
                f"{seg.fenster_text}"
            )

            items = await llm_json_completion(
                config=config,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
            )

            findings = self._parse_findings(items, self.name, [seg.id])
            logger.info(f"Breit-Pass: {len(findings)} Fundstellen in {seg.id}")
            all_findings.extend(findings)

        return all_findings
