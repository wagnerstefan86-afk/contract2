"""Pass 2: Perspektivische Vertiefung — domain-specific expert lenses.

Runs multiple sub-passes, each with a specialized perspective that
may catch issues the broad pass missed. Each sub-pass re-reads
segments through a domain-expert lens.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, FINDING_JSON_SCHEMA, QUALITAETS_REGELN

logger = logging.getLogger(__name__)

# Each perspective: (name, system prompt addition)
PERSPEKTIVEN = [
    (
        "Informationssicherheit",
        """Du bist Experte für Informationssicherheit und prüfst Verträge aus Auftragnehmer-Sicht.
Suche nach ALLEN Klauseln, die Folgendes betreffen — auch wenn sie nur indirekt oder am Rande relevant erscheinen:
- Verschlüsselungsanforderungen, die schwer erfüllbar oder nicht genau spezifiziert sind
- Zugriffskontrollen und Berechtigungsmanagement-Pflichten
- Vorfallmeldepflichten (Incident Response) mit unrealistischen Fristen (z.B. unter 24h)
- Anforderungen an Sicherheitszertifizierungen (ISO 27001, SOC2, C5 etc.)
- Datenlöschpflichten und Nachweispflichten für Löschung
- Penetrationstests oder Sicherheitsaudits, die der Auftragnehmer dulden muss
- Anforderungen an Standort, Datenresidenz, Netzwerktrennung
- Verpflichtungen zur Einhaltung von Sicherheitsstandards des Auftraggebers (die sich ändern können!)
- "Stand der Technik"-Formulierungen bei Sicherheitsanforderungen
- Pflicht zur Bereitstellung eines Incident-Response-Teams""",
    ),
    (
        "BCM / Betrieb / Resilienz",
        """Du bist Experte für Business Continuity, IT-Betrieb und Resilienz.
Suche nach ALLEN Klauseln, die Folgendes betreffen — auch Klauseln, die nur indirekt Betriebsverpflichtungen schaffen:
- SLA-Verpflichtungen mit hohen Verfügbarkeitsanforderungen (99.9%+ ist problematisch, 99.95%+ ist sehr problematisch)
- Reaktionszeiten und Wiederherstellungszeiten (RTO/RPO), die unrealistisch sein könnten
- BCM/DR-Planpflichten und regelmäßige Testpflichten
- Notfallübungen, die der Auftragnehmer durchführen oder unterstützen muss
- Strafen bei SLA-Verletzungen (Pönalen, Service Credits) — besonders wenn kumulierbar
- Vertragsstrafen, die NICHT auf den Gesamtschaden angerechnet werden
- Kapazitätszusicherungen und Skalierungspflichten
- Pflichten bei Ausfall von Subdienstleistern
- Verpflichtungen zu redundanten Systemen oder georedundanten Standorten
- Wartungsfenster-Einschränkungen, die Betrieb erschweren
- Prioritätseinstufungen, die einseitig vom Auftraggeber festgelegt werden""",
    ),
    (
        "Compliance / Regulatorik",
        """Du bist Experte für regulatorische Compliance und prüfst aus Auftragnehmer-Sicht.
Suche nach ALLEN Klauseln, die Folgendes betreffen — besonders regulatorische Durchreichung ist häufig und gefährlich:
- Regulatorische Durchreichung (regulatory pass-through): Pflichten, die eigentlich den Auftraggeber treffen, aber an den Auftragnehmer weitergereicht werden
- DSGVO-Pflichten, die über das Standardmaß hinausgehen
- Branchenspezifische Regularien (BAIT, VAIT, DORA, NIS2, KRITIS) — der Auftragnehmer ist oft kein reguliertes Institut!
- Zertifizierungspflichten, die der Auftragnehmer erfüllen und aufrechterhalten muss
- Pflicht zur Einhaltung von Weisungen, die sich ändern können (Blanko-Weisungsrecht)
- Compliance-Nachweispflichten und Berichtspflichten
- Pflicht zur Anpassung an sich ändernde Regulierung auf EIGENE KOSTEN
- Pflicht zur Einhaltung von "sämtlichen für den Auftraggeber geltenden" Anforderungen — das ist eine Blanko-Pflicht
- Verweis auf BaFin-Rundschreiben oder ähnliche regulatorische Dokumente, die sich ändern""",
    ),
    (
        "Audit / Reporting / Nachweise",
        """Du bist Experte für Audit- und Nachweispflichten in IT-Verträgen.
Suche nach ALLEN Klauseln, die Folgendes betreffen — Audit-Rechte werden oft unterschätzt:
- Prüfrechte des Auftraggebers (vor Ort, remote, unangekündigt)
- Prüfrechte von Dritten (Wirtschaftsprüfer, Regulatoren, BaFin)
- Uneingeschränkte Zugangsrechte zu Unterlagen, Systemen und Räumlichkeiten
- Berichtspflichten mit hoher Frequenz oder nicht spezifiziertem Umfang
- Berichte deren Format, Umfang und Detailtiefe EINSEITIG vom Auftraggeber festgelegt werden
- Nachweispflichten für Zertifizierungen, Schulungen, Prozesse
- Pflicht zur Herausgabe von Dokumenten, Logdateien, Konfigurationen
- KPI-Reporting und Messmethoden, die einseitig definiert werden
- Mitwirkungspflichten bei Prüfungen Dritter auf EIGENE KOSTEN
- Aufbewahrungspflichten für Dokumentation
- Pflicht, Audit-Kosten selbst zu tragen""",
    ),
    (
        "Haftung / Zusicherung / Überdehnung",
        """Du bist Experte für Haftungsrecht in IT-Verträgen und prüfst aus Auftragnehmer-Sicht.
Suche nach ALLEN Klauseln, die Folgendes betreffen — fehlende Haftungsbegrenzungen sind genauso problematisch wie explizite:
- Haftungsobergrenzen, die FEHLEN oder unangemessen hoch sind
- UNBESCHRÄNKTE Haftung (ist fast immer problematisch)
- Ausschluss der Beschränkung auf leichte Fahrlässigkeit
- Freistellungsverpflichtungen (Indemnification) zugunsten des Auftraggebers
- Gewährleistungszusagen, die über den Standard hinausgehen
- Schadensersatzregelungen mit unklarem Umfang
- Vertragsstrafen / Pönalen, besonders wenn kumulierbar oder nicht anrechenbar
- Zusicherungen, die schwer einhaltbar sind ("Mängelfreiheit", "Stand der Technik", "marktüblich")
- Haftung für Dritte oder Subunternehmer wie für eigenes Verschulden
- Versicherungspflichten mit hohen Deckungssummen (10 Mio.+)
- Einseitige Haftungsausschlüsse zugunsten des Auftraggebers
- IP-Übertragung bei Vertragsende oder automatisch bei Entstehung
- Unwiderruflicher Verzicht auf Rechte""",
    ),
]


BASE_SYSTEM = """Du bist ein erfahrener Vertragsjurist und IT-Sourcing-Spezialist mit Fokus auf Managed Services, Outsourcing, Cloud-Verträge und regulatorische Anforderungen.
Du prüfst Verträge aus der Perspektive eines Auftragnehmers (IT-Dienstleister).

WICHTIG: Du sollst NUR solche Punkte identifizieren, die für den Auftragnehmer ein rechtliches, wirtschaftliches oder operatives Risiko, ein einseitiges Machtgefälle oder eine regulatorische Haftungsübertragung darstellen.
Ignoriere unkritische Standardpassagen und rein deklarative Formulierungen.

{SPEZIALISIERUNG}

{regeln}

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
                regeln=QUALITAETS_REGELN,
                schema=FINDING_JSON_SCHEMA,
            )

            for seg in segments:
                user_prompt = (
                    f"Analysiere den folgenden Vertragsabschnitt aus der Perspektive "
                    f"'{perspektive_name}'. Identifiziere nur tatsächlich verhandlungsrelevante "
                    f"Risiken. Fasse ähnliche Risiken zusammen.\n\n"
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
