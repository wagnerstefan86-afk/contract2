import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

import enum


class AnalyseStatus(str, enum.Enum):
    GESTARTET = "Gestartet"
    PASS_1 = "Pass 1 läuft"
    PASS_2 = "Pass 2 läuft"
    PASS_3 = "Pass 3 läuft"
    PASS_4 = "Pass 4 läuft"
    CLUSTERING = "Clustering läuft"
    KONSOLIDIERUNG = "Konsolidierung"
    ABGESCHLOSSEN = "Abgeschlossen"
    FEHLGESCHLAGEN = "Fehlgeschlagen"


class Analyse(Base):
    __tablename__ = "analysen"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vertrag_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vertraege.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(50), default=AnalyseStatus.GESTARTET.value)
    aktueller_pass: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fortschritt: Mapped[int] = mapped_column(Integer, default=0)
    konfig_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    gestartet_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    beendet_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fehler: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pipeline evaluation / debug data — written at end of analysis
    auswertung: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    vertrag = relationship("Vertrag", back_populates="analysen")
    fundstellen = relationship("Fundstelle", back_populates="analyse", cascade="all, delete-orphan")
    risikothemen = relationship("RisikoThema", back_populates="analyse", cascade="all, delete-orphan")
