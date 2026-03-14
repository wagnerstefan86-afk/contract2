"""RisikoThema model — LLM-generated topic clusters that group multiple Fundstellen."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, Table, Column
from sqlalchemy.dialects.postgresql import UUID
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

    analyse = relationship("Analyse", back_populates="risikothemen")
    vertrag = relationship("Vertrag", back_populates="risikothemen")
    fundstellen = relationship("Fundstelle", secondary=risikothema_fundstellen, back_populates="risikothemen")
