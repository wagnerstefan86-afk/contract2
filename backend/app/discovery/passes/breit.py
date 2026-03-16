"""Pass 1: Breite Ersterfassung — broad initial scan.

Goal: scan every segment for material contractual risks from the
Auftragnehmer perspective. Uses the shared material-risk extraction prompt.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, MATERIAL_RISK_SYSTEM_PROMPT, get_perspective_prompt

logger = logging.getLogger(__name__)

PASS_CONTEXT = """

Zusätzlicher Kontext für diesen Pass — Breite Ersterfassung:
Schwerpunkte:
- Fristen und Reaktionszeiten (unrealistisch kurz?)
- Vertragsstrafen (unverhältnismäßig?)
- Haftungsregelungen (fehlende Deckelungen? unbegrenzt?)
- Gewährleistungen und Zusicherungen (zu weitgehend?)
- Einseitige Pflichten oder Beschränkungen
- Einseitige Rechte (Kündigung, Änderungen, Weisungen)
- Verweise auf externe Dokumente oder Standards (unkontrollierbar?)
- Fehlende Regelungen (was nicht geregelt ist, kann gefährlich sein)
- Automatische Verlängerung und lange Bindungsfristen
- Transitionspflichten bei Vertragsende"""


class BreitPass(DiscoveryPass):
    name = "Breite Ersterfassung"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
        perspective: str = "provider",
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []
        system_prompt = MATERIAL_RISK_SYSTEM_PROMPT + get_perspective_prompt(perspective) + PASS_CONTEXT

        for seg in segments:
            logger.info(f"Breit-Pass: Segment {seg.id}")
            user_prompt = (
                f"Analysiere den folgenden Vertragsabschnitt. "
                f"Extrahiere nur WESENTLICHE vertragliche Risiken. "
                f"Antworte mit NO_FINDING falls kein wesentliches Risiko vorliegt.\n\n"
                f"{seg.fenster_text}"
            )

            items = await llm_json_completion(
                config=config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
            )

            findings = self._parse_findings(items, self.name, [seg.id],
                                            segment_text=seg.fenster_text)
            logger.info(f"Breit-Pass: {len(findings)} Fundstellen in {seg.id}")
            all_findings.extend(findings)

        return all_findings
