import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

import enum


class Risikostufe(str, enum.Enum):
    HOCH = "Hoch"
    MITTEL = "Mittel"
    NIEDRIG = "Niedrig"
    HINWEIS = "Hinweis"


class PruefStatus(str, enum.Enum):
    OFFEN = "Offen"
    BESTAETIGT = "Bestätigt"
    ABGELEHNT = "Abgelehnt"
    ZURUECKGESTELLT = "Zurückgestellt"


class Fundstelle(Base):
    __tablename__ = "fundstellen"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analyse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysen.id", ondelete="CASCADE"))
    vertrag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vertraege.id", ondelete="CASCADE"))
    textstelle: Mapped[str] = mapped_column(Text)
    absatz_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    kategorie: Mapped[str] = mapped_column(String(200))
    risikostufe: Mapped[str] = mapped_column(String(50), default=Risikostufe.HINWEIS.value)
    kurzbeschreibung: Mapped[str] = mapped_column(Text)
    erklaerung: Mapped[str | None] = mapped_column(Text, nullable=True)
    empfehlung: Mapped[str | None] = mapped_column(Text, nullable=True)
    quelle_pass: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pruef_status: Mapped[str] = mapped_column(String(50), default=PruefStatus.OFFEN.value)
    pruef_kommentar: Mapped[str | None] = mapped_column(Text, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Structured detail: enriched context, structured recommendations, page refs
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Consolidation debug: how many raw candidates were merged into this finding
    zusammenfuehrung: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Case-based pipeline extensions (nullable for backward compat) ---
    analysis_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("analysis_cases.id", ondelete="CASCADE"), nullable=True
    )
    case_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_documents.id", ondelete="SET NULL"), nullable=True
    )
    document_section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_sections.id", ondelete="SET NULL"), nullable=True
    )
    extraction_pass: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Policy engine flags
    is_positive_control: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_suppressed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_out_of_scope: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    out_of_scope_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suppression_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policy_rules.id", ondelete="SET NULL"), nullable=True
    )
    normalized_risk_core: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Relationships
    analyse = relationship("Analyse", back_populates="fundstellen")
    vertrag = relationship("Vertrag", back_populates="fundstellen")
    risikothemen = relationship("RisikoThema", secondary="risikothema_fundstellen", back_populates="fundstellen")
