"""Theme and ThemeEvidence models — case-level consolidated risk themes."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import FinalSelectionBasis, EvidenceRole


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_cases.id", ondelete="CASCADE")
    )

    category: Mapped[str] = mapped_column(String(200))
    canonical_title: Mapped[str] = mapped_column(String(500))
    canonical_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_risk_core: Mapped[str | None] = mapped_column(String(300), nullable=True)
    severity: Mapped[str] = mapped_column(String(50))

    source_finding_count: Mapped[int] = mapped_column(Integer, default=0)
    source_document_count: Mapped[int] = mapped_column(Integer, default=0)
    primary_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_documents.id", ondelete="SET NULL"), nullable=True
    )

    conflict_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    conflict_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Final editorial selection
    final_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_editorial_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    final_rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_selection_basis: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    analysis_case = relationship("AnalysisCase", back_populates="themes")
    evidence = relationship("ThemeEvidence", back_populates="theme", cascade="all, delete-orphan")


class ThemeEvidence(Base):
    __tablename__ = "theme_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    theme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("themes.id", ondelete="CASCADE")
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fundstellen.id", ondelete="CASCADE")
    )

    evidence_role: Mapped[str] = mapped_column(String(50), default=EvidenceRole.SUPPORTING.value)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    theme = relationship("Theme", back_populates="evidence")
    finding = relationship("Fundstelle")
