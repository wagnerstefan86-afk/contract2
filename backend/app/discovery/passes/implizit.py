"""Pass 3: Implizite Pflichten — hidden obligations scan.

Goal: find obligations NOT explicitly stated but implied through vague
language, catch-all clauses, definitions, external references, or
combinations of clauses. Uses the full contract text for maximum context.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, FINDING_JSON_SCHEMA, QUALITAETS_REGELN

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""Du bist ein erfahrener Vertragsjurist und IT-Sourcing-Spezialist, spezialisiert auf das Erkennen IMPLIZITER und VERSTECKTER Pflichten in IT-Verträgen. Du prüfst aus der Perspektive des Auftragnehmers (IT-Dienstleister).

Deine Aufgabe ist es, Verpflichtungen zu finden, die NICHT explizit aufgelistet sind, aber IMPLIZIT entstehen und ein reales Risiko für den Auftragnehmer darstellen.

Prüfe auf diese Muster:

1. VAGE FORMULIERUNGEN, die den Leistungsumfang schleichend erweitern:
   - "angemessene Maßnahmen", "best efforts", "nach bestem Wissen"
   - "marktübliche Standards", "Stand der Technik"
   - "sämtliche", "alle erforderlichen"

2. DEFINITIONEN, die Pflichten einschmuggeln:
   - Definitionen von "Leistung" oder "Service", die sehr breit gefasst sind
   - "einschließlich, aber nicht beschränkt auf..."
   - Definitionen, die auf externe Dokumente verweisen

3. CATCH-ALL-KLAUSELN:
   - "sonstige Leistungen, die zur Erreichung des Vertragszwecks erforderlich sind"
   - "alle damit zusammenhängenden Tätigkeiten"

4. EXTERNE VERWEISE:
   - Verweis auf Standards (ISO, BSI, NIST) mit umfangreichen Pflichten
   - Verweis auf Richtlinien des Auftraggebers "in der jeweils aktuellen Fassung" (Blanko-Verweis!)
   - Verweis auf Anlagen, die nicht vollständig spezifiziert sind

5. KOMBINATIONSEFFEKTE:
   - Klauseln, die einzeln harmlos sind, aber zusammen eine überdehnende Pflicht ergeben
   - Allgemeine Mitwirkungspflichten + spezifische SLAs = implizite 24/7-Bereitschaft
   - Breiter Leistungsumfang + Festpreis = Kostenrisiko bei Scope Creep

6. FEHLENDE REGELUNGEN:
   - Keine Haftungsobergrenze definiert
   - Kein Change-Management-Verfahren bei Änderungen
   - Keine Regelung zur Kostentragung bei regulatorischen Änderungen

WICHTIG: Erstelle NUR Findings für tatsächliche Risiken. Fasse ähnliche implizite Pflichten zu einem Finding zusammen.
Implizite Pflichten sind oft die gefährlichsten, weil sie erst bei Streitigkeiten sichtbar werden — aber nicht jede vage Formulierung ist automatisch ein Risiko.

{QUALITAETS_REGELN}

{FINDING_JSON_SCHEMA}"""


class ImplizitPass(DiscoveryPass):
    name = "Implizite Pflichten"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []

        # MVP: Send full text if it fits, otherwise process larger segment windows.
        MAX_CHARS = 12000  # roughly ~3k tokens

        if len(full_text) <= MAX_CHARS:
            # Full text fits — analyze at once for maximum cross-clause visibility
            logger.info("Implizit-Pass: Gesamttext wird analysiert")
            items = await llm_json_completion(
                config=config,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=(
                    "Analysiere den folgenden Vertrag auf IMPLIZITE und VERSTECKTE Pflichten "
                    "für den Auftragnehmer. Identifiziere nur Stellen mit realem Risikopotenzial. "
                    "Achte auf fehlende Regelungen, offene Verweise und Kombinationseffekte. "
                    "Fasse ähnliche implizite Pflichten zusammen.\n\n"
                    f"{full_text}"
                ),
                temperature=0.4,
                max_tokens=4096,
            )
            findings = self._parse_findings(items, self.name, ["full-text"])
            all_findings.extend(findings)
        else:
            # Process in larger overlapping chunks
            logger.info(f"Implizit-Pass: Text zu lang ({len(full_text)} Zeichen), segmentweise Analyse")
            for seg in segments:
                items = await llm_json_completion(
                    config=config,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=(
                        "Analysiere den folgenden Vertragsabschnitt auf IMPLIZITE und VERSTECKTE "
                        "Pflichten für den Auftragnehmer. Nur tatsächlich risikorelevante Stellen.\n\n"
                        f"{seg.fenster_text}"
                    ),
                    temperature=0.4,
                    max_tokens=4096,
                )
                findings = self._parse_findings(items, self.name, [seg.id])
                all_findings.extend(findings)

        logger.info(f"Implizit-Pass: {len(all_findings)} Fundstellen insgesamt")
        return all_findings
