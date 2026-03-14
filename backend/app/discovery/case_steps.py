"""Steps 6-10 for the case-based multi-document pipeline.

Step 6 — Screening: LLM classification of sections (irrelevant/context/risk_candidate)
Step 7 — Extraction: LLM finding extraction per reviewable section
Step 8 — Topic Clustering: Group findings into themes by similarity
Step 9 — Consolidation: LLM-based theme merging
Step 10 — Final Editorial: LLM reduction to core negotiation-relevant themes
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.case_document import CaseDocument
from app.models.document_section import DocumentSection
from app.models.fundstelle import Fundstelle, PruefStatus
from app.models.positive_control import PositiveControl
from app.models.theme import Theme, ThemeEvidence
from app.models.enums import (
    SectionRouting, ControlType, ControlStatus,
    EvidenceRole, FinalSelectionBasis,
)
from app.discovery.llm_client import LLMConfig, llm_completion, estimate_tokens, get_throttle
from app.discovery.policy_engine import scan_finding

logger = logging.getLogger(__name__)


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

    Returns metrics dict with counts.
    """
    result = await db.execute(
        select(DocumentSection)
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case_id)
        .where(DocumentSection.routing == SectionRouting.REVIEWABLE.value)
        .where(DocumentSection.screening_status == None)  # noqa: E711
        .order_by(DocumentSection.section_index)
    )
    sections = list(result.scalars().all())

    if not sections:
        logger.info("Keine Sections zum Screenen gefunden")
        return {"total": 0, "risk_candidate": 0, "context": 0, "ignored": 0}

    metrics = {"total": len(sections), "risk_candidate": 0, "context": 0, "ignored": 0}

    # Process in batches of 5
    batch_size = 5
    for i in range(0, len(sections), batch_size):
        batch = sections[i:i + batch_size]
        tasks = [_screen_single_section(section, config) for section in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for section, res in zip(batch, results):
            if isinstance(res, Exception):
                logger.warning(f"Screening fehlgeschlagen für Section {section.id}: {res}")
                section.screening_status = "error"
                section.screening_result = {"error": str(res)}
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

    await db.commit()
    logger.info(
        f"Screening abgeschlossen: {metrics['total']} Sections — "
        f"{metrics['risk_candidate']} risk_candidate, {metrics['context']} context, "
        f"{metrics['ignored']} ignored"
    )
    return metrics


async def _screen_single_section(section: DocumentSection, config: LLMConfig) -> dict:
    """Screen a single section via LLM."""
    text = section.raw_text[:3000]  # Cap at 3000 chars for screening
    user_prompt = f"Abschnitt (Seite {section.page_from or '?'}, {section.char_count} Zeichen):\n\n{text}"

    raw = await llm_completion(
        config, SCREENING_SYSTEM_PROMPT, user_prompt,
        temperature=0.1, max_tokens=256,
    )

    # Parse JSON response
    try:
        # Strip markdown if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
    except (json.JSONDecodeError, IndexError):
        pass

    # Default to risk_candidate on parse failure
    logger.warning(f"Screening JSON-Parse fehlgeschlagen, default risk_candidate. Raw: {raw[:100]}")
    return {"relevance": "risk_candidate", "categories": ["OTHER"], "reasoning": "Parse-Fehler"}


# ---------------------------------------------------------------------------
# Step 7 — Extraction
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """Du bist ein Vertragsanalyse-Experte. Analysiere den folgenden Vertragsabschnitt und extrahiere ALLE risikorelevanten Fundstellen.

Antworte AUSSCHLIESSLICH mit einem JSON-Array (kein Markdown, keine Erklärung):
[
  {
    "textstelle": "Exakter Wortlaut aus dem Text (max 300 Zeichen)",
    "kurzbeschreibung": "Kurze Beschreibung des Risikos (max 150 Zeichen)",
    "kategorie": "KATEGORIE",
    "risikostufe": "Hoch" | "Mittel" | "Niedrig" | "Hinweis",
    "erklaerung": "Warum ist das ein Risiko? (2-3 Sätze)",
    "empfehlung": "Handlungsempfehlung (1-2 Sätze)",
    "ist_positiv": false
  }
]

Wenn der Abschnitt eine Zertifizierung, einen Standard oder eine positive Zusicherung enthält, setze "ist_positiv": true.

Kategorien: SECURITY_GOVERNANCE, CERTIFICATION_ASSURANCE, AUDIT_RIGHTS, SUBPROCESSING, AVAILABILITY_SLA, INCIDENT_MANAGEMENT, CHANGE_MANAGEMENT, EXIT_PORTABILITY, BACKUP_RECOVERY, BCM_ITSCM, LIABILITY, PERFORMANCE_REPORTING, DATA_PROTECTION, OTHER

Wenn KEINE Fundstellen vorhanden sind, antworte mit einem leeren Array: []"""


async def extract_findings(
    case_id: uuid.UUID,
    analyse_id: uuid.UUID,
    vertrag_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
    policy_rules: list | None = None,
) -> dict:
    """Step 7: Extract findings from all screened risk_candidate sections.

    Returns metrics dict.
    """
    result = await db.execute(
        select(DocumentSection)
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case_id)
        .where(DocumentSection.screening_status == "analyze")
        .where(DocumentSection.extraction_status == None)  # noqa: E711
        .order_by(DocumentSection.section_index)
    )
    sections = list(result.scalars().all())

    if not sections:
        logger.info("Keine Sections zur Extraktion vorhanden")
        return {"total_sections": 0, "total_findings": 0, "total_positive_controls": 0}

    metrics = {"total_sections": len(sections), "total_findings": 0, "total_positive_controls": 0}
    all_findings: list[Fundstelle] = []

    # Process in batches of 5
    batch_size = 5
    for i in range(0, len(sections), batch_size):
        batch = sections[i:i + batch_size]
        tasks = [_extract_single_section(section, config) for section in batch]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for section, res in zip(batch, results):
            if isinstance(res, Exception):
                logger.warning(f"Extraktion fehlgeschlagen für Section {section.id}: {res}")
                section.extraction_status = "error"
                continue

            section.extraction_status = "completed"

            for finding_data in res:
                ist_positiv = finding_data.get("ist_positiv", False)

                if ist_positiv:
                    # Create positive control instead of finding
                    pc = PositiveControl(
                        analysis_case_id=case_id,
                        case_document_id=section.case_document_id,
                        document_section_id=section.id,
                        control_type=ControlType.STANDARD_CONTROL.value,
                        control_value=finding_data.get("kurzbeschreibung", ""),
                        source_text=finding_data.get("textstelle", "")[:500],
                        status=ControlStatus.NEEDS_REVIEW.value,
                    )
                    db.add(pc)
                    metrics["total_positive_controls"] += 1
                    continue

                # Apply policy rules post-extraction if available
                is_suppressed = False
                suppression_reason = None
                policy_rule_id = None
                if policy_rules:
                    matches = scan_finding(
                        finding_data.get("kurzbeschreibung", ""),
                        finding_data.get("kategorie", "OTHER"),
                        policy_rules,
                    )
                    for m in matches:
                        if m.action == "SUPPRESS_RISK":
                            is_suppressed = True
                            suppression_reason = m.rule_name
                            policy_rule_id = uuid.UUID(m.rule_id) if m.rule_id else None
                            break

                fundstelle = Fundstelle(
                    analyse_id=analyse_id,
                    vertrag_id=vertrag_id,
                    analysis_case_id=case_id,
                    case_document_id=section.case_document_id,
                    document_section_id=section.id,
                    textstelle=finding_data.get("textstelle", "")[:500],
                    kurzbeschreibung=finding_data.get("kurzbeschreibung", "Unbekannt"),
                    kategorie=finding_data.get("kategorie", "OTHER"),
                    risikostufe=finding_data.get("risikostufe", "Hinweis"),
                    erklaerung=finding_data.get("erklaerung"),
                    empfehlung=finding_data.get("empfehlung"),
                    extraction_pass="case_step7",
                    pruef_status=PruefStatus.OFFEN.value,
                    is_suppressed=is_suppressed,
                    suppression_reason=suppression_reason,
                    policy_rule_id=policy_rule_id,
                )
                db.add(fundstelle)
                all_findings.append(fundstelle)
                metrics["total_findings"] += 1

        await db.flush()

    await db.commit()
    logger.info(
        f"Extraktion abgeschlossen: {metrics['total_sections']} Sections — "
        f"{metrics['total_findings']} Findings, {metrics['total_positive_controls']} Positive Controls"
    )
    return metrics


async def _extract_single_section(section: DocumentSection, config: LLMConfig) -> list[dict]:
    """Extract findings from a single section via LLM."""
    text = section.raw_text[:6000]  # Cap for extraction
    heading = section.heading_path or ""
    user_prompt = (
        f"Dokumentabschnitt (Seite {section.page_from or '?'}, "
        f"Überschrift: {heading}):\n\n{text}"
    )

    raw = await llm_completion(
        config, EXTRACTION_SYSTEM_PROMPT, user_prompt,
        temperature=0.2, max_tokens=4096,
    )

    # Parse JSON array response
    try:
        cleaned = raw.strip()
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
            parsed = json.loads(cleaned[start:end + 1])
            if isinstance(parsed, list):
                return parsed
    except (json.JSONDecodeError, IndexError):
        pass

    logger.warning(f"Extraktion JSON-Parse fehlgeschlagen. Raw: {raw[:200]}")
    return []


# ---------------------------------------------------------------------------
# Step 8 — Topic Clustering
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

    Returns metrics dict.
    """
    # Load all non-suppressed findings for this case
    result = await db.execute(
        select(Fundstelle)
        .where(Fundstelle.analysis_case_id == case_id)
        .where(Fundstelle.is_suppressed == False)  # noqa: E712
        .where(Fundstelle.is_out_of_scope == False)  # noqa: E712
        .order_by(Fundstelle.erstellt_am)
    )
    findings = list(result.scalars().all())

    if not findings:
        logger.info("Keine Findings zum Clustern vorhanden")
        return {"total_findings": 0, "total_themes": 0}

    # Build compact finding representation for LLM
    finding_lines = []
    for idx, f in enumerate(findings):
        finding_lines.append(
            f"[{idx}] {f.kurzbeschreibung} | Kat: {f.kategorie} | Risiko: {f.risikostufe} | "
            f"Text: {f.textstelle[:150]}"
        )
    findings_text = "\n".join(finding_lines)

    user_prompt = f"Es gibt {len(findings)} Fundstellen:\n\n{findings_text}"

    raw = await llm_completion(
        config, CLUSTERING_SYSTEM_PROMPT, user_prompt,
        temperature=0.2, max_tokens=4096,
    )

    # Parse clustering result
    clusters = _parse_json_array(raw)
    if not clusters:
        logger.warning("Clustering lieferte keine Ergebnisse, erstelle 1:1-Mapping")
        clusters = _fallback_clustering(findings)

    # Count unique documents
    doc_ids = set()
    for f in findings:
        if f.case_document_id:
            doc_ids.add(f.case_document_id)

    # Persist themes
    themes_created = 0
    for rank, cluster in enumerate(clusters):
        evidence_indices = cluster.get("evidence_indices", [])
        cluster_findings = [findings[i] for i in evidence_indices if i < len(findings)]

        if not cluster_findings:
            continue

        theme = Theme(
            analysis_case_id=case_id,
            category=cluster.get("category", "OTHER"),
            canonical_title=cluster.get("topic_title", f"Thema {rank + 1}")[:500],
            canonical_summary=cluster.get("summary"),
            severity=cluster.get("severity", "Mittel"),
            source_finding_count=len(cluster_findings),
            source_document_count=len({f.case_document_id for f in cluster_findings if f.case_document_id}),
        )
        db.add(theme)
        await db.flush()

        # Link evidence
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
    logger.info(f"Clustering abgeschlossen: {len(findings)} Findings → {themes_created} Themen")
    return {"total_findings": len(findings), "total_themes": themes_created}


def _fallback_clustering(findings: list[Fundstelle]) -> list[dict]:
    """Fallback: group findings by category."""
    by_cat: dict[str, list[int]] = {}
    for idx, f in enumerate(findings):
        cat = f.kategorie or "OTHER"
        by_cat.setdefault(cat, []).append(idx)

    clusters = []
    for cat, indices in by_cat.items():
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
    """Step 9: Consolidate themes — merge overlapping, mark primary evidence.

    Returns metrics dict.
    """
    result = await db.execute(
        select(Theme)
        .where(Theme.analysis_case_id == case_id)
        .order_by(Theme.created_at)
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

        # Load finding details for evidence
        evidence_details = []
        for ev in evidence:
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

    raw = await llm_completion(
        config, CONSOLIDATION_SYSTEM_PROMPT, user_prompt,
        temperature=0.2, max_tokens=4096,
    )

    consolidation_results = _parse_json_array(raw)
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
            if merged_idx < len(themes) and merged_idx != theme_idx:
                merged_indices.add(merged_idx)
                merged_theme = themes[merged_idx]
                # Move evidence from merged theme to this theme
                merged_ev = await db.execute(
                    select(ThemeEvidence).where(ThemeEvidence.theme_id == merged_theme.id)
                )
                for ev in merged_ev.scalars().all():
                    ev.theme_id = theme.id
                    ev.evidence_role = EvidenceRole.SECONDARY.value

                # Update finding count
                theme.source_finding_count += merged_theme.source_finding_count

                # Delete merged theme
                await db.delete(merged_theme)

    await db.commit()

    remaining = len(themes) - len(merged_indices)
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
# Step 10 — Final Editorial
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

Regeln:
- Wähle 3-8 Kernthemen für kurze Verträge (< 50 Findings), 5-12 für große
- Nur wirklich VERHANDLUNGSRELEVANTE Themen auswählen
- Jedes Thema braucht: editorial_summary, alternativformulierung, bieterfrage, verhandlungsargumente
- Sortiere nach Wichtigkeit (final_rank 1 = wichtigstes)
- Alle nicht-ausgewählten Themen in rejected_themes mit Begründung"""


async def final_editorial(
    case_id: uuid.UUID,
    db: AsyncSession,
    config: LLMConfig,
) -> dict:
    """Step 10: Final editorial — select core themes for negotiation.

    Returns metrics dict.
    """
    result = await db.execute(
        select(Theme)
        .where(Theme.analysis_case_id == case_id)
        .order_by(Theme.created_at)
    )
    themes = list(result.scalars().all())

    if not themes:
        logger.info("Keine Themen für Final Editorial vorhanden")
        return {"total_themes": 0, "selected": 0, "rejected": 0}

    # Count total findings for size-based thresholds
    finding_count_result = await db.execute(
        select(func.count(Fundstelle.id))
        .where(Fundstelle.analysis_case_id == case_id)
        .where(Fundstelle.is_suppressed == False)  # noqa: E712
    )
    total_findings = finding_count_result.scalar() or 0

    # Build theme descriptions for LLM
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

    raw = await llm_completion(
        config, EDITORIAL_SYSTEM_PROMPT, user_prompt,
        temperature=0.3, max_tokens=8192,
    )

    # Parse editorial result
    editorial = _parse_json_object(raw)
    if not editorial:
        logger.warning("Final Editorial lieferte kein Ergebnis — alle Themen bleiben")
        return {"total_themes": len(themes), "selected": len(themes), "rejected": 0}

    selected_count = 0
    rejected_count = 0

    # Apply selections
    for sel in editorial.get("selected_themes", []):
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

        # Update primary evidence
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

    await db.commit()
    logger.info(
        f"Final Editorial abgeschlossen: {selected_count} ausgewählt, "
        f"{rejected_count} verworfen"
    )
    return {
        "total_themes": len(themes),
        "selected": selected_count,
        "rejected": rejected_count,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_array(raw: str) -> list[dict]:
    """Parse a JSON array from LLM response, handling markdown wrapping."""
    cleaned = raw.strip()
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
    if start < 0 or end <= start:
        return []

    try:
        parsed = json.loads(cleaned[start:end + 1])
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _parse_json_object(raw: str) -> dict | None:
    """Parse a JSON object from LLM response, handling markdown wrapping."""
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
    if start < 0 or end <= start:
        return None

    try:
        parsed = json.loads(cleaned[start:end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
