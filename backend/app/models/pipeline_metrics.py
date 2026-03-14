"""PipelineMetrics and ThemeDebugSnapshot models for pipeline observability."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, Float, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PipelineMetrics(Base):
    __tablename__ = "pipeline_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_cases.id", ondelete="CASCADE")
    )

    sections_total: Mapped[int] = mapped_column(Integer, default=0)
    sections_screened: Mapped[int] = mapped_column(Integer, default=0)
    sections_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    sections_ignored: Mapped[int] = mapped_column(Integer, default=0)
    sections_context: Mapped[int] = mapped_column(Integer, default=0)
    findings_created: Mapped[int] = mapped_column(Integer, default=0)
    positive_controls_found: Mapped[int] = mapped_column(Integer, default=0)
    clusters_created: Mapped[int] = mapped_column(Integer, default=0)
    themes_after_consolidation: Mapped[int] = mapped_column(Integer, default=0)
    themes_final: Mapped[int] = mapped_column(Integer, default=0)
    processing_time_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    llm_calls_total: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analysis_case = relationship("AnalysisCase", backref="pipeline_metrics")


class ThemeDebugSnapshot(Base):
    __tablename__ = "theme_debug_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_cases.id", ondelete="CASCADE")
    )

    stage: Mapped[str] = mapped_column(String(100))
    data_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analysis_case = relationship("AnalysisCase", backref="debug_snapshots")
