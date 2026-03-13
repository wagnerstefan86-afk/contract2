"""Pass 1: Breite Ersterfassung — broad initial scan.

Goal: cast the widest net. Scan every segment for ANY clause that could
create an obligation, risk, liability, restriction, or commitment for
the Auftragnehmer. Over-include rather than miss anything.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, FINDING_JSON_SCHEMA, RECALL_INSTRUCTION

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""Du bist ein erfahrener Vertragsprüfer, der Verträge aus der Perspektive eines IT-Dienstleisters (Auftragnehmer) analysiert.

Deine Aufgabe ist eine BREITE ERSTERFASSUNG aller potenziell problematischen Stellen.

WICHTIGE REGELN:
- Identifiziere JEDE Klausel, jeden Satz oder jede Formulierung, die eine Verpflichtung, ein Risiko, eine Haftung, eine Einschränkung oder eine Zusage für den Auftragnehmer schaffen KÖNNTE.
- Im Zweifel EINSCHLIESSEN, nicht ausschließen. Lieber zu viele als zu wenige Fundstellen.
- Ignoriere Überschriften und Abschnittsnummern — analysiere den INHALT und die BEDEUTUNG.
- Auch harmlos klingende Formulierungen können versteckte Pflichten enthalten.
- Achte besonders auf:
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

{RECALL_INSTRUCTION}

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
                f"Finde ALLE potenziell problematischen Stellen für den Auftragnehmer. "
                f"Denke daran: Lieber 10 Fundstellen als 3. Überinklusion ist gewünscht.\n\n"
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
