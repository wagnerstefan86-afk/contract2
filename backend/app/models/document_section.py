"""DocumentSection model — a chunk of text within a CaseDocument."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import SectionType, SectionRouting


class DocumentSection(Base):
    __tablename__ = "document_sections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_documents.id", ondelete="CASCADE")
    )

    section_index: Mapped[int] = mapped_column(Integer)
    page_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    heading_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    section_type: Mapped[str] = mapped_column(String(50), default=SectionType.BODY.value)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)

    raw_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String(64))

    # Policy scan routing result
    routing: Mapped[str | None] = mapped_column(String(50), nullable=True)
    routing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Step 6: Screening result
    screening_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    screening_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Step 7: Extraction status
    extraction_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    case_document = relationship("CaseDocument", back_populates="sections")
    positive_controls = relationship("PositiveControl", back_populates="document_section", cascade="all, delete-orphan")
