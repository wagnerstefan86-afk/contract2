"""Stage A+B: Universal Risk Read — clause-aware first-read screening.

Every clause/block is read exactly once. The LLM outputs a strict structured
risk screen that decides whether the clause is actually problematic for the
IT service provider.  Only clauses with is_problematic=true survive into the
deep-check stage.

This replaces the old 4-pass brute-force model (breit, perspektive, implizit,
bankregulatorik) with a single, focused first-read that asks:
  "Why is this clause problematic for the provider?"
NOT:
  "What is this clause about?"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_completion
from app.discovery.passes.base import (
    RawFinding,
    build_source_fingerprint,
    normalize_severity,
    get_perspective_prompt,
    MIN_SCOPE_TEXT_LENGTH,
    _extract_evidence_text,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output model for the first-read stage
# ---------------------------------------------------------------------------

# Normalized problem type taxonomy
PROBLEM_TYPES = {
    "regulatory_shift",
    "bcm_transfer",
    "risk_management_transfer",
    "unclear_audit",
    "excessive_reporting",
    "unbalanced_liability",
    "subcontractor_liability",
    "open_scope",
    "one_sided_rights",
    "undefined_terms",
    "unclear_acceptance",
    "unclear_change_control",
    "vague_security_obligation",
    "excessive_evidence_obligation",
    "unrestricted_compliance_passthrough",
    "exit_or_transition_burden",
    "unreasonable_response_or_restore_commitment",
}

# Deep-check domain routing keys
DEEP_CHECK_DOMAINS = {
    "audit",
    "reporting",
    "bcm",
    "liability",
    "regulatory",
    "scope",
    "subcontractor",
    "exit",
    "security",
    "change_control",
}


@dataclass
class ClauseScreenResult:
    """Structured output of the universal risk read for one clause/segment."""
    segment_id: str
    segment_text: str
    is_problematic: bool
    problem_types: list[str] = field(default_factory=list)
    severity: str = "low"
    reason: str = ""
    evidence_text: str = ""
    trigger_domains: list[str] = field(default_factory=list)
    needs_deep_check: bool = False
    deep_check_domains: list[str] = field(default_factory=list)
    # Category mapping for backward compatibility with RawFinding
    category: str = ""

    def to_raw_finding(self) -> RawFinding:
        """Convert a problematic screen result to a RawFinding for downstream compatibility."""
        # Map problem_types to a primary category for the existing pipeline
        kategorie = self.category or _problem_type_to_category(self.problem_types)
        risikostufe = normalize_severity(self.severity)
        textstelle = self.evidence_text or self.segment_text[:2000]
        truncated = textstelle[:2000]

        return RawFinding(
            textstelle=truncated,
            kategorie=kategorie,
            kurzbeschreibung=self.reason[:200] if self.reason else "",
            erklaerung=self.reason,
            empfehlung="",  # Populated by deep checks or editorial
            risikostufe=risikostufe,
            segment_ids=[self.segment_id],
            quelle_pass="Risiko-Erstprüfung",
            scope_type="paragraph",
            scope_text=self.evidence_text or self.segment_text[:2000],
            trigger_spans=[],
            source_fingerprint=build_source_fingerprint(truncated, [self.segment_id]),
        )


def _problem_type_to_category(problem_types: list[str]) -> str:
    """Map problem_types to the existing category enum for backward compatibility."""
    _MAP = {
        "regulatory_shift": "Compliance",
        "bcm_transfer": "BCM",
        "risk_management_transfer": "Compliance",
        "unclear_audit": "Audit",
        "excessive_reporting": "Reporting",
        "unbalanced_liability": "Haftung",
        "subcontractor_liability": "Subunternehmer",
        "open_scope": "Leistungsumfang & Abgrenzung",
        "one_sided_rights": "Weisungsrecht",
        "undefined_terms": "Vertragsmanagement",
        "unclear_acceptance": "Leistungsumfang & Abgrenzung",
        "unclear_change_control": "Vertragsmanagement",
        "vague_security_obligation": "Informationssicherheit",
        "excessive_evidence_obligation": "Audit",
        "unrestricted_compliance_passthrough": "Compliance",
        "exit_or_transition_burden": "Exit",
        "unreasonable_response_or_restore_commitment": "Verfügbarkeit & Betrieb",
    }
    for pt in problem_types:
        if pt in _MAP:
            return _MAP[pt]
    return "Sonstiges"


# ---------------------------------------------------------------------------
# System prompt for the universal risk read
# ---------------------------------------------------------------------------

RISK_SCREEN_SYSTEM_PROMPT = """Du bist ein Vertragsrisikoanalyse-System für IT-Outsourcing-Verträge.
Du prüfst den Vertrag aus Sicht eines NICHT-REGULIERTEN IT-Dienstleisters (Auftragnehmer).

═══════════════════════════════════════════
DEINE AUFGABE
═══════════════════════════════════════════
Lies jeden Vertragsabschnitt und beantworte EINE Frage:
→ Erzeugt diese Klausel ein konkretes vertragliches PROBLEM für den IT-Dienstleister?

Du sollst NICHT fragen:
- "Worum geht es in dieser Klausel?"
- "Welche Pflichten gibt es?"
- "Welche InfoSec-Themen werden erwähnt?"

Du MUSST fragen:
- "Warum ist diese Klausel problematisch für den Dienstleister?"
- "Schafft diese Klausel eine unausgewogene / vage / übermäßige / verlagerte Pflicht?"
- "Wenn ja: Was genau ist das vertragliche Problem und wo steht der Beleg?"

═══════════════════════════════════════════
PROBLEMERKENNUNGSREGELN
═══════════════════════════════════════════
Markiere is_problematic=true NUR wenn MINDESTENS eine dieser Bedingungen zutrifft:

1. Eine Pflicht wird auf den Dienstleister verlagert, die zu breit, zu vage, zu offen oder unverhältnismäßig ist.
2. Der Dienstleister wird für regulatorische, BCM-, Risikomanagement-, Audit-, Reporting- oder Compliance-Lasten verantwortlich gemacht, die über den angemessenen Leistungsumfang hinausgehen.
3. Ein Recht des Auftraggebers ist einseitig, unzureichend begrenzt, oder operativ/finanziell riskant für den Dienstleister.
4. Eine Haftungs-/Freistellungs-/Subunternehmerklausel ist unausgewogen oder unbegrenzt.
5. Die Klausel schafft unklare Abnahme-, Umfangs-, Reporting-, Audit-, Wiederherstellungs- oder Nachweispflichten.
6. Pflichten sind nicht klar begrenzt durch Machbarkeit, Zumutbarkeit, Kostenzuordnung oder vereinbarten Umfang.

═══════════════════════════════════════════
ANTI-NOISE-REGELN (ZWINGEND)
═══════════════════════════════════════════
Markiere is_problematic=false wenn die Klausel:
- Rein beschreibend ist (Vertragsstruktur, Definitionen ohne Pflichtausweitung)
- Neutral oder ausgewogen ist
- Marktüblich / branchenstandard ist
- Nur auf Sicherheit/Compliance VERWEIST ohne Lastenverlagerung auf den Dienstleister
- Allgemeine Aussagen ohne konkreten Nachteil für den Dienstleister enthält
- Standard-Geheimhaltungs-, Datenschutz- oder IP-Klauseln ohne Übermaß enthält

KONKRETE BEISPIELE:

NICHT problematisch (is_problematic=false):
- "Der Auftragnehmer hält ISO 27001 ein und unterhält angemessene Sicherheitskontrollen."
  → Standard-Erwartung, kein automatisches Problem.
- "Die Parteien vereinbaren Vertraulichkeit gemäß den üblichen Bedingungen."
  → Ausgewogene Standardklausel.
- "Der Auftragnehmer benennt einen Ansprechpartner für Sicherheitsfragen."
  → Normale organisatorische Pflicht.

PROBLEMATISCH (is_problematic=true):
- "Der Auftragnehmer stellt jederzeit die Einhaltung aller für den Auftraggeber geltenden regulatorischen Anforderungen sicher, einschließlich künftiger Änderungen, ohne Zusatzkosten."
  → regulatory_shift / unrestricted_compliance_passthrough
- "Der Auftraggeber kann jederzeit Berichte, Nachweise, Dokumentationen und Prozessanpassungen verlangen, soweit vom Auftraggeber als angemessen erachtet."
  → excessive_reporting / unclear_audit / one_sided_rights
- "Der Auftragnehmer ist verantwortlich für die vollständige Umsetzung und laufende Pflege der BCM- und Risikomanagement-Anforderungen des Auftraggebers."
  → bcm_transfer / risk_management_transfer

═══════════════════════════════════════════
PROBLEM-TAXONOMIE
═══════════════════════════════════════════
Verwende diese normalisierten problem_types:
- regulatory_shift — Regulatorische Pflichten auf den Dienstleister verlagert
- bcm_transfer — BCM/ITSCM-Verantwortung auf den Dienstleister übertragen
- risk_management_transfer — Risikomanagement-Pflichten verlagert
- unclear_audit — Unklare, unbegrenzte oder einseitige Auditrechte
- excessive_reporting — Übermäßige Berichts-/Nachweis-/Dokumentationspflichten
- unbalanced_liability — Unausgewogene oder unbegrenzte Haftung
- subcontractor_liability — Unausgewogene Subunternehmerhaftung
- open_scope — Offener/unklarer Leistungsumfang, Scope-Creep-Risiko
- one_sided_rights — Einseitige Rechte (Weisung, Änderung, Kündigung)
- undefined_terms — Unbestimmte Begriffe, vage Standards
- unclear_acceptance — Unklare Abnahmekriterien oder -verfahren
- unclear_change_control — Fehlendes oder einseitiges Change-Management
- vague_security_obligation — Vage Sicherheitspflichten ("Stand der Technik" ohne Grenzen)
- excessive_evidence_obligation — Übermäßige Nachweispflichten
- unrestricted_compliance_passthrough — Pauschalverweis auf alle Kundenanforderungen
- exit_or_transition_burden — Unverhältnismäßige Exit-/Transitionspflichten
- unreasonable_response_or_restore_commitment — Unrealistische Reaktions-/Wiederherstellungszeiten

DEEP-CHECK-DOMAINS (für Routing in die Tiefenprüfung):
audit, reporting, bcm, liability, regulatory, scope, subcontractor, exit, security, change_control

═══════════════════════════════════════════
SPRACH-REGEL
═══════════════════════════════════════════
- reason: MUSS auf Deutsch sein.
- evidence_text: MUSS exakter Originalwortlaut aus dem Vertragsdokument sein (Originalsprache beibehalten).
- category: MUSS auf Deutsch sein.
- problem_types, trigger_domains, deep_check_domains: englische Schlüsselwörter (Taxonomy).

═══════════════════════════════════════════
AUSGABEFORMAT
═══════════════════════════════════════════
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Für JEDEN Abschnitt genau EIN Objekt.

Wenn der Abschnitt problematisch ist:
{
  "is_problematic": true,
  "problem_types": ["regulatory_shift", "excessive_reporting"],
  "severity": "low|medium|high|critical",
  "reason": "Kurze, konkrete Erklärung auf Deutsch, warum dies für den Dienstleister problematisch ist (2-3 Sätze)",
  "evidence_text": "Exakter Originalwortlaut aus dem Vertragsdokument, der das Problem belegt",
  "category": "Deutsche Kategorie (z.B. Compliance, Audit, Haftung)",
  "trigger_domains": ["regulatory", "reporting"],
  "needs_deep_check": true,
  "deep_check_domains": ["regulatory", "reporting"]
}

Wenn der Abschnitt NICHT problematisch ist:
{
  "is_problematic": false
}

═══════════════════════════════════════════
QUALITÄTSREGELN
═══════════════════════════════════════════
- Pro Abschnitt maximal EIN Ergebnisobjekt.
- Bei mehreren Problemen im selben Abschnitt: ALLE problem_types in einem Objekt auflisten.
- evidence_text MUSS der exakte Originaltext sein — NICHT umformuliert.
- reason muss verhandlungstauglich formuliert sein: Klauselwirkung → konkretes Risiko → Verhandlungsrelevanz.
- Weniger Funde mit hoher Qualität sind IMMER besser als viele schwache Signale.
- Wenn unklar: is_problematic=false. Im Zweifel KEIN Fund."""


# ---------------------------------------------------------------------------
# Main screening function
# ---------------------------------------------------------------------------

async def run_risk_screen(
    segments: list[Segment],
    config: LLMConfig,
    full_text: str,
    perspective: str = "provider",
) -> list[ClauseScreenResult]:
    """Run the universal risk read across all segments.

    Returns one ClauseScreenResult per segment. Non-problematic clauses have
    is_problematic=false and will be dropped by the hard filter.
    """
    results: list[ClauseScreenResult] = []
    system_prompt = RISK_SCREEN_SYSTEM_PROMPT + get_perspective_prompt(perspective)

    for seg in segments:
        logger.info(f"Risiko-Erstprüfung: Segment {seg.id}")
        user_prompt = (
            f"Analysiere den folgenden Vertragsabschnitt. "
            f"Ist diese Klausel problematisch für den IT-Dienstleister?\n\n"
            f"{seg.fenster_text}"
        )

        try:
            raw_response = await llm_completion(
                config=config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=2048,
            )

            parsed = _parse_screen_response(raw_response, seg)
            results.append(parsed)

            if parsed.is_problematic:
                logger.info(
                    f"Risiko-Erstprüfung: {seg.id} → PROBLEMATISCH "
                    f"({', '.join(parsed.problem_types)}, {parsed.severity})"
                )
            else:
                logger.debug(f"Risiko-Erstprüfung: {seg.id} → nicht problematisch")
        except Exception as e:
            logger.warning(f"Risiko-Erstprüfung: {seg.id} fehlgeschlagen: {e}")
            # On failure, include the segment as problematic to avoid silent loss
            results.append(ClauseScreenResult(
                segment_id=seg.id,
                segment_text=seg.fenster_text,
                is_problematic=True,
                problem_types=["undefined_terms"],
                severity="low",
                reason=f"Erstprüfung fehlgeschlagen: {type(e).__name__}. Zur Sicherheit als problematisch eingestuft.",
                evidence_text=seg.text[:500],
                trigger_domains=[],
                needs_deep_check=False,
                deep_check_domains=[],
                category="Sonstiges",
            ))

    return results


def _parse_screen_response(raw: str, seg: Segment) -> ClauseScreenResult:
    """Parse the LLM response into a ClauseScreenResult."""
    # Extract JSON from response (handle markdown code blocks)
    json_str = raw.strip()
    if "```" in json_str:
        parts = json_str.split("```")
        for part in parts[1:]:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("[") or cleaned.startswith("{"):
                json_str = cleaned
                break

    # Parse JSON — could be array or object
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        # Try to find JSON within the response
        start = json_str.find("[")
        if start == -1:
            start = json_str.find("{")
        end = max(json_str.rfind("]"), json_str.rfind("}"))
        if start >= 0 and end > start:
            try:
                parsed = json.loads(json_str[start:end + 1])
            except json.JSONDecodeError:
                logger.warning(f"JSON-Parsing fehlgeschlagen für {seg.id}")
                return _default_non_problematic(seg)
        else:
            return _default_non_problematic(seg)

    # Normalize: if array, take first element
    if isinstance(parsed, list):
        if not parsed:
            return _default_non_problematic(seg)
        parsed = parsed[0]

    if not isinstance(parsed, dict):
        return _default_non_problematic(seg)

    is_problematic = bool(parsed.get("is_problematic", False))

    if not is_problematic:
        return _default_non_problematic(seg)

    # Extract evidence_text, validating against original segment text
    evidence_raw = str(parsed.get("evidence_text", ""))
    evidence_text = _extract_evidence_text(
        llm_scope_text=evidence_raw,
        segment_text=seg.fenster_text,
        trigger_spans=[],
    )

    problem_types = parsed.get("problem_types", [])
    if not isinstance(problem_types, list):
        problem_types = []
    # Normalize to known taxonomy
    problem_types = [pt for pt in problem_types if isinstance(pt, str)]

    trigger_domains = parsed.get("trigger_domains", [])
    if not isinstance(trigger_domains, list):
        trigger_domains = []

    deep_check_domains = parsed.get("deep_check_domains", [])
    if not isinstance(deep_check_domains, list):
        deep_check_domains = []

    severity = str(parsed.get("severity", "low")).lower()
    if severity not in ("low", "medium", "high", "critical"):
        severity = "low"

    return ClauseScreenResult(
        segment_id=seg.id,
        segment_text=seg.fenster_text,
        is_problematic=True,
        problem_types=problem_types,
        severity=severity,
        reason=str(parsed.get("reason", "")),
        evidence_text=evidence_text,
        trigger_domains=trigger_domains,
        needs_deep_check=bool(parsed.get("needs_deep_check", False)),
        deep_check_domains=deep_check_domains,
        category=str(parsed.get("category", "")),
    )


def _default_non_problematic(seg: Segment) -> ClauseScreenResult:
    """Return a non-problematic result for a segment."""
    return ClauseScreenResult(
        segment_id=seg.id,
        segment_text=seg.fenster_text,
        is_problematic=False,
    )


# ---------------------------------------------------------------------------
# Hard filter: extract only problematic clauses
# ---------------------------------------------------------------------------

def filter_problematic(
    results: list[ClauseScreenResult],
) -> tuple[list[ClauseScreenResult], list[ClauseScreenResult]]:
    """Partition screen results into problematic and non-problematic.

    Returns (problematic, dropped).
    """
    problematic = [r for r in results if r.is_problematic]
    dropped = [r for r in results if not r.is_problematic]
    return problematic, dropped
