"""AnalysisCase model — central entity for a multi-document review case."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import CaseStatus


class AnalysisCase(Base):
    __tablename__ = "analysis_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_case_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    customer_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default=CaseStatus.CREATED.value)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    policy_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_profiles.id"), nullable=True
    )

    # Aggregate counters (updated as pipeline progresses)
    total_documents: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_characters: Mapped[int] = mapped_column(Integer, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    total_findings: Mapped[int] = mapped_column(Integer, default=0)
    total_themes: Mapped[int] = mapped_column(Integer, default=0)
    total_final_themes: Mapped[int] = mapped_column(Integer, default=0)

    processing_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    documents = relationship("CaseDocument", back_populates="analysis_case", cascade="all, delete-orphan")
    positive_controls = relationship("PositiveControl", back_populates="analysis_case", cascade="all, delete-orphan")
    themes = relationship("Theme", back_populates="analysis_case", cascade="all, delete-orphan")
    processing_jobs = relationship("ProcessingJob", back_populates="analysis_case", cascade="all, delete-orphan")
    policy_profile = relationship("PolicyProfile", back_populates="analysis_cases")
