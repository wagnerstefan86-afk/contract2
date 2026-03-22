"""Stage D: Trigger-based domain deep checks.

Only invoked for clauses already marked as problematic by the universal risk
read.  Each deep check enriches the finding with domain-specific severity,
reasoning, negotiation implications, and recommendation candidates.

Routing is determined by the trigger_domains / deep_check_domains from the
first-read output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_completion
from app.discovery.passes.risk_screen import ClauseScreenResult
from app.discovery.passes.base import (
    RawFinding,
    build_source_fingerprint,
    normalize_severity,
    _extract_evidence_text,
    _format_verhandlungsargumente,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Domain deep-check definitions
# ---------------------------------------------------------------------------

DOMAIN_PROMPTS: dict[str, str] = {
    "audit": """TIEFENPRÜFUNG: AUDIT- UND KONTROLLRECHTE

Prüfe die markierte Klausel auf diese konkreten Audit-Risiken für den IT-Dienstleister:

1. Unangekündigte Vor-Ort-Audits (operatives Störungsrisiko)
2. Unbegrenzte Auditfrequenz oder -dauer
3. Zugangsrechte für Dritte (Wirtschaftsprüfer, Regulierer) ohne klare Abgrenzung
4. Pflicht zur Kostenübernahme von Audits
5. Uneingeschränkter Zugriff auf Dokumente, Systeme, Räumlichkeiten
6. Fehlende Vorankündigungsfristen
7. Pflicht zur Umsetzung von Audit-Feststellungen ohne Prüfung der Zumutbarkeit

Liefere:
- severity: Neubewertung (low/medium/high/critical)
- deep_reason: Detaillierte Erklärung des Audit-Risikos (3-4 Sätze, Deutsch)
- recommendation: Konkrete Handlungsempfehlung (1-2 Sätze, Deutsch)
- negotiation_points: 2-3 konkrete Verhandlungshebel (Deutsch)
- alternative_wording: Vorschlag für ausgewogenere Formulierung (Deutsch)
- bidder_question: Konkrete Bieterfrage (Deutsch)""",

    "reporting": """TIEFENPRÜFUNG: REPORTING- UND NACHWEISPFLICHTEN

Prüfe die markierte Klausel auf diese konkreten Reporting-Risiken für den IT-Dienstleister:

1. Unbegrenzte oder unbestimmte Berichtspflichten
2. Einseitig definiertes Berichtsformat/-umfang
3. Unrealistische Berichtsfrequenz
4. KPI-Reporting mit einseitiger Messmethodik
5. Dokumentationsaufbewahrungspflichten ohne Zeitbegrenzung
6. Pflicht zur jederzeitigen Auskunftserteilung ohne Vorlaufzeit

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "bcm": """TIEFENPRÜFUNG: BCM / ITSCM / RESILIENZ

Prüfe die markierte Klausel auf diese konkreten BCM-Risiken für den IT-Dienstleister:

1. Übertragung der BCM-/DR-Verantwortung des Auftraggebers auf den Dienstleister
2. Unrealistische RTO/RPO-Vorgaben ohne technische Machbarkeitsprüfung
3. Pflicht zu regelmäßigen BCM-Tests mit unklarem Umfang
4. Geo-Redundanz- oder Redundanzanforderungen ohne Kostenzuordnung
5. Verfügbarkeitsgarantien über 99,9% ohne klar definierte Messmethodik
6. Pflicht zur Übernahme des Risikomanagements des Auftraggebers

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "liability": """TIEFENPRÜFUNG: HAFTUNG / FREISTELLUNG / VERTRAGSSTRAFEN

Prüfe die markierte Klausel auf diese konkreten Haftungsrisiken für den IT-Dienstleister:

1. Fehlende oder unangemessen hohe Haftungsdeckelung
2. Unbeschränkte Haftung (fast immer problematisch)
3. Einseitige Freistellungspflichten zugunsten des Auftraggebers
4. Kumulative oder nicht anrechenbare Vertragsstrafen
5. Haftung für Dritte / Subunternehmer als eigenes Verschulden
6. Versicherungspflichten mit hohen Deckungssummen (10M+)
7. Einseitige Haftungsausschlüsse zugunsten des Auftraggebers
8. Garantien, die schwer einzuhalten sind ("mangelfrei", "Stand der Technik")

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "regulatory": """TIEFENPRÜFUNG: REGULATORISCHE LASTENVERLAGERUNG

Prüfe die markierte Klausel auf diese konkreten regulatorischen Risiken für den IT-Dienstleister:

1. Regulatorische Durchreichung: Pflichten des regulierten Auftraggebers werden auf den Dienstleister verlagert
2. Pauschalverweis auf "alle für den Auftraggeber geltenden Anforderungen"
3. Pflicht zur Anpassung an sich ändernde regulatorische Anforderungen auf eigene Kosten
4. DORA/NIS2/BAIT/MaRisk-Pflichten ohne klare Abgrenzung des Dienstleisteranteils
5. Blanko-Weisungsrechte zur Durchsetzung regulatorischer Änderungen
6. Verweis auf regulatorische Rundschreiben "in ihrer jeweiligen Fassung"

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "scope": """TIEFENPRÜFUNG: LEISTUNGSUMFANG / SCOPE CREEP

Prüfe die markierte Klausel auf diese konkreten Scope-Risiken für den IT-Dienstleister:

1. Offene oder unbestimmte Leistungsdefinitionen
2. "Alle zur Vertragszweckerreichung erforderlichen Leistungen"
3. Einseitige Leistungserweiterungsrechte des Auftraggebers
4. Fehlende Change-Management-Verfahren bei Umfangsänderungen
5. Verweis auf nicht finalisierte Anlagen oder externe Dokumente
6. Breite Definitionen von "Service" oder "Liefergegenstand" mit "einschließlich, aber nicht beschränkt auf"

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "subcontractor": """TIEFENPRÜFUNG: SUBUNTERNEHMER

Prüfe die markierte Klausel auf Subunternehmer-Risiken für den IT-Dienstleister:

1. Unbegrenzte Haftung für Subunternehmerhandlungen als eigenes Verschulden
2. Genehmigungspflicht mit einseitigem Widerrufsrecht
3. Durchreichung aller Vertragspflichten auf Subunternehmer ohne Anpassung
4. Fehlende Rückgriffsmöglichkeit gegen Subunternehmer
5. Pflicht zur jederzeitigen Auswechslung auf Kundenwunsch

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "exit": """TIEFENPRÜFUNG: EXIT / TRANSITION

Prüfe die markierte Klausel auf Exit-/Transitionsrisiken für den IT-Dienstleister:

1. Unverhältnismäßig lange Unterstützungspflichten nach Vertragsende
2. Datenherausgabe ohne klare Abgrenzung oder Kostenregelung
3. Pflicht zur kostenlosen Übergangsunterstützung
4. Wissenstransferpflichten ohne zeitliche Begrenzung
5. Herausgabe von Werkzeugen, Templates, Prozessdokumentation als Eigentum des Kunden

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "security": """TIEFENPRÜFUNG: INFORMATIONSSICHERHEIT

Prüfe die markierte Klausel auf Sicherheits-Risiken für den IT-Dienstleister:

1. Verschlüsselungsanforderungen ohne klare Spezifikation (welcher Standard, welche Schlüssellänge?)
2. Pflicht zur Duldung von Penetrationstests ohne Rahmenbedingungen
3. "Stand der Technik" ohne Definition oder Anpassungsklausel
4. Verpflichtung auf sich ändernde Kundensicherheitsrichtlinien
5. Incident-Response mit unrealistischen Fristen (< 24h für komplexe Vorfälle)
6. Nachweispflicht für Datenlöschung ohne angemessene Methodik

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",

    "change_control": """TIEFENPRÜFUNG: CHANGE MANAGEMENT / WEISUNGSRECHTE

Prüfe die markierte Klausel auf Change-Control-Risiken für den IT-Dienstleister:

1. Einseitiges Weisungsrecht ohne Zumutbarkeitsgrenzen
2. Änderungsrechte ohne Vergütungsanpassung
3. Fehlende Eskalations- oder Widerspruchsmechanismen
4. Pflicht zur Umsetzung von Änderungen "unverzüglich" ohne Prüfungsfrist
5. Dynamische Verweise auf externe Dokumente "in ihrer jeweiligen Fassung"

Liefere die gleichen Felder wie bei der Audit-Tiefenprüfung.""",
}

DEEP_CHECK_SYSTEM_TEMPLATE = """Du bist ein erfahrener Vertragsprüfer für IT-Outsourcing-Verträge.
Du führst eine TIEFENPRÜFUNG für eine bereits als problematisch identifizierte Klausel durch.
Die Erstprüfung hat diese Klausel als problematisch markiert — deine Aufgabe ist die Vertiefung.

SPRACH-REGEL: Alle Ausgaben auf Deutsch. evidence_text bleibt in Originalsprache des Vertrags.

{domain_prompt}

AUSGABEFORMAT — Antworte AUSSCHLIESSLICH mit einem JSON-Objekt:
{{
  "severity": "low|medium|high|critical",
  "deep_reason": "Detaillierte Erklärung des domänenspezifischen Risikos (3-4 Sätze, Deutsch)",
  "recommendation": "Konkrete Handlungsempfehlung (1-2 Sätze, Deutsch)",
  "negotiation_points": ["Verhandlungshebel 1", "Verhandlungshebel 2"],
  "alternative_wording": "Vorschlag für ausgewogenere Formulierung",
  "bidder_question": "Konkrete, beantwortbare Bieterfrage",
  "refined_problem_types": ["problem_type_1", "problem_type_2"],
  "evidence_text": "Exakter Originalwortlaut, der das Problem belegt"
}}"""


@dataclass
class DeepCheckResult:
    """Enrichment from a domain deep check."""
    domain: str
    severity: str = "low"
    deep_reason: str = ""
    recommendation: str = ""
    negotiation_points: list[str] = field(default_factory=list)
    alternative_wording: str = ""
    bidder_question: str = ""
    refined_problem_types: list[str] = field(default_factory=list)
    evidence_text: str = ""


async def run_deep_checks(
    problematic: list[ClauseScreenResult],
    config: LLMConfig,
) -> dict[str, list[DeepCheckResult]]:
    """Run domain-specific deep checks for all problematic clauses.

    Returns a dict mapping segment_id → list of DeepCheckResult.
    Only runs checks for domains that are actually needed.
    """
    results: dict[str, list[DeepCheckResult]] = {}

    for clause in problematic:
        domains = clause.deep_check_domains
        if not domains:
            # Fall back to trigger_domains if deep_check_domains is empty
            domains = clause.trigger_domains
        if not domains:
            continue

        # Only check domains we have prompts for
        domains = [d for d in domains if d in DOMAIN_PROMPTS]
        if not domains:
            continue

        clause_results: list[DeepCheckResult] = []
        for domain in domains:
            logger.info(f"Tiefenprüfung [{domain}]: Segment {clause.segment_id}")

            system_prompt = DEEP_CHECK_SYSTEM_TEMPLATE.format(
                domain_prompt=DOMAIN_PROMPTS[domain]
            )
            user_prompt = (
                f"Erstprüfung-Ergebnis:\n"
                f"- Problem-Typen: {', '.join(clause.problem_types)}\n"
                f"- Schwere: {clause.severity}\n"
                f"- Grund: {clause.reason}\n\n"
                f"Vertragsklausel:\n{clause.evidence_text or clause.segment_text[:2000]}"
            )

            try:
                raw = await llm_completion(
                    config=config,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.2,
                    max_tokens=2048,
                )
                result = _parse_deep_check(raw, domain)
                clause_results.append(result)
            except Exception as e:
                logger.warning(
                    f"Tiefenprüfung [{domain}] für {clause.segment_id} "
                    f"fehlgeschlagen: {e}"
                )

        if clause_results:
            results[clause.segment_id] = clause_results

    return results


def _parse_deep_check(raw: str, domain: str) -> DeepCheckResult:
    """Parse a deep check LLM response."""
    json_str = raw.strip()
    if "```" in json_str:
        parts = json_str.split("```")
        for part in parts[1:]:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                json_str = cleaned
                break

    try:
        start = json_str.find("{")
        end = json_str.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(json_str[start:end + 1])
        else:
            return DeepCheckResult(domain=domain)
    except json.JSONDecodeError:
        return DeepCheckResult(domain=domain)

    if not isinstance(parsed, dict):
        return DeepCheckResult(domain=domain)

    negotiation_points = parsed.get("negotiation_points", [])
    if not isinstance(negotiation_points, list):
        negotiation_points = []

    refined = parsed.get("refined_problem_types", [])
    if not isinstance(refined, list):
        refined = []

    return DeepCheckResult(
        domain=domain,
        severity=str(parsed.get("severity", "low")),
        deep_reason=str(parsed.get("deep_reason", "")),
        recommendation=str(parsed.get("recommendation", "")),
        negotiation_points=[str(p) for p in negotiation_points if p],
        alternative_wording=str(parsed.get("alternative_wording", "")),
        bidder_question=str(parsed.get("bidder_question", "")),
        refined_problem_types=[str(p) for p in refined if p],
        evidence_text=str(parsed.get("evidence_text", "")),
    )


def merge_deep_checks_into_findings(
    problematic: list[ClauseScreenResult],
    deep_results: dict[str, list[DeepCheckResult]],
) -> list[RawFinding]:
    """Merge first-read results with deep-check enrichments into RawFindings.

    Creates one RawFinding per problematic clause, enriched with the deepest
    severity and the combined negotiation/recommendation content from all
    domain deep checks that ran for it.
    """
    findings: list[RawFinding] = []

    for clause in problematic:
        checks = deep_results.get(clause.segment_id, [])

        # Start from the first-read data
        base_finding = clause.to_raw_finding()

        if not checks:
            findings.append(base_finding)
            continue

        # Escalate severity to highest from deep checks
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        max_severity = clause.severity
        for check in checks:
            if severity_order.get(check.severity, 0) > severity_order.get(max_severity, 0):
                max_severity = check.severity
        base_finding.risikostufe = normalize_severity(max_severity)

        # Merge deep reasons into erklaerung
        deep_reasons = [c.deep_reason for c in checks if c.deep_reason]
        if deep_reasons:
            base_finding.erklaerung = (
                clause.reason + "\n\n" + "\n\n".join(deep_reasons)
            )

        # Merge recommendations
        recommendations = [c.recommendation for c in checks if c.recommendation]
        if recommendations:
            base_finding.empfehlung = "\n".join(recommendations)

        # Merge alternative wording (take the first non-empty one)
        for check in checks:
            if check.alternative_wording:
                base_finding.alternativformulierung = check.alternative_wording
                break

        # Merge bidder questions
        for check in checks:
            if check.bidder_question:
                base_finding.bieterfrage = check.bidder_question
                break

        # Merge negotiation points
        all_negotiation = []
        for check in checks:
            all_negotiation.extend(check.negotiation_points)
        if all_negotiation:
            base_finding.verhandlungsargumente = "\n".join(
                f"- {p}" for p in all_negotiation
            )

        # Merge refined problem types into risiko_detail
        all_types = set(clause.problem_types)
        for check in checks:
            all_types.update(check.refined_problem_types)
        base_finding.risiko_detail = ", ".join(sorted(all_types))

        # Use best evidence text
        for check in checks:
            if check.evidence_text and len(check.evidence_text) > len(base_finding.scope_text or ""):
                base_finding.scope_text = check.evidence_text
                base_finding.textstelle = check.evidence_text[:2000]

        findings.append(base_finding)

    return findings
