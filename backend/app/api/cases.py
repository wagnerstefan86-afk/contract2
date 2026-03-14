"""API endpoints for AnalysisCase — multi-document review cases."""

import asyncio
import os
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, async_session
from app.auth import get_current_user
from app.config import settings
from app.models.benutzer import Benutzer
from app.models.analysis_case import AnalysisCase
from app.models.case_document import CaseDocument
from app.models.document_section import DocumentSection
from app.models.positive_control import PositiveControl
from app.models.enums import CaseStatus, DocumentStatus, ParseStatus, ClassificationStatus
from app.models.theme import Theme, ThemeEvidence
from app.models.fundstelle import Fundstelle
from app.schemas.analysis_case import (
    AnalysisCaseResponse,
    AnalysisCaseDetail,
    AnalysisCaseCreate,
    CaseDocumentResponse,
)
from app.schemas.policy import PositiveControlResponse, DocumentSectionResponse
from app.schemas.theme import ThemeResponse, ThemeEvidenceResponse, CaseThemesResponse

router = APIRouter(prefix="/cases", tags=["Analysis Cases"])


# ---------------------------------------------------------------------------
# Case CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[AnalysisCaseResponse])
async def list_cases(
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnalysisCase).order_by(AnalysisCase.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=AnalysisCaseResponse, status_code=201)
async def create_case(
    body: AnalysisCaseCreate,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case = AnalysisCase(
        title=body.title,
        external_case_ref=body.external_case_ref,
        customer_name=body.customer_name,
        policy_profile_id=body.policy_profile_id,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


@router.get("/{case_id}", response_model=AnalysisCaseDetail)
async def get_case(
    case_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AnalysisCase)
        .where(AnalysisCase.id == case_id)
        .options(selectinload(AnalysisCase.documents))
    )
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case nicht gefunden")
    return case


@router.delete("/{case_id}", status_code=204)
async def delete_case(
    case_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case = await db.get(AnalysisCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case nicht gefunden")
    await db.delete(case)
    await db.commit()


# ---------------------------------------------------------------------------
# Document upload
# ---------------------------------------------------------------------------

@router.post("/{case_id}/documents", response_model=CaseDocumentResponse, status_code=201)
async def upload_document(
    case_id: uuid.UUID,
    datei: UploadFile = File(...),
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case = await db.get(AnalysisCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case nicht gefunden")

    upload_dir = os.path.join(settings.upload_dir, "cases", str(case_id))
    os.makedirs(upload_dir, exist_ok=True)

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(datei.filename or "upload")[1]
    file_path = os.path.join(upload_dir, f"{file_id}{ext}")

    with open(file_path, "wb") as f:
        shutil.copyfileobj(datei.file, f)

    doc = CaseDocument(
        analysis_case_id=case_id,
        filename=datei.filename or "unbekannt",
        original_mime_type=datei.content_type,
        source_storage_path=file_path,
    )
    db.add(doc)
    case.total_documents = (case.total_documents or 0) + 1
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{case_id}/documents", response_model=list[CaseDocumentResponse])
async def list_documents(
    case_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CaseDocument)
        .where(CaseDocument.analysis_case_id == case_id)
        .order_by(CaseDocument.document_role_rank.desc())
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Start pipeline
# ---------------------------------------------------------------------------

@router.post("/{case_id}/analyze", response_model=AnalysisCaseResponse)
async def start_analysis(
    case_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    case = await db.get(AnalysisCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case nicht gefunden")
    if case.status == CaseStatus.PROCESSING.value:
        raise HTTPException(status_code=409, detail="Analyse läuft bereits")

    case.status = CaseStatus.INGESTING.value
    await db.commit()
    await db.refresh(case)

    asyncio.create_task(_run_case_pipeline_background(case_id))
    return case


async def _run_case_pipeline_background(case_id: uuid.UUID) -> None:
    from app.discovery.case_pipeline import run_case_pipeline
    async with async_session() as db:
        await run_case_pipeline(case_id, db)


# ---------------------------------------------------------------------------
# Results — positive controls, sections, out-of-scope
# ---------------------------------------------------------------------------

@router.get("/{case_id}/positive-controls", response_model=list[PositiveControlResponse])
async def list_positive_controls(
    case_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PositiveControl)
        .where(PositiveControl.analysis_case_id == case_id)
        .order_by(PositiveControl.created_at)
    )
    return result.scalars().all()


@router.get("/{case_id}/sections", response_model=list[DocumentSectionResponse])
async def list_sections(
    case_id: uuid.UUID,
    routing: str | None = None,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(DocumentSection)
        .join(CaseDocument, DocumentSection.case_document_id == CaseDocument.id)
        .where(CaseDocument.analysis_case_id == case_id)
    )
    if routing:
        query = query.where(DocumentSection.routing == routing)
    query = query.order_by(DocumentSection.section_index)

    result = await db.execute(query)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Results — themes
# ---------------------------------------------------------------------------

@router.get("/{case_id}/themes", response_model=CaseThemesResponse)
async def list_themes(
    case_id: uuid.UUID,
    final_only: bool = False,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all themes for a case, optionally filtered to final-selected only."""
    query = (
        select(Theme)
        .where(Theme.analysis_case_id == case_id)
        .options(selectinload(Theme.evidence))
    )
    if final_only:
        query = query.where(Theme.final_selected == True)  # noqa: E712

    query = query.order_by(Theme.final_rank.asc().nullslast(), Theme.created_at)
    result = await db.execute(query)
    themes = list(result.scalars().all())

    # Denormalize evidence with finding details
    theme_responses = []
    for theme in themes:
        evidence_responses = []
        for ev in theme.evidence:
            finding = await db.get(Fundstelle, ev.finding_id)
            evidence_responses.append(ThemeEvidenceResponse(
                id=ev.id,
                finding_id=ev.finding_id,
                evidence_role=ev.evidence_role,
                rank=ev.rank,
                kurzbeschreibung=finding.kurzbeschreibung if finding else None,
                kategorie=finding.kategorie if finding else None,
                risikostufe=finding.risikostufe if finding else None,
                textstelle=finding.textstelle if finding else None,
            ))

        theme_responses.append(ThemeResponse(
            id=theme.id,
            analysis_case_id=theme.analysis_case_id,
            category=theme.category,
            canonical_title=theme.canonical_title,
            canonical_summary=theme.canonical_summary,
            severity=theme.severity,
            source_finding_count=theme.source_finding_count,
            source_document_count=theme.source_document_count,
            conflict_detected=theme.conflict_detected,
            conflict_summary=theme.conflict_summary,
            final_selected=theme.final_selected,
            final_rank=theme.final_rank,
            final_editorial_json=theme.final_editorial_json,
            final_rejection_reason=theme.final_rejection_reason,
            final_selection_basis=theme.final_selection_basis,
            created_at=theme.created_at,
            evidence=evidence_responses,
        ))

    # Count totals
    total_final = sum(1 for t in themes if t.final_selected)
    finding_count_result = await db.execute(
        select(func.count(Fundstelle.id))
        .where(Fundstelle.analysis_case_id == case_id)
    )
    total_findings = finding_count_result.scalar() or 0

    return CaseThemesResponse(
        themes=theme_responses,
        total_themes=len(themes),
        total_final=total_final,
        total_findings=total_findings,
    )
