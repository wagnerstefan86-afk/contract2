import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey
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
    absatz_ids: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    kategorie: Mapped[str] = mapped_column(String(200))
    risikostufe: Mapped[str] = mapped_column(String(50), default=Risikostufe.HINWEIS.value)
    kurzbeschreibung: Mapped[str] = mapped_column(Text)
    erklaerung: Mapped[str | None] = mapped_column(Text, nullable=True)
    empfehlung: Mapped[str | None] = mapped_column(Text, nullable=True)
    quelle_pass: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pruef_status: Mapped[str] = mapped_column(String(50), default=PruefStatus.OFFEN.value)
    pruef_kommentar: Mapped[str | None] = mapped_column(Text, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analyse = relationship("Analyse", back_populates="fundstellen")
    vertrag = relationship("Vertrag", back_populates="fundstellen")
