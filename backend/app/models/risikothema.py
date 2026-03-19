"""RisikoThema model — LLM-generated topic clusters that group multiple Fundstellen."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, Table, Column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# Many-to-many junction table
risikothema_fundstellen = Table(
    "risikothema_fundstellen",
    Base.metadata,
    Column("risikothema_id", UUID(as_uuid=True), ForeignKey("risikothemen.id", ondelete="CASCADE"), primary_key=True),
    Column("fundstelle_id", UUID(as_uuid=True), ForeignKey("fundstellen.id", ondelete="CASCADE"), primary_key=True),
)


class RisikoThema(Base):
    __tablename__ = "risikothemen"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analyse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("analysen.id", ondelete="CASCADE"))
    vertrag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vertraege.id", ondelete="CASCADE"))
    titel: Mapped[str] = mapped_column(String(300))
    kategorie: Mapped[str] = mapped_column(String(200))
    risikostufe: Mapped[str] = mapped_column(String(50))
    beschreibung: Mapped[str] = mapped_column(Text)
    sortierung: Mapped[int] = mapped_column(Integer, default=0)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # --- Final Editorial Pass fields ---
    # Whether this topic survived the final editorial reduction
    final_selected: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Reason for rejection (only set if final_selected=False after editorial pass ran)
    final_verwerfungsgrund: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Rich editorial output for selected topics (titel, kurzbeschreibung,
    # warum_verhandlungsrelevant, alternativformulierung, bieterfrage,
    # verhandlungsargumente, primaerfundstelle_id, sekundaerfundstelle_ids)
    final_editorial: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Decision Layer fields ---
    # Workflow status: OPEN, IN_NEGOTIATION, ACCEPTED, REJECTED, CLOSED
    decision_status: Mapped[str] = mapped_column(String(50), default="OPEN", server_default="OPEN")
    # Free-text comment from the reviewer
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Human overrides for AI-generated recommendation/negotiation
    recommendation_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    negotiation_override: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who decided and when
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("benutzer.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    analyse = relationship("Analyse", back_populates="risikothemen")
    vertrag = relationship("Vertrag", back_populates="risikothemen")
    fundstellen = relationship("Fundstelle", secondary=risikothema_fundstellen, back_populates="risikothemen")
    decided_by = relationship("Benutzer", foreign_keys=[decided_by_user_id], lazy="selectin")
