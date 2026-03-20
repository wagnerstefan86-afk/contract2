"""Case Pipeline Orchestrator — multi-document analysis pipeline.

Manages the full case lifecycle:
1. Case Ingest — register documents
2. Document Parse — extract text
3. Document Classify — determine document type
4. Section Split — chunk into sections
5. Policy Scan — route sections via policy rules
6. Screening — LLM section classification
7. Extraction — LLM-based finding extraction per section
8. Case Clustering — group findings into themes
9. Case Consolidation — deduplicate and merge themes
10. Final Editorial — select core themes for reviewers

Each step creates/updates ProcessingJob records for resume capability.
Collects PipelineMetrics for observability (Task 1).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.models.analysis_case import AnalysisCase
from app.models.case_document import CaseDocument
from app.models.document_section import DocumentSection
from app.models.positive_control import PositiveControl
from app.models.processing_job import ProcessingJob
from app.models.fundstelle import Fundstelle
from app.models.theme import Theme
from app.models.vertrag import Vertrag, VertragStatus
from app.models.analyse import Analyse, AnalyseStatus
from app.models.pipeline_metrics import PipelineMetrics
from app.models.enums import (
    CaseStatus, DocumentStatus, ParseStatus, ClassificationStatus,
    JobType, JobStatus, SectionRouting, ControlType, ControlStatus,
)
from app.discovery.document_parser import parse_document, classify_document, compute_sha256, detect_language
from app.discovery.section_splitter import split_into_sections
from app.discovery.policy_engine import load_active_rules, scan_section
from app.discovery.llm_client import lade_llm_config, get_throttle

logger = logging.getLogger(__name__)


async def run_case_pipeline(case_id: uuid.UUID, db: AsyncSession) -> None:
    """Run the full case analysis pipeline.

    This is the main entry point for case-based analysis.
    Each step is wrapped in a ProcessingJob for observability and resume.
    Collects PipelineMetrics and pipeline_warnings throughout.
    """
    case = await db.get(AnalysisCase, case_id)
    if not case:
        logger.error(f"AnalysisCase {case_id} nicht gefunden")
        return

    pipeline_start = time.monotonic()
    pipeline_warnings: list[str] = []

    try:
        case.status = CaseStatus.PROCESSING.value
        case.started_at = datetime.utcnow()
        await db.commit()

        # Step 1: Parse all documents
        await _step_parse_documents(db, case)

        # Step 2: Classify documents
        await _step_classify_documents(db, case)

        # Step 3: Split into sections
        await _step_split_sections(db, case)

        # Step 4: Policy scan
        await _step_policy_scan(db, case)

        # Load LLM config for Steps 6-10
        llm_config = await lade_llm_config(db)
        policy_rules = await load_active_rules(db)

        # Create bridge Vertrag + Analyse for Fundstelle FK compatibility
        bridge_vertrag, bridge_analyse = await _ensure_bridge_records(db, case)

        # Initialize step metrics
        screen_metrics = {}
        extract_metrics = {}
        cluster_metrics = {}
        consolidate_metrics = {}
        editorial_metrics = {}

        # Step 6: Screening
        job6 = await _create_job(db, case.id, JobType.SECTION_SCREEN)
        try:
            from app.discovery.case_steps import screen_sections
            screen_metrics = await screen_sections(case.id, db, llm_config, policy_rules)
            job6.payload_json = screen_metrics
            await _complete_job(db, job6)
            # Collect screening warnings (Task 3)
            if screen_metrics.get("warnings"):
                pipeline_warnings.extend(screen_metrics["warnings"])
        except Exception as e:
            await _complete_job(db, job6, error=str(e))
            logger.error(f"Screening fehlgeschlagen: {e}")
            pipeline_warnings.append(f"SCREENING_ERROR: {e}")

        # Step 7: Extraction
        job7 = await _create_job(db, case.id, JobType.SECTION_EXTRACT)
        try:
            from app.discovery.case_steps import extract_findings
            extract_metrics = await extract_findings(
                case.id, bridge_analyse.id, bridge_vertrag.id,
                db, llm_config, policy_rules,
            )
            job7.payload_json = extract_metrics
            await _complete_job(db, job7)
        except Exception as e:
            await _complete_job(db, job7, error=str(e))
            logger.error(f"Extraktion fehlgeschlagen: {e}")
            pipeline_warnings.append(f"EXTRACTION_ERROR: {e}")

        # Step 8: Topic Clustering
        job8 = await _create_job(db, case.id, JobType.CASE_CLUSTER)
        try:
            from app.discovery.case_steps import cluster_findings
            cluster_metrics = await cluster_findings(case.id, db, llm_config)
            job8.payload_json = cluster_metrics
            await _complete_job(db, job8)
        except Exception as e:
            await _complete_job(db, job8, error=str(e))
            logger.error(f"Clustering fehlgeschlagen: {e}")
            pipeline_warnings.append(f"CLUSTERING_ERROR: {e}")

        # Step 9: Consolidation
        job9 = await _create_job(db, case.id, JobType.CASE_CONSOLIDATE)
        try:
            from app.discovery.case_steps import consolidate_themes
            consolidate_metrics = await consolidate_themes(case.id, db, llm_config)
            job9.payload_json = consolidate_metrics
            await _complete_job(db, job9)
        except Exception as e:
            await _complete_job(db, job9, error=str(e))
            logger.error(f"Konsolidierung fehlgeschlagen: {e}")
            pipeline_warnings.append(f"CONSOLIDATION_ERROR: {e}")

        # Step 10: Final Editorial
        job10 = await _create_job(db, case.id, JobType.CASE_EDITORIAL)
        try:
            from app.discovery.case_steps import final_editorial
            editorial_metrics = await final_editorial(case.id, db, llm_config)
            job10.payload_json = editorial_metrics
            await _complete_job(db, job10)
        except Exception as e:
            await _complete_job(db, job10, error=str(e))
            logger.error(f"Final Editorial fehlgeschlagen: {e}")
            pipeline_warnings.append(f"EDITORIAL_ERROR: {e}")

        # Compute processing time
        processing_time = time.monotonic() - pipeline_start

        # Task 1: Save PipelineMetrics
        throttle = get_throttle(llm_config)
        metrics = PipelineMetrics(
            case_id=case.id,
            sections_total=screen_metrics.get("total", 0),
            sections_screened=screen_metrics.get("total", 0),
            sections_analyzed=screen_metrics.get("risk_candidate", 0),
            sections_ignored=screen_metrics.get("ignored", 0),
            sections_context=screen_metrics.get("context", 0),
            findings_created=extract_metrics.get("total_findings", 0),
            positive_controls_found=extract_metrics.get("total_positive_controls", 0),
            clusters_created=cluster_metrics.get("total_themes", 0),
            themes_after_consolidation=consolidate_metrics.get("themes_after", cluster_metrics.get("total_themes", 0)),
            themes_final=editorial_metrics.get("selected", 0),
            processing_time_seconds=round(processing_time, 2),
            llm_calls_total=throttle.stats.get("total_requests", 0),
        )
        db.add(metrics)

        # Update case counters
        await _update_case_counters(db, case)

        # Store pipeline warnings and summary on case
        case.pipeline_warnings = pipeline_warnings if pipeline_warnings else None
        case.processing_summary = {
            "processing_time_seconds": round(processing_time, 2),
            "sections_total": screen_metrics.get("total", 0),
            "sections_analyzed": screen_metrics.get("risk_candidate", 0),
            "findings_created": extract_metrics.get("total_findings", 0),
            "clusters_created": cluster_metrics.get("total_themes", 0),
            "themes_after_consolidation": consolidate_metrics.get("themes_after", 0),
            "themes_final": editorial_metrics.get("selected", 0),
            "llm_calls_total": throttle.stats.get("total_requests", 0),
        }

        # Determine final status: partial if LLM steps had errors but findings exist
        has_step_errors = any(w.startswith(("SCREENING_ERROR:", "EXTRACTION_ERROR:", "CLUSTERING_ERROR:", "CONSOLIDATION_ERROR:", "EDITORIAL_ERROR:")) for w in pipeline_warnings)
        has_findings = extract_metrics.get("total_findings", 0) > 0
        if has_step_errors and has_findings:
            case.status = CaseStatus.PARTIAL.value
            case.failure_reason = (
                f"{sum(1 for w in pipeline_warnings if '_ERROR:' in w)} Schritt(e) fehlgeschlagen. "
                f"Ergebnisse basieren auf den erfolgreichen Schritten."
            )
        elif has_step_errors and not has_findings:
            case.status = CaseStatus.FAILED.value
            case.failure_reason = "Alle Analyseschritte fehlgeschlagen — keine Ergebnisse."
        else:
            case.status = CaseStatus.COMPLETED.value
        case.finished_at = datetime.utcnow()
        await db.commit()

        logger.info(
            f"Case pipeline abgeschlossen: {case_id} "
            f"({round(processing_time, 1)}s, {len(pipeline_warnings)} warnings)"
        )

    except Exception as e:
        logger.exception(f"Case pipeline fehlgeschlagen: {e}")
        case.status = CaseStatus.FAILED.value
        case.failure_reason = _case_user_facing_error(e)
        case.finished_at = datetime.utcnow()
        pipeline_warnings.append(f"PIPELINE_FATAL: {type(e).__name__}: {e}")
        case.pipeline_warnings = pipeline_warnings
        await db.commit()


def _case_user_facing_error(e: Exception) -> str:
    """Convert an exception to a user-friendly message for case pipeline."""
    msg = str(e).lower()
    if "429" in msg or "rate" in msg:
        return "Die KI-Schnittstelle ist vorübergehend überlastet. Bitte versuchen Sie es in einigen Minuten erneut."
    if "401" in msg or "auth" in msg or "api_key" in msg:
        return "Der KI-API-Schlüssel ist ungültig oder fehlt. Bitte prüfen Sie die Einstellungen."
    if "timeout" in msg:
        return "Die KI-Anfrage hat zu lange gedauert. Bitte erneut versuchen."
    if any(code in msg for code in ("500", "502", "503")):
        return "Der KI-Dienst ist vorübergehend nicht erreichbar. Bitte später erneut versuchen."
    return "Bei der Analyse ist ein unerwarteter Fehler aufgetreten. Bitte versuchen Sie es erneut."


async def _create_job(
    db: AsyncSession,
    case_id: uuid.UUID,
    job_type: JobType,
    payload: dict | None = None,
) -> ProcessingJob:
    """Create a processing job record."""
    job = ProcessingJob(
        analysis_case_id=case_id,
        job_type=job_type.value,
        status=JobStatus.RUNNING.value,
        started_at=datetime.utcnow(),
        payload_json=payload,
    )
    db.add(job)
    await db.flush()
    return job


async def _complete_job(db: AsyncSession, job: ProcessingJob, error: str | None = None):
    """Mark a job as completed or failed."""
    if error:
        job.status = JobStatus.FAILED_RETRYABLE.value
        job.error_message = error
    else:
        job.status = JobStatus.COMPLETED.value
    job.finished_at = datetime.utcnow()
    await db.flush()


# ---------------------------------------------------------------------------
# Pipeline Steps
# ---------------------------------------------------------------------------

async def _step_parse_documents(db: AsyncSession, case: AnalysisCase) -> None:
    """Parse all documents in the case — extract text, compute hashes."""
    result = await db.execute(
        select(CaseDocument)
        .where(CaseDocument.analysis_case_id == case.id)
        .where(CaseDocument.parse_status == ParseStatus.PENDING.value)
    )
    docs = list(result.scalars().all())

    for doc in docs:
        job = await _create_job(db, case.id, JobType.DOCUMENT_PARSE, {"document_id": str(doc.id)})

        try:
            doc.parse_status = ParseStatus.RUNNING.value
            doc.status = DocumentStatus.PARSING.value
            await db.flush()

            if not doc.source_storage_path:
                raise ValueError(f"Kein Dateipfad für Dokument {doc.filename}")

            # Compute hash
            doc.sha256 = compute_sha256(doc.source_storage_path)

            # Extract text
            extraction = parse_document(doc.source_storage_path)
            doc.char_count = len(extraction.text)
            doc.page_count = len(extraction.seiten_map) if extraction.seiten_map else None
            doc.language = detect_language(extraction.text)

            doc.parse_status = ParseStatus.COMPLETED.value
            doc.status = DocumentStatus.PARSED.value

            # Store text temporarily in job payload for section split step
            job.payload_json = {
                "document_id": str(doc.id),
                "char_count": doc.char_count,
                "page_count": doc.page_count,
                "seiten_map": extraction.seiten_map,
                "text": extraction.text,
            }

            await _complete_job(db, job)
            logger.info(f"Dokument geparst: {doc.filename} ({doc.char_count} Zeichen, {doc.page_count} Seiten)")

        except Exception as e:
            doc.parse_status = ParseStatus.FAILED.value
            doc.status = DocumentStatus.FAILED.value
            doc.error_message = str(e)
            await _complete_job(db, job, error=str(e))
            logger.error(f"Dokument-Parse fehlgeschlagen: {doc.filename}: {e}")

    await db.commit()


async def _step_classify_documents(db: AsyncSession, case: AnalysisCase) -> None:
    """Classify document types for all parsed documents."""
    result = await db.execute(
        select(CaseDocument)
        .where(CaseDocument.analysis_case_id == case.id)
        .where(CaseDocument.parse_status == ParseStatus.COMPLETED.value)
        .where(CaseDocument.classification_status == ClassificationStatus.PENDING.value)
    )
    docs = list(result.scalars().all())

    for doc in docs:
        job = await _create_job(db, case.id, JobType.DOCUMENT_CLASSIFY, {"document_id": str(doc.id)})

        try:
            doc.classification_status = ClassificationStatus.RUNNING.value
            await db.flush()

            # Get text preview from parse job
            parse_jobs = await db.execute(
                select(ProcessingJob)
                .where(ProcessingJob.analysis_case_id == case.id)
                .where(ProcessingJob.job_type == JobType.DOCUMENT_PARSE.value)
                .where(ProcessingJob.status == JobStatus.COMPLETED.value)
            )
            text_preview = ""
            for pj in parse_jobs.scalars().all():
                if pj.payload_json and pj.payload_json.get("document_id") == str(doc.id):
                    text_preview = pj.payload_json.get("text", "")[:3000]
                    break

            doc_type, role_rank = classify_document(doc.filename, text_preview)
            doc.document_type = doc_type.value
            doc.document_role_rank = role_rank
            doc.classification_status = ClassificationStatus.COMPLETED.value
            doc.status = DocumentStatus.CLASSIFIED.value

            await _complete_job(db, job)
            logger.info(f"Dokument klassifiziert: {doc.filename} → {doc_type.value} (rank={role_rank})")

        except Exception as e:
            doc.classification_status = ClassificationStatus.FAILED.value
            await _complete_job(db, job, error=str(e))
            logger.error(f"Dokument-Klassifikation fehlgeschlagen: {doc.filename}: {e}")

    await db.commit()


async def _step_split_sections(db: AsyncSession, case: AnalysisCase) -> None:
    """Split all classified documents into sections/chunks."""
    result = await db.execute(
        select(CaseDocument)
        .where(CaseDocument.analysis_case_id == case.id)
        .where(CaseDocument.classification_status == ClassificationStatus.COMPLETED.value)
    )
    docs = list(result.scalars().all())

    for doc in docs:
        # Check if sections already exist (idempotent)
        existing = await db.execute(
            select(DocumentSection.id)
            .where(DocumentSection.case_document_id == doc.id)
            .limit(1)
        )
        if existing.first():
            logger.debug(f"Sections für {doc.filename} bereits vorhanden, überspringe")
            continue

        job = await _create_job(db, case.id, JobType.DOCUMENT_PARSE, {"document_id": str(doc.id), "step": "section_split"})

        try:
            # Retrieve text from parse job
            parse_jobs = await db.execute(
                select(ProcessingJob)
                .where(ProcessingJob.analysis_case_id == case.id)
                .where(ProcessingJob.job_type == JobType.DOCUMENT_PARSE.value)
                .where(ProcessingJob.status == JobStatus.COMPLETED.value)
            )
            text = ""
            seiten_map = None
            for pj in parse_jobs.scalars().all():
                if pj.payload_json and pj.payload_json.get("document_id") == str(doc.id):
                    text = pj.payload_json.get("text", "")
                    seiten_map = pj.payload_json.get("seiten_map")
                    break

            if not text:
                raise ValueError(f"Kein Text für Dokument {doc.filename} gefunden")

            sections = split_into_sections(text, seiten_map)

            for section in sections:
                db_section = DocumentSection(
                    case_document_id=doc.id,
                    section_index=section.index,
                    page_from=section.page_from,
                    page_to=section.page_to,
                    heading_path=section.heading_path,
                    section_type=section.section_type,
                    char_count=section.char_count,
                    token_estimate=section.token_estimate,
                    raw_text=section.raw_text,
                    normalized_text=section.normalized_text,
                    hash=section.hash,
                )
                db.add(db_section)

            await db.flush()
            doc.status = DocumentStatus.READY.value
            await _complete_job(db, job)
            logger.info(f"Sections erstellt: {doc.filename} → {len(sections)} Sections")

        except Exception as e:
            await _complete_job(db, job, error=str(e))
            logger.error(f"Section-Split fehlgeschlagen: {doc.filename}: {e}")

    await db.commit()


async def _step_policy_scan(db: AsyncSession, case: AnalysisCase) -> None:
    """Run policy rules against all sections to determine routing."""
    rules = await load_active_rules(db)
    if not rules:
        logger.info("Keine aktiven Policy-Regeln — alle Sections als REVIEWABLE markiert")
        return

    # Load all sections for this case
    result = await db.execute(
        select(DocumentSection)
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case.id)
        .where(DocumentSection.routing == None)
    )
    sections = list(result.scalars().all())

    job = await _create_job(db, case.id, JobType.SECTION_POLICY_SCAN, {
        "section_count": len(sections),
        "rule_count": len(rules),
    })

    positive_control_count = 0
    out_of_scope_count = 0
    reviewable_count = 0

    try:
        for section in sections:
            scan_result = scan_section(section.raw_text, rules)
            section.routing = scan_result.routing.value
            section.routing_reason = scan_result.routing_reason

            # Create positive control records
            for pc_match in scan_result.positive_controls:
                pc = PositiveControl(
                    analysis_case_id=case.id,
                    case_document_id=section.case_document_id,
                    document_section_id=section.id,
                    control_type=ControlType.CERTIFICATION.value,
                    control_value=pc_match.matched_text,
                    source_text=section.raw_text[:500],
                    policy_rule_id=uuid.UUID(pc_match.rule_id) if pc_match.rule_id else None,
                    status=ControlStatus.ACCEPTED.value,
                )
                db.add(pc)
                positive_control_count += 1

            if scan_result.routing == SectionRouting.OUT_OF_SCOPE:
                out_of_scope_count += 1
            elif scan_result.routing == SectionRouting.REVIEWABLE:
                reviewable_count += 1

        await db.flush()
        await _complete_job(db, job)
        logger.info(
            f"Policy Scan abgeschlossen: {len(sections)} Sections — "
            f"{reviewable_count} reviewable, {out_of_scope_count} out-of-scope, "
            f"{positive_control_count} positive controls"
        )

    except Exception as e:
        await _complete_job(db, job, error=str(e))
        logger.error(f"Policy Scan fehlgeschlagen: {e}")

    await db.commit()


async def _ensure_bridge_records(db: AsyncSession, case: AnalysisCase):
    """Create bridge Vertrag + Analyse for FK compatibility with Fundstelle.

    The case pipeline uses AnalysisCase but Fundstelle requires analyse_id/vertrag_id.
    We create synthetic records to bridge the two models.
    """
    # Check if bridge vertrag already exists (idempotent)
    result = await db.execute(
        select(Vertrag).where(Vertrag.dateiname == f"__case__{case.id}")
    )
    vertrag = result.scalar_one_or_none()
    if not vertrag:
        vertrag = Vertrag(
            dateiname=f"__case__{case.id}",
            dateipfad="",
            status=VertragStatus.IN_ANALYSE.value,
        )
        db.add(vertrag)
        await db.flush()

    result = await db.execute(
        select(Analyse).where(Analyse.vertrag_id == vertrag.id)
    )
    analyse = result.scalar_one_or_none()
    if not analyse:
        analyse = Analyse(
            vertrag_id=vertrag.id,
            status=AnalyseStatus.GESTARTET.value,
        )
        db.add(analyse)
        await db.flush()

    return vertrag, analyse


async def _update_case_counters(db: AsyncSession, case: AnalysisCase) -> None:
    """Update aggregate counters on the case."""
    # Document count
    doc_result = await db.execute(
        select(CaseDocument).where(CaseDocument.analysis_case_id == case.id)
    )
    docs = list(doc_result.scalars().all())
    case.total_documents = len(docs)
    case.total_pages = sum(d.page_count or 0 for d in docs)
    case.total_characters = sum(d.char_count or 0 for d in docs)

    # Section count
    section_result = await db.execute(
        select(func.count(DocumentSection.id))
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case.id)
    )
    case.total_chunks = section_result.scalar() or 0

    # Finding count
    finding_count = await db.execute(
        select(func.count(Fundstelle.id))
        .where(Fundstelle.analysis_case_id == case.id)
    )
    case.total_findings = finding_count.scalar() or 0

    # Theme counts
    theme_count = await db.execute(
        select(func.count(Theme.id))
        .where(Theme.analysis_case_id == case.id)
    )
    case.total_themes = theme_count.scalar() or 0

    final_count = await db.execute(
        select(func.count(Theme.id))
        .where(Theme.analysis_case_id == case.id)
        .where(Theme.final_selected == True)  # noqa: E712
    )
    case.total_final_themes = final_count.scalar() or 0

    await db.flush()


# ---------------------------------------------------------------------------
# Task 8 — Case Summary Generator
# ---------------------------------------------------------------------------

async def generate_case_summary(case_id: uuid.UUID, db: AsyncSession) -> dict:
    """Generate a summary of the case analysis results."""
    case = await db.get(AnalysisCase, case_id)
    if not case:
        return {"error": "Case not found"}

    # Count documents
    doc_count = await db.execute(
        select(func.count(CaseDocument.id))
        .where(CaseDocument.analysis_case_id == case_id)
    )

    # Count sections
    sections_total = await db.execute(
        select(func.count(DocumentSection.id))
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case_id)
    )

    # Count sections analyzed
    sections_analyzed = await db.execute(
        select(func.count(DocumentSection.id))
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case_id)
        .where(DocumentSection.screening_status == "analyze")
    )

    # Count findings
    findings_count = await db.execute(
        select(func.count(Fundstelle.id))
        .where(Fundstelle.analysis_case_id == case_id)
    )

    # Count themes
    themes_count = await db.execute(
        select(func.count(Theme.id))
        .where(Theme.analysis_case_id == case_id)
    )

    # Count final themes
    final_themes_count = await db.execute(
        select(func.count(Theme.id))
        .where(Theme.analysis_case_id == case_id)
        .where(Theme.final_selected == True)  # noqa: E712
    )

    # Count positive controls
    pc_count = await db.execute(
        select(func.count(PositiveControl.id))
        .where(PositiveControl.analysis_case_id == case_id)
    )

    # Get processing time from metrics
    metrics_result = await db.execute(
        select(PipelineMetrics)
        .where(PipelineMetrics.case_id == case_id)
        .order_by(PipelineMetrics.created_at.desc())
        .limit(1)
    )
    pipeline_metrics = metrics_result.scalar_one_or_none()

    return {
        "case_id": str(case_id),
        "title": case.title,
        "status": case.status,
        "documents": doc_count.scalar() or 0,
        "sections_total": sections_total.scalar() or 0,
        "sections_analyzed": sections_analyzed.scalar() or 0,
        "findings": findings_count.scalar() or 0,
        "themes": themes_count.scalar() or 0,
        "themes_final": final_themes_count.scalar() or 0,
        "positive_controls": pc_count.scalar() or 0,
        "processing_time_seconds": pipeline_metrics.processing_time_seconds if pipeline_metrics else None,
        "pipeline_warnings": case.pipeline_warnings or [],
    }
