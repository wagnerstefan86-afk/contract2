"""Steps 6-10 for the case-based multi-document pipeline.

Step 6 — Screening: LLM classification of sections (irrelevant/context/risk_candidate)
Step 7 — Extraction: LLM finding extraction per reviewable section
Step 8 — Topic Clustering: Group findings into themes by similarity
Step 9 — Consolidation: LLM-based theme merging
Step 10 — Final Editorial: LLM reduction to core negotiation-relevant themes

Includes:
- Screening guardrails (Tasks 3)
- Cluster quality diagnostics (Task 4)
- Editorial guardrails with retry (Task 5)
- Robust JSON parsing with LLM repair (Task 6)
- Deterministic clustering (Task 7)
- Paginated section loading (Task 9)
- Debug snapshots (Task 2)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_document import CaseDocument
from app.models.document_section import DocumentSection
from app.models.fundstelle import Fundstelle, PruefStatus
from app.models.positive_control import PositiveControl
from app.models.theme import Theme, ThemeEvidence
from app.models.pipeline_metrics import ThemeDebugSnapshot
from app.models.enums import (
    SectionRouting, ControlType, ControlStatus,
    EvidenceRole, FinalSelectionBasis,
)
from app.discovery.llm_client import LLMConfig, llm_completion, estimate_tokens, get_throttle

logger = logging.getLogger(__name__)

# --- Constants ---
SECTION_BATCH_SIZE = 50
LLM_BATCH_SIZE = 5
MAX_EDITORIAL_THEMES = 15
SCREENING_HIGH_REMOVAL_THRESHOLD = 0.90
SCREENING_LOW_REMOVAL_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Task 6 — Robust JSON parsing with LLM repair
# ---------------------------------------------------------------------------

async def _robust_parse_json_array(
    raw: str,
    config: LLMConfig | None = None,
    context: str = "",
) -> list[dict]:
    """Parse a JSON array with multi-step repair on failure.

    1. Direct parse
    2. Strip markdown and re-parse
    3. LLM repair request (if config provided)
    4. Return empty list
    """
    # Step 1: direct parse
    cleaned = raw.strip()

    # Step 2: strip markdown
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts[1:]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                cleaned = part
                break

    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    # Step 3: LLM repair
    if config:
        try:
            repair_prompt = (
                "Die folgende LLM-Antwort enthält ungültiges JSON. "
                "Repariere es und gib NUR ein valides JSON-Array zurück.\n\n"
                f"Kontext: {context}\n\nRohantwort:\n{raw[:3000]}"
            )
            repaired = await llm_completion(
                config,
                "Du bist ein JSON-Reparatur-Assistent. Antworte NUR mit validem JSON.",
                repair_prompt,
                temperature=0.0,
                max_tokens=4096,
            )
            repaired_clean = repaired.strip()
            rs = repaired_clean.find("[")
            re_ = repaired_clean.rfind("]")
            if rs >= 0 and re_ > rs:
                parsed = json.loads(repaired_clean[rs:re_ + 1])
                if isinstance(parsed, list):
                    logger.info(f"JSON-Reparatur erfolgreich ({context})")
                    return parsed
        except Exception as e:
            logger.warning(f"JSON-Reparatur fehlgeschlagen ({context}): {e}")

    # Step 4: fallback
    logger.warning(f"JSON-Array Parse endgültig fehlgeschlagen ({context}). Raw: {raw[:200]}")
    return []


async def _robust_parse_json_object(
    raw: str,
    config: LLMConfig | None = None,
    context: str = "",
) -> dict | None:
    """Parse a JSON object with multi-step repair on failure."""
    cleaned = raw.strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts[1:]:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                cleaned = part
                break

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(cleaned[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # LLM repair
    if config:
        try:
            repair_prompt = (
                "Die folgende LLM-Antwort enthält ungültiges JSON. "
                "Repariere es und gib NUR ein valides JSON-Objekt zurück.\n\n"
                f"Kontext: {context}\n\nRohantwort:\n{raw[:3000]}"
            )
            repaired = await llm_completion(
                config,
                "Du bist ein JSON-Reparatur-Assistent. Antworte NUR mit validem JSON.",
                repair_prompt,
                temperature=0.0,
                max_tokens=4096,
            )
            rs = repaired.find("{")
            re_ = repaired.rfind("}")
            if rs >= 0 and re_ > rs:
                parsed = json.loads(repaired[rs:re_ + 1])
                if isinstance(parsed, dict):
                    logger.info(f"JSON-Objekt-Reparatur erfolgreich ({context})")
                    return parsed
        except Exception as e:
            logger.warning(f"JSON-Objekt-Reparatur fehlgeschlagen ({context}): {e}")

    logger.warning(f"JSON-Objekt Parse endgültig fehlgeschlagen ({context}). Raw: {raw[:200]}")
    return None


# ---------------------------------------------------------------------------
# Task 2 — Debug snapshot helper
# ---------------------------------------------------------------------------

async def _save_debug_snapshot(
    db: AsyncSession,
    case_id: uuid.UUID,
    stage: str,
    data: dict | list,
) -> None:
    """Store a debug snapshot (summaries only, no full text)."""
    try:
        snapshot = ThemeDebugSnapshot(
            case_id=case_id,
            stage=stage,
            data_json=data if isinstance(data, dict) else {"items": data},
        )
        db.add(snapshot)
        await db.flush()
    except Exception as e:
        logger.warning(f"Debug-Snapshot speichern fehlgeschlagen ({stage}): {e}")


# ---------------------------------------------------------------------------
# Step 6 — Screening
# ---------------------------------------------------------------------------

SCREENING_SYSTEM_PROMPT = """Du bist ein Vertrags-Screening-Assistent. Klassifiziere den folgenden Vertragsabschnitt.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt (kein Markdown, keine Erklärung):
{
  "relevance": "irrelevant" | "context" | "risk_candidate",
  "categories": ["KATEGORIE1", "KATEGORIE2"],
  "reasoning": "Kurze Begründung (1 Satz)"
}

Regeln:
- "irrelevant": Inhaltsverzeichnis, reine Definitionen ohne Risikorelevanz, Anhang-Verweise, Formatierungs-Artefakte
- "context": Standardklauseln, allgemeine Regelungen die als Kontext nützlich sind, aber kein direktes Risiko darstellen
- "risk_candidate": Klauseln mit Risikopotenzial — Haftung, SLA, Datenschutz, Audit, Kündigung, Sicherheit, Verfügbarkeit, Exit, Subunternehmer

Kategorien (wähle 1-3): SECURITY_GOVERNANCE, CERTIFICATION_ASSURANCE, AUDIT_RIGHTS, SUBPROCESSING, AVAILABILITY_SLA, INCIDENT_MANAGEMENT, CHANGE_MANAGEMENT, EXIT_PORTABILITY, BACKUP_RECOVERY, BCM_ITSCM, LIABILITY, PERFORMANCE_REPORTING, DATA_PROTECTION, OTHER"""


async def screen_sections(
    case_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
    policy_rules: list | None = None,
) -> dict:
    """Step 6: Screen all REVIEWABLE sections via lightweight LLM classification.

    Returns metrics dict with counts. Includes screening guardrails (Task 3).
    Loads sections in paginated batches (Task 9).
    """
    metrics = {"total": 0, "risk_candidate": 0, "context": 0, "ignored": 0, "errors": 0}
    offset = 0

    while True:
        result = await db.execute(
            select(DocumentSection)
            .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
            .where(CaseDocument.analysis_case_id == case_id)
            .where(DocumentSection.routing == SectionRouting.REVIEWABLE.value)
            .where(DocumentSection.screening_status == None)  # noqa: E711
            .order_by(DocumentSection.section_index)
            .limit(SECTION_BATCH_SIZE)
            .offset(offset)
        )
        sections = list(result.scalars().all())
        if not sections:
            break

        metrics["total"] += len(sections)

        # Process in LLM batches of 5
        for i in range(0, len(sections), LLM_BATCH_SIZE):
            batch = sections[i:i + LLM_BATCH_SIZE]
            tasks = [_screen_single_section(section, config) for section in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for section, res in zip(batch, results):
                if isinstance(res, Exception):
                    logger.warning(f"Screening fehlgeschlagen für Section {section.id}: {res}")
                    section.screening_status = "error"
                    section.screening_result = {"error": str(res)}
                    metrics["errors"] += 1
                    continue

                relevance = res.get("relevance", "risk_candidate")
                section.screening_result = res

                if relevance == "irrelevant":
                    section.screening_status = "ignored"
                    metrics["ignored"] += 1
                elif relevance == "context":
                    section.screening_status = "context"
                    metrics["context"] += 1
                else:
                    section.screening_status = "analyze"
                    metrics["risk_candidate"] += 1

            await db.flush()

        offset += SECTION_BATCH_SIZE

    await db.commit()

    # Save debug snapshot
    await _save_debug_snapshot(db, case_id, "screening_result", metrics)

    # Task 3 — Screening guardrails: generate warnings
    warnings = _check_screening_guardrails(metrics)
    if warnings:
        metrics["warnings"] = warnings

    logger.info(
        f"Screening abgeschlossen: {metrics['total']} Sections — "
        f"{metrics['risk_candidate']} risk_candidate, {metrics['context']} context, "
        f"{metrics['ignored']} ignored, {metrics['errors']} errors"
    )
    return metrics


def _check_screening_guardrails(metrics: dict) -> list[str]:
    """Task 3: Check screening ratios and flag anomalies."""
    warnings = []
    total = metrics.get("total", 0)
    if total == 0:
        return warnings

    analyzed = metrics.get("risk_candidate", 0)
    removal_rate = 1.0 - (analyzed / total)

    if removal_rate > SCREENING_HIGH_REMOVAL_THRESHOLD:
        warnings.append(
            f"SCREENING_HIGH_REMOVAL: {removal_rate:.0%} der Sections wurden aussortiert "
            f"({analyzed}/{total} verbleibend). Mögliche Ursache: zu aggressives Screening."
        )

    if removal_rate < SCREENING_LOW_REMOVAL_THRESHOLD:
        warnings.append(
            f"SCREENING_LOW_REMOVAL: Nur {removal_rate:.0%} aussortiert "
            f"({analyzed}/{total} verbleibend). Screening filtert wenig — hoher LLM-Aufwand."
        )

    return warnings


async def _screen_single_section(section: DocumentSection, config: LLMConfig) -> dict:
    """Screen a single section via LLM."""
    text = section.raw_text[:3000]
    user_prompt = f"Abschnitt (Seite {section.page_from or '?'}, {section.char_count} Zeichen):\n\n{text}"

    try:
        raw = await llm_completion(
            config, SCREENING_SYSTEM_PROMPT, user_prompt,
            temperature=0.1, max_tokens=256,
        )
        result = await _robust_parse_json_object(raw, context="screening")
        if result and "relevance" in result:
            return result
    except Exception as e:
        logger.warning(f"Screening LLM-Fehler: {e}")

    # Default to risk_candidate on any failure — never lose content
    return {"relevance": "risk_candidate", "categories": ["OTHER"], "reasoning": "Parse/LLM-Fehler — als risk_candidate bewertet"}


# ---------------------------------------------------------------------------
# Step 7 — Extraction
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a contract risk extraction system for IT service provider contract reviews.
Your task is NOT to list every potentially problematic sentence.
Your task is to extract only MATERIAL contractual risks that would realistically be raised during a professional contract review.

Important principle:
Most paragraphs do NOT contain a standalone contractual risk.
Only produce a finding when the paragraph contains a clear contractual risk that would require clarification, negotiation, or mitigation.

--------------------------------
RISK DETECTION RULES
--------------------------------
Create a finding ONLY if at least one of the following conditions is true:
1. The contract creates a one-sided obligation or right
   (e.g. unilateral instruction rights, unilateral changes, unilateral termination).
2. Liability or responsibility is unclear, unlimited, or transferred broadly.
3. The scope of services is vague, open-ended, or allows uncontrolled expansion.
4. Compliance, security, regulatory, or reporting obligations are imposed without clear limits.
5. Audit or control rights create operational or legal risk.
6. Subcontracting or delegation creates unclear responsibility or liability.
7. An obligation exists without defined limits, criteria, or boundaries.

If none of these conditions apply, the paragraph has NO_FINDING.

--------------------------------
ANTI-NOISE RULES
--------------------------------
DO NOT create a finding when:
- The text only describes normal contractual structure.
- The clause is neutral or balanced.
- The clause merely references compliance or standards without imposing unclear obligations.
- The risk only exists when taken out of context.

--------------------------------
CONTEXT RULE
--------------------------------
A finding must always be based on the full paragraph or clause context.
Never generate findings based on isolated sentences or fragments.

--------------------------------
DEDUPLICATION RULE
--------------------------------
Each paragraph may produce at most one finding.
If multiple potential risks appear in the paragraph,
choose the single most relevant contractual risk.

--------------------------------
POSITIVE CONTROLS
--------------------------------
If the paragraph contains a certification, standard, or positive assurance
(e.g. ISO 27001, SOC 2, explicit security commitment), return it as a
positive_control instead of a risk finding.

--------------------------------
OUTPUT FORMAT
--------------------------------
Return ONLY a JSON array (no markdown, no explanation).
Each element is either a risk finding or a positive control:

[
  {
    "scope_type": "paragraph",
    "scope_text": "full paragraph text from the document",
    "trigger_spans": ["short trigger phrase 1", "optional trigger phrase 2"],
    "category": "CATEGORY",
    "severity": "low|medium|high|critical",
    "description": "short explanation of the contractual risk (2-3 sentences)",
    "ist_positiv": false
  },
  {
    "scope_text": "paragraph with positive assurance",
    "description": "ISO 27001 certification confirmed",
    "ist_positiv": true
  }
]

If NO paragraphs contain material risks or positive controls, return: []

Categories: SECURITY_GOVERNANCE, CERTIFICATION_ASSURANCE, AUDIT_RIGHTS, SUBPROCESSING, AVAILABILITY_SLA, INCIDENT_MANAGEMENT, CHANGE_MANAGEMENT, EXIT_PORTABILITY, BACKUP_RECOVERY, BCM_ITSCM, LIABILITY, PERFORMANCE_REPORTING, DATA_PROTECTION, OTHER

--------------------------------
QUALITY REQUIREMENTS
--------------------------------
- Only extract risks that a legal or security reviewer would actually discuss.
- Prefer fewer, higher-quality findings.
- Avoid creating multiple findings for variations of the same clause.
- Never invent risks that are not clearly supported by the paragraph.
- A good extraction result contains few but meaningful findings, not many weak signals."""

# Minimum chars for scope_text to be considered valid paragraph-level evidence
MIN_SCOPE_TEXT_LENGTH = 80

# Map LLM severity labels to internal Risikostufe values
_SEVERITY_MAP = {
    "critical": "Kritisch",
    "high": "Hoch",
    "medium": "Mittel",
    "low": "Niedrig",
    # Pass-through for legacy or German labels
    "kritisch": "Kritisch",
    "hoch": "Hoch",
    "mittel": "Mittel",
    "niedrig": "Niedrig",
    "hinweis": "Hinweis",
}


async def extract_findings(
    case_id: uuid.UUID,
    analyse_id: uuid.UUID,
    vertrag_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
    policy_rules: list | None = None,
) -> dict:
    """Step 7: Extract findings from all screened risk_candidate sections.

    Returns metrics dict. Uses paginated loading (Task 9).
    """
    metrics = {"total_sections": 0, "total_findings": 0, "total_positive_controls": 0, "errors": 0}
    offset = 0
    extraction_summary = []

    while True:
        result = await db.execute(
            select(DocumentSection)
            .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
            .where(CaseDocument.analysis_case_id == case_id)
            .where(DocumentSection.screening_status == "analyze")
            .where(DocumentSection.extraction_status == None)  # noqa: E711
            .order_by(DocumentSection.section_index)
            .limit(SECTION_BATCH_SIZE)
            .offset(offset)
        )
        sections = list(result.scalars().all())
        if not sections:
            break

        metrics["total_sections"] += len(sections)

        for i in range(0, len(sections), LLM_BATCH_SIZE):
            batch = sections[i:i + LLM_BATCH_SIZE]
            tasks = [_extract_single_section(section, config) for section in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for section, res in zip(batch, results):
                if isinstance(res, Exception):
                    logger.warning(f"Extraktion fehlgeschlagen für Section {section.id}: {res}")
                    section.extraction_status = "error"
                    metrics["errors"] += 1
                    continue

                section.extraction_status = "completed"
                section_findings = 0

                for finding_data in res:
                    # Skip NO_FINDING entries
                    if finding_data.get("result") == "NO_FINDING":
                        continue

                    ist_positiv = finding_data.get("ist_positiv", False)

                    if ist_positiv:
                        pc = PositiveControl(
                            analysis_case_id=case_id,
                            case_document_id=section.case_document_id,
                            document_section_id=section.id,
                            control_type=ControlType.STANDARD_CONTROL.value,
                            control_value=finding_data.get("description", finding_data.get("kurzbeschreibung", ""))[:500],
                            source_text=(finding_data.get("scope_text") or finding_data.get("textstelle") or "")[:500],
                            status=ControlStatus.NEEDS_REVIEW.value,
                        )
                        db.add(pc)
                        metrics["total_positive_controls"] += 1
                        continue

                    # --- Map field names (new prompt → model) ---
                    # "description" → kurzbeschreibung + erklaerung
                    description = finding_data.get("description") or ""
                    kurzbeschreibung = finding_data.get("kurzbeschreibung") or description[:150] or "Unbekannt"
                    erklaerung = finding_data.get("erklaerung") or description or None
                    # "category" → kategorie
                    kategorie = finding_data.get("category") or finding_data.get("kategorie") or "OTHER"
                    # "severity" → risikostufe (with mapping)
                    raw_severity = (finding_data.get("severity") or finding_data.get("risikostufe") or "medium").lower()
                    risikostufe = _SEVERITY_MAP.get(raw_severity, "Mittel")

                    # Policy post-filtering
                    is_suppressed = False
                    suppression_reason = None
                    policy_rule_id = None
                    if policy_rules:
                        try:
                            from app.discovery.policy_engine import scan_finding
                            matches = scan_finding(
                                kurzbeschreibung,
                                kategorie,
                                policy_rules,
                            )
                            for m in matches:
                                if m.action == "SUPPRESS_RISK":
                                    is_suppressed = True
                                    suppression_reason = m.rule_name
                                    policy_rule_id = uuid.UUID(m.rule_id) if m.rule_id else None
                                    break
                        except Exception as e:
                            logger.warning(f"Policy scan_finding Fehler: {e}")

                    # --- Paragraph-level evidence fields ---
                    scope_text = finding_data.get("scope_text") or ""
                    scope_type = finding_data.get("scope_type") or ""
                    raw_trigger_spans = finding_data.get("trigger_spans")
                    trigger_spans = (
                        [str(s) for s in raw_trigger_spans if s]
                        if isinstance(raw_trigger_spans, list)
                        else []
                    )

                    # Quality guardrail: if scope_text is too short, fall
                    # back to the full section text as the evidence context
                    if len(scope_text) < MIN_SCOPE_TEXT_LENGTH and section.raw_text:
                        scope_text = section.raw_text
                        scope_type = "paragraph"

                    # Backward compat: populate legacy textstelle with
                    # scope_text (paragraph context) so old pages still work
                    legacy_textstelle = scope_text[:2000] if scope_text else finding_data.get("textstelle", "")[:500]

                    fundstelle = Fundstelle(
                        analyse_id=analyse_id,
                        vertrag_id=vertrag_id,
                        analysis_case_id=case_id,
                        case_document_id=section.case_document_id,
                        document_section_id=section.id,
                        textstelle=legacy_textstelle,
                        kurzbeschreibung=kurzbeschreibung,
                        kategorie=kategorie,
                        risikostufe=risikostufe,
                        erklaerung=erklaerung,
                        empfehlung=finding_data.get("empfehlung"),
                        extraction_pass="case_step7",
                        pruef_status=PruefStatus.OFFEN.value,
                        is_suppressed=is_suppressed,
                        suppression_reason=suppression_reason,
                        policy_rule_id=policy_rule_id,
                        # Paragraph-level evidence
                        scope_type=scope_type if scope_type in ("paragraph", "clause_block") else None,
                        scope_text=scope_text or None,
                        trigger_spans=trigger_spans or None,
                        evidence_heading_path=section.heading_path,
                        evidence_page_from=section.page_from,
                        evidence_page_to=section.page_to,
                    )
                    db.add(fundstelle)
                    metrics["total_findings"] += 1
                    section_findings += 1

                extraction_summary.append({
                    "section_id": str(section.id),
                    "heading": (section.heading_path or "")[:80],
                    "findings": section_findings,
                })

            await db.flush()

        offset += SECTION_BATCH_SIZE

    await db.commit()

    # Debug snapshot — summary only, no full text
    await _save_debug_snapshot(db, case_id, "extraction_result", {
        "metrics": metrics,
        "per_section": extraction_summary[:100],  # cap to avoid huge snapshots
    })

    logger.info(
        f"Extraktion abgeschlossen: {metrics['total_sections']} Sections — "
        f"{metrics['total_findings']} Findings, {metrics['total_positive_controls']} Positive Controls, "
        f"{metrics['errors']} Errors"
    )
    return metrics


async def _extract_single_section(section: DocumentSection, config: LLMConfig) -> list[dict]:
    """Extract findings from a single section via LLM with robust parsing."""
    text = section.raw_text[:6000]
    heading = section.heading_path or ""
    user_prompt = (
        f"Dokumentabschnitt (Seite {section.page_from or '?'}, "
        f"Überschrift: {heading}):\n\n{text}"
    )

    try:
        raw = await llm_completion(
            config, EXTRACTION_SYSTEM_PROMPT, user_prompt,
            temperature=0.2, max_tokens=4096,
        )
        return await _robust_parse_json_array(raw, config, context="extraction")
    except Exception as e:
        logger.warning(f"Extraction LLM-Fehler: {e}")
        return []


# ---------------------------------------------------------------------------
# Step 8 — Topic Clustering (Task 7: deterministic)
# ---------------------------------------------------------------------------

CLUSTERING_SYSTEM_PROMPT = """Du bist ein Vertragsanalyse-Experte. Gruppiere die folgenden Einzelfundstellen zu übergeordneten RISIKOTHEMEN.

Antworte AUSSCHLIESSLICH mit einem JSON-Array (kein Markdown, keine Erklärung):
[
  {
    "topic_title": "Titel des Risikothemas (max 100 Zeichen)",
    "category": "KATEGORIE",
    "severity": "Hoch" | "Mittel" | "Niedrig",
    "summary": "Zusammenfassung des Risikothemas (2-3 Sätze)",
    "evidence_indices": [0, 3, 7]
  }
]

Regeln:
- Zielgröße: 5-15 Themen
- Jedes Thema fasst ÄHNLICHE Risiken zusammen (gleiche Kategorie oder verwandtes Thema)
- Jedes Finding muss genau EINEM Thema zugeordnet werden
- "evidence_indices" referenziert die Indizes der Findings (0-basiert)
- Severity richtet sich nach dem höchsten Risiko der zugeordneten Findings
- Themen mit nur 1 Finding sind erlaubt, wenn das Finding eigenständig wichtig ist

Kategorien: SECURITY_GOVERNANCE, CERTIFICATION_ASSURANCE, AUDIT_RIGHTS, SUBPROCESSING, AVAILABILITY_SLA, INCIDENT_MANAGEMENT, CHANGE_MANAGEMENT, EXIT_PORTABILITY, BACKUP_RECOVERY, BCM_ITSCM, LIABILITY, PERFORMANCE_REPORTING, DATA_PROTECTION, OTHER"""


async def cluster_findings(
    case_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
) -> dict:
    """Step 8: Cluster findings into themes.

    Task 7: Deterministic — sorts findings by (kategorie, kurzbeschreibung) before clustering.
    Task 4: Cluster quality diagnostics included.
    """
    # Load all non-suppressed findings for this case
    result = await db.execute(
        select(Fundstelle)
        .where(Fundstelle.analysis_case_id == case_id)
        .where(Fundstelle.is_suppressed == False)  # noqa: E712
        .where(Fundstelle.is_out_of_scope == False)  # noqa: E712
        .order_by(Fundstelle.kategorie, Fundstelle.kurzbeschreibung, Fundstelle.erstellt_am)
    )
    findings = list(result.scalars().all())

    if not findings:
        logger.info("Keine Findings zum Clustern vorhanden")
        return {"total_findings": 0, "total_themes": 0}

    # Debug snapshot: cluster input
    await _save_debug_snapshot(db, case_id, "cluster_input", {
        "finding_count": len(findings),
        "findings": [
            {"id": str(f.id), "kategorie": f.kategorie, "kurzbeschreibung": f.kurzbeschreibung[:100]}
            for f in findings[:200]
        ],
    })

    # Build compact finding representation for LLM
    finding_lines = []
    for idx, f in enumerate(findings):
        finding_lines.append(
            f"[{idx}] {f.kurzbeschreibung} | Kat: {f.kategorie} | Risiko: {f.risikostufe} | "
            f"Text: {f.textstelle[:150]}"
        )
    findings_text = "\n".join(finding_lines)

    user_prompt = f"Es gibt {len(findings)} Fundstellen:\n\n{findings_text}"

    try:
        raw = await llm_completion(
            config, CLUSTERING_SYSTEM_PROMPT, user_prompt,
            temperature=0.0,  # Task 7: temperature=0 for deterministic output
            max_tokens=4096,
        )
        clusters = await _robust_parse_json_array(raw, config, context="clustering")
    except Exception as e:
        logger.warning(f"Clustering LLM-Fehler: {e}")
        clusters = []

    if not clusters:
        logger.warning("Clustering lieferte keine Ergebnisse, erstelle Kategorie-basiertes Fallback")
        clusters = _fallback_clustering(findings)

    # Task 4: Cluster quality diagnostics
    cluster_diagnostics = []

    # Persist themes
    themes_created = 0
    for rank, cluster in enumerate(clusters):
        evidence_indices = cluster.get("evidence_indices", [])
        cluster_findings = [findings[i] for i in evidence_indices if 0 <= i < len(findings)]

        if not cluster_findings:
            continue

        # Task 4: Category variance check
        categories = {f.kategorie for f in cluster_findings}
        is_mixed = len(categories) > 1
        is_singleton = len(cluster_findings) == 1
        doc_ids = {f.case_document_id for f in cluster_findings if f.case_document_id}

        diagnostic = {
            "title": cluster.get("topic_title", "")[:100],
            "cluster_size": len(cluster_findings),
            "documents_involved": len(doc_ids),
            "categories": list(categories),
            "is_mixed_category": is_mixed,
            "is_singleton": is_singleton,
        }
        if is_mixed:
            diagnostic["cluster_warning"] = "MIXED_CATEGORIES"
        if is_singleton:
            diagnostic["cluster_warning"] = diagnostic.get("cluster_warning", "") + " SINGLETON"
        cluster_diagnostics.append(diagnostic)

        theme = Theme(
            analysis_case_id=case_id,
            category=cluster.get("category", "OTHER"),
            canonical_title=cluster.get("topic_title", f"Thema {rank + 1}")[:500],
            canonical_summary=cluster.get("summary"),
            severity=cluster.get("severity", "Mittel"),
            source_finding_count=len(cluster_findings),
            source_document_count=len(doc_ids),
        )
        db.add(theme)
        await db.flush()

        for ev_rank, f in enumerate(cluster_findings):
            te = ThemeEvidence(
                theme_id=theme.id,
                finding_id=f.id,
                evidence_role=EvidenceRole.SUPPORTING.value,
                rank=ev_rank,
            )
            db.add(te)

        themes_created += 1

    await db.commit()

    # Debug snapshot: cluster output with diagnostics
    await _save_debug_snapshot(db, case_id, "cluster_output", {
        "total_findings": len(findings),
        "total_themes": themes_created,
        "diagnostics": cluster_diagnostics,
    })

    logger.info(f"Clustering abgeschlossen: {len(findings)} Findings → {themes_created} Themen")
    return {
        "total_findings": len(findings),
        "total_themes": themes_created,
        "diagnostics": cluster_diagnostics,
    }


def _fallback_clustering(findings: list[Fundstelle]) -> list[dict]:
    """Fallback: group findings by category."""
    by_cat: dict[str, list[int]] = {}
    for idx, f in enumerate(findings):
        cat = f.kategorie or "OTHER"
        by_cat.setdefault(cat, []).append(idx)

    clusters = []
    for cat, indices in sorted(by_cat.items()):  # sorted for determinism
        clusters.append({
            "topic_title": f"Risiken: {cat}",
            "category": cat,
            "severity": "Mittel",
            "summary": f"Gesammelte Risikofundstellen der Kategorie {cat}",
            "evidence_indices": indices,
        })
    return clusters


# ---------------------------------------------------------------------------
# Step 9 — Consolidation
# ---------------------------------------------------------------------------

CONSOLIDATION_SYSTEM_PROMPT = """Du bist ein Vertragsanalyse-Experte. Konsolidiere die folgenden Risikothemen, indem du:
1. Stark überlappende Themen zusammenführst
2. Das wichtigste Evidence als PRIMARY markierst (max 3 pro Thema)
3. Konflikte zwischen Dokumenten erkennst

Antworte AUSSCHLIESSLICH mit einem JSON-Array (kein Markdown):
[
  {
    "theme_index": 0,
    "merged_with": [],
    "canonical_title": "Konsolidierter Titel",
    "canonical_summary": "Konsolidierte Zusammenfassung (2-3 Sätze)",
    "severity": "Hoch" | "Mittel" | "Niedrig",
    "primary_evidence_ids": ["uuid1", "uuid2"],
    "conflict_detected": false,
    "conflict_summary": null
  }
]

Regeln:
- Wenn 2+ Themen dasselbe Risiko beschreiben, führe sie zusammen (merged_with enthält die Indizes der absorbierten Themen)
- Jedes Thema erscheint genau einmal: entweder als eigenständig oder als merged_with bei einem anderen
- primary_evidence_ids: max 3 wichtigste Fundstellen-IDs
- Zielgröße nach Konsolidierung: 4-12 Themen"""


async def consolidate_themes(
    case_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
) -> dict:
    """Step 9: Consolidate themes — merge overlapping, mark primary evidence."""
    result = await db.execute(
        select(Theme)
        .where(Theme.analysis_case_id == case_id)
        .order_by(Theme.category, Theme.canonical_title)  # deterministic order
    )
    themes = list(result.scalars().all())

    if len(themes) <= 1:
        logger.info("Zu wenige Themen für Konsolidierung")
        return {"themes_before": len(themes), "themes_after": len(themes), "merged": 0}

    # Load evidence for each theme
    theme_data = []
    for idx, theme in enumerate(themes):
        ev_result = await db.execute(
            select(ThemeEvidence)
            .where(ThemeEvidence.theme_id == theme.id)
            .order_by(ThemeEvidence.rank)
        )
        evidence = list(ev_result.scalars().all())

        evidence_details = []
        for ev in evidence[:10]:  # Cap evidence loaded per theme
            f = await db.get(Fundstelle, ev.finding_id)
            if f:
                evidence_details.append({
                    "id": str(f.id),
                    "kurzbeschreibung": f.kurzbeschreibung,
                    "kategorie": f.kategorie,
                    "risikostufe": f.risikostufe,
                    "textstelle": f.textstelle[:200],
                })

        theme_data.append({
            "index": idx,
            "title": theme.canonical_title,
            "category": theme.category,
            "severity": theme.severity,
            "summary": theme.canonical_summary or "",
            "finding_count": theme.source_finding_count,
            "evidence": evidence_details,
        })

    # Build LLM prompt
    user_prompt = f"Es gibt {len(themes)} Risikothemen:\n\n"
    for td in theme_data:
        user_prompt += (
            f"[{td['index']}] {td['title']} | Kat: {td['category']} | "
            f"Severity: {td['severity']} | {td['finding_count']} Findings\n"
            f"  Summary: {td['summary'][:200]}\n"
            f"  Evidence: {json.dumps([e['kurzbeschreibung'] for e in td['evidence'][:5]], ensure_ascii=False)}\n\n"
        )

    try:
        raw = await llm_completion(
            config, CONSOLIDATION_SYSTEM_PROMPT, user_prompt,
            temperature=0.0,
            max_tokens=4096,
        )
        consolidation_results = await _robust_parse_json_array(raw, config, context="consolidation")
    except Exception as e:
        logger.warning(f"Konsolidierung LLM-Fehler: {e}")
        consolidation_results = []

    if not consolidation_results:
        logger.warning("Konsolidierung lieferte keine Ergebnisse — Themen bleiben unverändert")
        return {"themes_before": len(themes), "themes_after": len(themes), "merged": 0}

    # Apply consolidation
    merged_indices = set()
    for cr in consolidation_results:
        theme_idx = cr.get("theme_index", -1)
        if theme_idx < 0 or theme_idx >= len(themes):
            continue

        theme = themes[theme_idx]
        theme.canonical_title = cr.get("canonical_title", theme.canonical_title)[:500]
        theme.canonical_summary = cr.get("canonical_summary", theme.canonical_summary)
        theme.severity = cr.get("severity", theme.severity)
        theme.conflict_detected = cr.get("conflict_detected", False)
        theme.conflict_summary = cr.get("conflict_summary")

        # Mark primary evidence
        primary_ids = cr.get("primary_evidence_ids", [])
        if primary_ids:
            ev_result = await db.execute(
                select(ThemeEvidence).where(ThemeEvidence.theme_id == theme.id)
            )
            for ev in ev_result.scalars().all():
                if str(ev.finding_id) in primary_ids:
                    ev.evidence_role = EvidenceRole.PRIMARY.value

        # Handle merges
        for merged_idx in cr.get("merged_with", []):
            if merged_idx < len(themes) and merged_idx != theme_idx and merged_idx not in merged_indices:
                merged_indices.add(merged_idx)
                merged_theme = themes[merged_idx]
                merged_ev = await db.execute(
                    select(ThemeEvidence).where(ThemeEvidence.theme_id == merged_theme.id)
                )
                for ev in merged_ev.scalars().all():
                    ev.theme_id = theme.id
                    ev.evidence_role = EvidenceRole.SECONDARY.value

                theme.source_finding_count += merged_theme.source_finding_count
                await db.delete(merged_theme)

    await db.commit()

    remaining = len(themes) - len(merged_indices)

    # Debug snapshot
    await _save_debug_snapshot(db, case_id, "consolidation_output", {
        "themes_before": len(themes),
        "themes_after": remaining,
        "merged_count": len(merged_indices),
        "merged_indices": list(merged_indices),
    })

    logger.info(
        f"Konsolidierung abgeschlossen: {len(themes)} → {remaining} Themen "
        f"({len(merged_indices)} zusammengeführt)"
    )
    return {
        "themes_before": len(themes),
        "themes_after": remaining,
        "merged": len(merged_indices),
    }


# ---------------------------------------------------------------------------
# Step 10 — Final Editorial (Task 5: guardrails)
# ---------------------------------------------------------------------------

EDITORIAL_SYSTEM_PROMPT = """Du bist ein Senior-Vertragsberater. Wähle aus den folgenden Risikothemen die VERHANDLUNGSRELEVANTEN Kernthemen aus.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt (kein Markdown):
{
  "selected_themes": [
    {
      "theme_index": 0,
      "final_rank": 1,
      "editorial_title": "Verhandlungsrelevanter Titel",
      "editorial_summary": "Warum verhandlungsrelevant (2-3 Sätze)",
      "alternativformulierung": "Vorgeschlagene alternative Vertragsformulierung",
      "bieterfrage": "Klärungsfrage an den Anbieter",
      "verhandlungsargumente": ["Argument 1", "Argument 2", "Argument 3"],
      "primary_evidence_ids": ["uuid1"]
    }
  ],
  "rejected_themes": [
    {
      "theme_index": 2,
      "rejection_reason": "Standardklausel ohne Verhandlungspotenzial"
    }
  ]
}

WICHTIG: Maximal 15 Themen auswählen.
Jedes ausgewählte Thema MUSS enthalten: editorial_title, editorial_summary, alternativformulierung, bieterfrage, verhandlungsargumente.

Regeln:
- Wähle 3-8 Kernthemen für kurze Verträge (< 50 Findings), 5-12 für große
- Nur wirklich VERHANDLUNGSRELEVANTE Themen auswählen
- Sortiere nach Wichtigkeit (final_rank 1 = wichtigstes)
- Alle nicht-ausgewählten Themen in rejected_themes mit Begründung"""

EDITORIAL_REQUIRED_FIELDS = {"editorial_title", "editorial_summary", "alternativformulierung", "bieterfrage", "verhandlungsargumente"}


async def final_editorial(
    case_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
) -> dict:
    """Step 10: Final editorial — select core themes for negotiation.

    Task 5: Enforces max 15 themes, validates required fields, retries once on failure.
    """
    result = await db.execute(
        select(Theme)
        .where(Theme.analysis_case_id == case_id)
        .order_by(Theme.category, Theme.canonical_title)  # deterministic
    )
    themes = list(result.scalars().all())

    if not themes:
        logger.info("Keine Themen für Final Editorial vorhanden")
        return {"total_themes": 0, "selected": 0, "rejected": 0}

    # Count total findings
    finding_count_result = await db.execute(
        select(func.count(Fundstelle.id))
        .where(Fundstelle.analysis_case_id == case_id)
        .where(Fundstelle.is_suppressed == False)  # noqa: E712
    )
    total_findings = finding_count_result.scalar() or 0

    # Build theme descriptions
    theme_lines = []
    for idx, theme in enumerate(themes):
        ev_result = await db.execute(
            select(ThemeEvidence)
            .where(ThemeEvidence.theme_id == theme.id)
            .order_by(ThemeEvidence.rank)
            .limit(5)
        )
        evidence = list(ev_result.scalars().all())

        evidence_details = []
        for ev in evidence:
            f = await db.get(Fundstelle, ev.finding_id)
            if f:
                evidence_details.append(f"{f.kurzbeschreibung} ({f.risikostufe})")

        theme_lines.append(
            f"[{idx}] {theme.canonical_title} | Kat: {theme.category} | "
            f"Severity: {theme.severity} | {theme.source_finding_count} Findings\n"
            f"  Summary: {theme.canonical_summary or 'n/a'}\n"
            f"  Top-Evidence: {'; '.join(evidence_details[:3])}\n"
        )

    user_prompt = (
        f"Vertragsdossier mit {total_findings} Findings in {len(themes)} Themen.\n\n"
        + "\n".join(theme_lines)
    )

    # Attempt editorial with retry (Task 5)
    editorial = None
    for attempt in range(2):
        try:
            raw = await llm_completion(
                config, EDITORIAL_SYSTEM_PROMPT, user_prompt,
                temperature=0.3, max_tokens=8192,
            )
            editorial = await _robust_parse_json_object(raw, config, context="editorial")
        except Exception as e:
            logger.warning(f"Editorial LLM-Fehler (Versuch {attempt + 1}): {e}")
            continue

        if editorial and _validate_editorial(editorial):
            break
        else:
            logger.warning(f"Editorial-Validierung fehlgeschlagen (Versuch {attempt + 1}), retry")
            editorial = None

    if not editorial:
        logger.warning("Final Editorial lieferte kein valides Ergebnis — alle Themen bleiben")
        return {"total_themes": len(themes), "selected": len(themes), "rejected": 0}

    selected_count = 0
    rejected_count = 0

    # Apply selections (capped at MAX_EDITORIAL_THEMES)
    selected_themes = editorial.get("selected_themes", [])[:MAX_EDITORIAL_THEMES]

    for sel in selected_themes:
        idx = sel.get("theme_index", -1)
        if idx < 0 or idx >= len(themes):
            continue

        theme = themes[idx]
        theme.final_selected = True
        theme.final_rank = sel.get("final_rank", idx + 1)
        theme.final_selection_basis = FinalSelectionBasis.LLM.value
        theme.final_editorial_json = {
            "editorial_title": sel.get("editorial_title", theme.canonical_title),
            "editorial_summary": sel.get("editorial_summary", ""),
            "alternativformulierung": sel.get("alternativformulierung", ""),
            "bieterfrage": sel.get("bieterfrage", ""),
            "verhandlungsargumente": sel.get("verhandlungsargumente", []),
        }

        primary_ids = sel.get("primary_evidence_ids", [])
        if primary_ids:
            ev_result = await db.execute(
                select(ThemeEvidence).where(ThemeEvidence.theme_id == theme.id)
            )
            for ev in ev_result.scalars().all():
                if str(ev.finding_id) in primary_ids:
                    ev.evidence_role = EvidenceRole.PRIMARY.value

        selected_count += 1

    # Apply rejections
    for rej in editorial.get("rejected_themes", []):
        idx = rej.get("theme_index", -1)
        if idx < 0 or idx >= len(themes):
            continue

        theme = themes[idx]
        theme.final_selected = False
        theme.final_rejection_reason = rej.get("rejection_reason", "")
        rejected_count += 1

    # Task 5: If still more than 15 selected, run a second reduction pass
    if selected_count > MAX_EDITORIAL_THEMES:
        logger.warning(f"Editorial: {selected_count} Themen > {MAX_EDITORIAL_THEMES}. Zweiter Reduktionspass.")
        selected_count = await _run_editorial_reduction(case_id, db, config, themes)

    await db.commit()

    # Debug snapshot
    await _save_debug_snapshot(db, case_id, "editorial_output", {
        "total_themes": len(themes),
        "selected": selected_count,
        "rejected": rejected_count,
    })

    logger.info(
        f"Final Editorial abgeschlossen: {selected_count} ausgewählt, "
        f"{rejected_count} verworfen"
    )
    return {
        "total_themes": len(themes),
        "selected": selected_count,
        "rejected": rejected_count,
    }


def _validate_editorial(editorial: dict) -> bool:
    """Task 5: Validate that editorial result has required fields."""
    selected = editorial.get("selected_themes", [])
    if not selected:
        return False

    for sel in selected:
        missing = EDITORIAL_REQUIRED_FIELDS - set(sel.keys())
        if missing:
            logger.warning(f"Editorial Theme {sel.get('theme_index', '?')} fehlen Felder: {missing}")
            return False

    return True


async def _run_editorial_reduction(
    case_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
    themes: list[Theme],
) -> int:
    """Task 5: Second editorial pass to reduce below MAX_EDITORIAL_THEMES."""
    selected = [t for t in themes if t.final_selected]
    if len(selected) <= MAX_EDITORIAL_THEMES:
        return len(selected)

    # Sort by final_rank and keep top MAX_EDITORIAL_THEMES
    selected.sort(key=lambda t: t.final_rank or 999)
    for t in selected[MAX_EDITORIAL_THEMES:]:
        t.final_selected = False
        t.final_rejection_reason = "Überschreitung des Themenlimits — im zweiten Reduktionspass entfernt"

    return MAX_EDITORIAL_THEMES
