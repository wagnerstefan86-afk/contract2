"""Case Pipeline Orchestrator — multi-document analysis pipeline.

Manages the full case lifecycle:
1. Case Ingest — register documents
2. Document Parse — extract text
3. Document Classify — determine document type
4. Section Split — chunk into sections
5. Policy Scan — route sections via policy rules
6. Screening — filter non-relevant sections (placeholder)
7. Extraction — LLM-based finding extraction per section
8. Case Clustering — group findings into themes
9. Case Consolidation — deduplicate and merge themes
10. Final Editorial — select core themes for reviewers

Each step creates/updates ProcessingJob records for resume capability.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_case import AnalysisCase
from app.models.case_document import CaseDocument
from app.models.document_section import DocumentSection
from app.models.positive_control import PositiveControl
from app.models.processing_job import ProcessingJob
from app.models.enums import (
    CaseStatus, DocumentStatus, ParseStatus, ClassificationStatus,
    JobType, JobStatus, SectionRouting, ControlType, ControlStatus,
)
from app.discovery.document_parser import parse_document, classify_document, compute_sha256, detect_language
from app.discovery.section_splitter import split_into_sections
from app.discovery.policy_engine import load_active_rules, scan_section
from app.discovery.llm_client import lade_llm_config

logger = logging.getLogger(__name__)


async def run_case_pipeline(case_id: uuid.UUID, db: AsyncSession) -> None:
    """Run the full case analysis pipeline.

    This is the main entry point for case-based analysis.
    Each step is wrapped in a ProcessingJob for observability and resume.
    """
    case = await db.get(AnalysisCase, case_id)
    if not case:
        logger.error(f"AnalysisCase {case_id} nicht gefunden")
        return

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

        # Update case counters
        await _update_case_counters(db, case)

        case.status = CaseStatus.COMPLETED.value
        case.finished_at = datetime.utcnow()
        await db.commit()

        logger.info(f"Case pipeline abgeschlossen: {case_id}")

    except Exception as e:
        logger.exception(f"Case pipeline fehlgeschlagen: {e}")
        case.status = CaseStatus.FAILED.value
        case.failure_reason = str(e)
        case.finished_at = datetime.utcnow()
        await db.commit()


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

            # Store extracted text path (we store inline for now via section split)
            # The raw text is kept in memory and passed to section splitter

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
        select(DocumentSection.id)
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case.id)
    )
    case.total_chunks = len(section_result.all())

    await db.flush()
