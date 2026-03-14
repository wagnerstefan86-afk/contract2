"""CaseDocument model — a single document within an AnalysisCase."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import DocumentType, DocumentStatus, ParseStatus, ClassificationStatus


class CaseDocument(Base):
    __tablename__ = "case_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_cases.id", ondelete="CASCADE")
    )

    filename: Mapped[str] = mapped_column(String(500))
    original_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)

    document_type: Mapped[str] = mapped_column(String(50), default=DocumentType.OTHER.value)
    document_role_rank: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(50), default=DocumentStatus.UPLOADED.value)
    parse_status: Mapped[str] = mapped_column(String(50), default=ParseStatus.PENDING.value)
    classification_status: Mapped[str] = mapped_column(String(50), default=ClassificationStatus.PENDING.value)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    source_storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    extracted_text_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    analysis_case = relationship("AnalysisCase", back_populates="documents")
    sections = relationship("DocumentSection", back_populates="case_document", cascade="all, delete-orphan")
    positive_controls = relationship("PositiveControl", back_populates="case_document", cascade="all, delete-orphan")
