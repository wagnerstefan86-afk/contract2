import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

import enum


class BenutzerRolle(str, enum.Enum):
    BENUTZER = "Benutzer"
    ADMIN = "Admin"


class BenutzerStatus(str, enum.Enum):
    AUSSTEHEND = "Ausstehend"
    AKTIV = "Aktiv"
    GESPERRT = "Gesperrt"


class Benutzer(Base):
    __tablename__ = "benutzer"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(500), unique=True, index=True)
    passwort_hash: Mapped[str] = mapped_column(Text)
    rolle: Mapped[str] = mapped_column(String(50), default=BenutzerRolle.BENUTZER.value)
    status: Mapped[str] = mapped_column(String(50), default=BenutzerStatus.AUSSTEHEND.value)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    aktualisiert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
