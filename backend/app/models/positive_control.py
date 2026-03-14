"""PositiveControl model — accepted controls / certifications found in documents."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import ControlType, ControlStatus


class PositiveControl(Base):
    __tablename__ = "positive_controls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_cases.id", ondelete="CASCADE")
    )
    case_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_documents.id", ondelete="CASCADE")
    )
    document_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_sections.id", ondelete="SET NULL"), nullable=True
    )

    control_type: Mapped[str] = mapped_column(String(50))
    control_value: Mapped[str] = mapped_column(String(300))
    source_text: Mapped[str] = mapped_column(Text)

    policy_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_rules.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(50), default=ControlStatus.ACCEPTED.value)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    analysis_case = relationship("AnalysisCase", back_populates="positive_controls")
    case_document = relationship("CaseDocument", back_populates="positive_controls")
    document_section = relationship("DocumentSection", back_populates="positive_controls")
