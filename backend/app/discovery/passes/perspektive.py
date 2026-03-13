"""Pass 2: Perspektivische Vertiefung — domain-specific expert lenses.

Runs multiple sub-passes, each with a specialized perspective that
may catch issues the broad pass missed. Each sub-pass re-reads
segments through a domain-expert lens.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, FINDING_JSON_SCHEMA

logger = logging.getLogger(__name__)

# Each perspective: (name, system prompt addition)
PERSPEKTIVEN = [
    (
        "Informationssicherheit",
        """Du bist Experte für Informationssicherheit und prüfst Verträge aus Auftragnehmer-Sicht.
Suche nach ALLEN Klauseln, die Folgendes betreffen:
- Verschlüsselungsanforderungen, die schwer erfüllbar sein könnten
- Zugriffskontrollen und Berechtigungsmanagement-Pflichten
- Vorfallmeldepflichten (Incident Response) mit unrealistischen Fristen
- Anforderungen an Sicherheitszertifizierungen (ISO 27001, SOC2 etc.)
- Datenlöschpflichten und Nachweispflichten
- Penetrationstests oder Sicherheitsaudits, die der Auftragnehmer dulden muss
- Anforderungen an Standort, Datenresidenz, Netzwerktrennung
- Verpflichtungen zur Einhaltung von Sicherheitsstandards des Auftraggebers""",
    ),
    (
        "BCM / Betrieb / Resilienz",
        """Du bist Experte für Business Continuity, IT-Betrieb und Resilienz.
Suche nach ALLEN Klauseln, die Folgendes betreffen:
- SLA-Verpflichtungen mit hohen Verfügbarkeitsanforderungen (99.9%+)
- Reaktionszeiten und Wiederherstellungszeiten (RTO/RPO), die unrealistisch sein könnten
- BCM/DR-Planpflichten und Testpflichten
- Notfallübungen, die der Auftragnehmer durchführen oder unterstützen muss
- Strafen bei SLA-Verletzungen (Pönalen, Service Credits)
- Kapazitätszusicherungen und Skalierungspflichten
- Pflichten bei Ausfall von Subdienstleistern
- Verpflichtungen zu redundanten Systemen oder Standorten""",
    ),
    (
        "Compliance / Regulatorik",
        """Du bist Experte für regulatorische Compliance und prüfst aus Auftragnehmer-Sicht.
Suche nach ALLEN Klauseln, die Folgendes betreffen:
- Regulatorische Durchreichung (regulatory pass-through) - Pflichten, die eigentlich den Auftraggeber treffen, aber an den Auftragnehmer weitergereicht werden
- DSGVO-Pflichten, die über das Standardmaß hinausgehen
- Branchenspezifische Regularien (BAIT, VAIT, DORA, NIS2, KRITIS)
- Zertifizierungspflichten, die der Auftragnehmer erfüllen muss
- Pflicht zur Einhaltung von Weisungen, die sich ändern können
- Compliance-Nachweispflichten und Berichtspflichten
- Pflicht zur Anpassung an sich ändernde Regulierung auf eigene Kosten""",
    ),
    (
        "Audit / Reporting / Nachweise",
        """Du bist Experte für Audit- und Nachweispflichten in IT-Verträgen.
Suche nach ALLEN Klauseln, die Folgendes betreffen:
- Prüfrechte des Auftraggebers (vor Ort, remote, unangekündigt)
- Prüfrechte von Dritten (Wirtschaftsprüfer, Regulatoren, Subunternehmer des AG)
- Berichtspflichten mit hoher Frequenz oder großem Umfang
- Nachweispflichten für Zertifizierungen, Schulungen, Prozesse
- Pflicht zur Herausgabe von Dokumenten, Logdateien, Konfigurationen
- KPI-Reporting und Messmethoden, die einseitig definiert werden
- Mitwirkungspflichten bei Prüfungen Dritter auf eigene Kosten
- Aufbewahrungspflichten für Dokumentation""",
    ),
    (
        "Haftung / Zusicherung / Überdehnung",
        """Du bist Experte für Haftungsrecht in IT-Verträgen und prüfst aus Auftragnehmer-Sicht.
Suche nach ALLEN Klauseln, die Folgendes betreffen:
- Haftungsobergrenzen, die fehlen oder unangemessen hoch sind
- Freistellungsverpflichtungen (Indemnification) zugunsten des Auftraggebers
- Gewährleistungszusagen, die über den Standard hinausgehen
- Schadensersatzregelungen mit unklarem Umfang
- Vertragsstrafen / Pönalen
- Zusicherungen, die schwer einhaltbar sind (Mängelfreiheit, "state of the art")
- Haftung für Dritte oder Subunternehmer ohne Regressmöglichkeit
- Versicherungspflichten mit hohen Deckungssummen
- Einseitige Haftungsausschlüsse zugunsten des Auftraggebers""",
    ),
]


BASE_SYSTEM = """Du bist ein erfahrener Vertragsprüfer, der Verträge aus der Perspektive eines IT-Dienstleisters (Auftragnehmer) analysiert.

WICHTIGE REGELN:
- Im Zweifel EINSCHLIESSEN. Lieber zu viele als zu wenige Fundstellen.
- Ignoriere Überschriften — analysiere den INHALT und die BEDEUTUNG.
- Suche nach Pflichten, die IMPLIZIT oder INDIREKT entstehen könnten.

{SPEZIALISIERUNG}

{schema}
"""


class PerspektivePass(DiscoveryPass):
    name = "Perspektivische Vertiefung"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []

        for perspektive_name, spezialisierung in PERSPEKTIVEN:
            logger.info(f"Perspektive-Pass: {perspektive_name}")
            system = BASE_SYSTEM.format(
                SPEZIALISIERUNG=spezialisierung,
                schema=FINDING_JSON_SCHEMA,
            )

            for seg in segments:
                user_prompt = (
                    f"Analysiere den folgenden Vertragsabschnitt aus der Perspektive "
                    f"'{perspektive_name}'. Finde ALLE relevanten Feststellungen.\n\n"
                    f"{seg.fenster_text}"
                )

                items = await llm_json_completion(
                    config=config,
                    system_prompt=system,
                    user_prompt=user_prompt,
                    temperature=0.2,
                    max_tokens=4096,
                )

                pass_label = f"{self.name} ({perspektive_name})"
                findings = self._parse_findings(items, pass_label, [seg.id])
                all_findings.extend(findings)

            logger.info(
                f"Perspektive-Pass '{perspektive_name}': "
                f"{sum(1 for f in all_findings if perspektive_name in f.quelle_pass)} Fundstellen"
            )

        return all_findings
