from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class JobCreated(BaseModel):
    job_id: str


class LinkCheckSummary(BaseModel):
    service: str
    status: str
    score: float | None = None
    verdict: str | None = None
    summary: dict[str, Any] | None = None


class LinkDetail(BaseModel):
    id: str
    original_url: str
    normalized_url: str
    final_hostname: str | None = None
    display_text: str | None = None
    display_text_mismatch: bool = False
    suspicious_tld: bool = False
    ip_literal: bool = False
    punycode: bool = False
    url_shortener: bool = False
    tracking_heavy: bool = False
    link_findings: dict[str, Any] | None = None
    checks: list[LinkCheckSummary] = []


class HeaderFinding(BaseModel):
    id: str
    severity: str
    title: str
    detail: str


class PreScores(BaseModel):
    phishing_score: int = 0
    advertising_score: int = 0
    legitimacy_score: int = 0
    breakdown: dict[str, float] = {}


class AssessmentResult(BaseModel):
    source: str = "llm"  # llm | deterministic | fallback
    classification: str | None = None
    risk_score: int | None = None
    confidence: int | None = None
    recommended_action: str | None = None
    rationale: str | None = None
    evidence: list[str] = []
    analyst_summary: str | None = None


class ServiceFlags(BaseModel):
    vt_enabled: bool = True
    urlscan_enabled: bool = True
    llm_enabled: bool = True


class JobStatus(BaseModel):
    id: str
    filename: str
    status: str
    error_message: str | None = None
    warnings: list[str] = []
    subject: str | None = None
    sender: str | None = None
    reply_to: str | None = None
    return_path: str | None = None
    to_address: str | None = None
    date: str | None = None
    message_id: str | None = None
    link_count: int = 0
    services: ServiceFlags = ServiceFlags()
    created_at: datetime | None = None
    updated_at: datetime | None = None


class JobResult(BaseModel):
    id: str
    filename: str
    status: str
    error_message: str | None = None
    warnings: list[str] = []
    subject: str | None = None
    sender: str | None = None
    reply_to: str | None = None
    return_path: str | None = None
    to_address: str | None = None
    date: str | None = None
    message_id: str | None = None
    authentication_results: str | None = None
    received_chain: list[str] = []
    raw_headers: str | None = None
    structured_headers: dict[str, Any] | None = None
    body_text: str | None = None
    attachment_metadata: list[dict[str, Any]] = []
    header_findings: list[HeaderFinding] = []
    pre_scores: PreScores | None = None
    links: list[LinkDetail] = []
    assessment: AssessmentResult | None = None
    services: ServiceFlags = ServiceFlags()
    created_at: datetime | None = None


class ExportResult(BaseModel):
    """Full structured export of an analysis."""
    job_id: str
    filename: str
    status: str
    warnings: list[str] = []
    email_metadata: dict[str, Any] = {}
    header_findings: list[HeaderFinding] = []
    pre_scores: PreScores | None = None
    links: list[LinkDetail] = []
    assessment: AssessmentResult | None = None
    services: ServiceFlags = ServiceFlags()
    analyzed_at: datetime | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.2.0"
    services: ServiceFlags = ServiceFlags()
