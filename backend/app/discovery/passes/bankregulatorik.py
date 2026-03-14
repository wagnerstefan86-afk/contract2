"""Pass 4: Bankregulatorik — banking regulatory risk analysis.

Goal: identify IT-outsourcing risks from a banking regulatory perspective
(KWG, MaRisk, BAIT, DORA). Highly selective: max 3 findings per segment.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding

logger = logging.getLogger(__name__)

RISK_LEVEL_MAP = {
    "kritisch": "Kritisch",
    "hoch": "Hoch",
    "mittel": "Mittel",
    "niedrig": "Niedrig",
}

SYSTEM_PROMPT = """Du bist ein erfahrener IT-Outsourcing-Jurist mit Schwerpunkt Bankregulatorik (KWG, MaRisk, BAIT, DORA).
Analysiere den folgenden Vertragsabschnitt aus Sicht des Auftragnehmers.
Melde nur Risiken, die für einen IT-Dienstleister wirtschaftlich, rechtlich oder operativ relevant sein können.

IGNORIERE:
- rein deklarative Formulierungen
- Definitionen ohne operative Wirkung
- Wiederholungen bereits erkannter Risiken
- rein organisatorische Klauseln ohne Risiko

Ein Risiko liegt insbesondere vor bei:
- einseitigen Weisungsrechten
- regulatorischer Durchreichung
- unbegrenzten oder unklaren Haftungsfolgen
- unklaren Leistungsumfängen
- Audit- oder Berichtspflichten ohne Begrenzung
- Subunternehmerhaftung
- Exit- oder Datenherausgabe
- Incident- oder BCM-Verpflichtungen

Wenn mehrere Sätze denselben Risikotyp betreffen, melde sie als separate Belege, aber mit derselben Kategorie.

AUSGABEFORMAT (JSON):
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat diese Felder:
{
  "title": "kurzer präziser Titel",
  "category": "Weisungsrecht | Audit | Compliance | Haftung | BCM | Incident | Subunternehmer | Exit | Leistungsumfang",
  "risk_level": "kritisch | hoch | mittel | niedrig",
  "textstelle": "Originaltext aus dem Vertrag",
  "kurzbeschreibung": "kurze Erklärung des Risikos"
}

Erzeuge maximal 3 Risiken pro Textsegment.
Wenn du KEINE relevanten Risiken findest, antworte mit einem leeren Array: []"""

MAX_FINDINGS_PER_SEGMENT = 3


class BankregulatorikPass(DiscoveryPass):
    name = "Bankregulatorik"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []

        for seg in segments:
            user_prompt = (
                f"Analysiere den folgenden Vertragsabschnitt aus bankregulatorischer Sicht. "
                f"Maximal 3 Risiken.\n\n"
                f"{seg.fenster_text}"
            )

            items = await llm_json_completion(
                config=config,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )

            findings = self._parse_bankregulatorik_findings(items, [seg.id])
            all_findings.extend(findings)

        logger.info(f"Bankregulatorik-Pass: {len(all_findings)} Fundstellen insgesamt")
        return all_findings

    def _parse_bankregulatorik_findings(
        self, items: list[dict], segment_ids: list[str]
    ) -> list[RawFinding]:
        """Parse the simplified banking regulatory JSON into RawFinding objects."""
        findings = []
        for item in items[:MAX_FINDINGS_PER_SEGMENT]:
            if not isinstance(item, dict):
                continue
            try:
                raw_risk = str(item.get("risk_level", "niedrig")).lower()
                findings.append(RawFinding(
                    textstelle=str(item.get("textstelle", "")),
                    kategorie=str(item.get("category", "Compliance")),
                    kurzbeschreibung=str(item.get("title", "")),
                    erklaerung=str(item.get("kurzbeschreibung", "")),
                    empfehlung="",
                    risikostufe=RISK_LEVEL_MAP.get(raw_risk, "Niedrig"),
                    segment_ids=segment_ids,
                    quelle_pass=self.name,
                ))
            except Exception:
                continue

        if len(items) > MAX_FINDINGS_PER_SEGMENT:
            logger.warning(
                f"Bankregulatorik-Pass: LLM lieferte {len(items)} Findings, "
                f"auf {MAX_FINDINGS_PER_SEGMENT} begrenzt"
            )

        return findings
