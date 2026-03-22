import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# Valid statuses: queued | parsing | extracting_links | checking_reputation | llm_assessment | completed | completed_with_warnings | failed
class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id = Column(String, primary_key=True, default=_uuid)
    filename = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
    error_message = Column(Text, nullable=True)
    warnings = Column(Text, nullable=True)  # JSON array of warning strings
    subject = Column(String, nullable=True)
    sender = Column(String, nullable=True)
    reply_to = Column(String, nullable=True)
    return_path = Column(String, nullable=True)
    to_address = Column(String, nullable=True)
    date = Column(String, nullable=True)
    message_id = Column(String, nullable=True)
    authentication_results = Column(Text, nullable=True)
    received_chain = Column(Text, nullable=True)  # JSON array
    raw_headers = Column(Text, nullable=True)
    structured_headers = Column(Text, nullable=True)  # JSON
    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    attachment_metadata = Column(Text, nullable=True)  # JSON array
    header_findings = Column(Text, nullable=True)  # JSON array of heuristic findings

    # Deterministic pre-scores
    phishing_score = Column(Integer, nullable=True)
    advertising_score = Column(Integer, nullable=True)
    legitimacy_score = Column(Integer, nullable=True)
    pre_score_details = Column(Text, nullable=True)  # JSON object with breakdown

    # Service flags (snapshot of what was enabled for this job)
    vt_enabled = Column(Integer, default=1)
    urlscan_enabled = Column(Integer, default=1)
    llm_enabled = Column(Integer, default=1)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    links = relationship("ExtractedLink", back_populates="job", cascade="all, delete-orphan")
    assessment = relationship("LlmAssessment", back_populates="job", uselist=False, cascade="all, delete-orphan")


class ExtractedLink(Base):
    __tablename__ = "extracted_links"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("analysis_jobs.id"), nullable=False)
    original_url = Column(Text, nullable=False)
    normalized_url = Column(Text, nullable=False)
    final_hostname = Column(String, nullable=True)
    display_text = Column(String, nullable=True)
    display_text_mismatch = Column(Integer, default=0)
    suspicious_tld = Column(Integer, default=0)
    ip_literal = Column(Integer, default=0)
    punycode = Column(Integer, default=0)
    url_shortener = Column(Integer, default=0)
    tracking_heavy = Column(Integer, default=0)
    link_findings = Column(Text, nullable=True)  # JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    job = relationship("AnalysisJob", back_populates="links")
    checks = relationship("ExternalCheckResult", back_populates="link", cascade="all, delete-orphan")


class ExternalCheckResult(Base):
    __tablename__ = "external_check_results"

    id = Column(String, primary_key=True, default=_uuid)
    link_id = Column(String, ForeignKey("extracted_links.id"), nullable=False)
    service = Column(String, nullable=False)  # virustotal | urlscan
    submission_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")  # pending|polling|done|error|timeout|skipped
    raw_result = Column(Text, nullable=True)  # JSON
    summary = Column(Text, nullable=True)  # JSON summary
    score = Column(Float, nullable=True)
    verdict = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    link = relationship("ExtractedLink", back_populates="checks")


class LlmAssessment(Base):
    __tablename__ = "llm_assessments"

    id = Column(String, primary_key=True, default=_uuid)
    job_id = Column(String, ForeignKey("analysis_jobs.id"), nullable=False)
    source = Column(String, nullable=False, default="llm")  # llm | deterministic | fallback
    classification = Column(String, nullable=True)
    risk_score = Column(Integer, nullable=True)
    confidence = Column(Integer, nullable=True)
    recommended_action = Column(String, nullable=True)
    rationale = Column(Text, nullable=True)
    evidence = Column(Text, nullable=True)  # JSON array
    analyst_summary = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    job = relationship("AnalysisJob", back_populates="assessment")
