import json
import logging
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import AnalysisJob, ExtractedLink, ExternalCheckResult, LlmAssessment
from app.schemas import (
    AssessmentResult,
    HealthResponse,
    HeaderFinding,
    JobCreated,
    JobResult,
    JobStatus,
    LinkCheckSummary,
    LinkDetail,
)
from app.services.orchestrator import run_analysis

logging.basicConfig(level=getattr(logging, settings.log_level))
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MailScope", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_BYTES = settings.max_upload_size_mb * 1024 * 1024


@app.get("/api/health", response_model=HealthResponse)
def health():
    return HealthResponse()


@app.post("/api/upload", response_model=JobCreated)
async def upload_email(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "No filename provided")
    ext = Path(file.filename).suffix.lower()
    if ext not in (".eml", ".msg"):
        raise HTTPException(400, "Only .eml and .msg files are supported")

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds {settings.max_upload_size_mb} MB limit")

    job = AnalysisJob(filename=file.filename, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)

    # Save file to temp location for background processing
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.write(content)
    tmp.close()

    background_tasks.add_task(run_analysis, job.id, tmp.name, ext)
    logger.info("Created analysis job %s for %s", job.id, file.filename)
    return JobCreated(job_id=job.id)


@app.get("/api/jobs/{job_id}", response_model=JobStatus)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return JobStatus(
        id=job.id,
        filename=job.filename,
        status=job.status,
        error_message=job.error_message,
        subject=job.subject,
        sender=job.sender,
        reply_to=job.reply_to,
        return_path=job.return_path,
        to_address=job.to_address,
        date=job.date,
        message_id=job.message_id,
        link_count=len(job.links),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@app.get("/api/jobs/{job_id}/result", response_model=JobResult)
def get_job_result(job_id: str, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")

    links_out: list[LinkDetail] = []
    for link in job.links:
        checks = [
            LinkCheckSummary(
                service=c.service,
                status=c.status,
                score=c.score,
                verdict=c.verdict,
                summary=json.loads(c.summary) if c.summary else None,
            )
            for c in link.checks
        ]
        links_out.append(
            LinkDetail(
                id=link.id,
                original_url=link.original_url,
                normalized_url=link.normalized_url,
                final_hostname=link.final_hostname,
                display_text=link.display_text,
                display_text_mismatch=bool(link.display_text_mismatch),
                suspicious_tld=bool(link.suspicious_tld),
                ip_literal=bool(link.ip_literal),
                punycode=bool(link.punycode),
                url_shortener=bool(link.url_shortener),
                tracking_heavy=bool(link.tracking_heavy),
                link_findings=json.loads(link.link_findings) if link.link_findings else None,
                checks=checks,
            )
        )

    assessment = None
    if job.assessment:
        a = job.assessment
        assessment = AssessmentResult(
            classification=a.classification,
            risk_score=a.risk_score,
            confidence=a.confidence,
            recommended_action=a.recommended_action,
            rationale=a.rationale,
            evidence=json.loads(a.evidence) if a.evidence else [],
            analyst_summary=a.analyst_summary,
        )

    header_findings = []
    if job.header_findings:
        for hf in json.loads(job.header_findings):
            header_findings.append(HeaderFinding(**hf))

    return JobResult(
        id=job.id,
        filename=job.filename,
        status=job.status,
        error_message=job.error_message,
        subject=job.subject,
        sender=job.sender,
        reply_to=job.reply_to,
        return_path=job.return_path,
        to_address=job.to_address,
        date=job.date,
        message_id=job.message_id,
        authentication_results=job.authentication_results,
        received_chain=json.loads(job.received_chain) if job.received_chain else [],
        raw_headers=job.raw_headers,
        structured_headers=json.loads(job.structured_headers) if job.structured_headers else None,
        body_text=job.body_text,
        attachment_metadata=json.loads(job.attachment_metadata) if job.attachment_metadata else [],
        header_findings=header_findings,
        links=links_out,
        assessment=assessment,
        created_at=job.created_at,
    )
