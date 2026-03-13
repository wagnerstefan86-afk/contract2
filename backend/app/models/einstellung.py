import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Einstellung(Base):
    __tablename__ = "einstellungen"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schluessel: Mapped[str] = mapped_column(String(200), unique=True)
    wert: Mapped[str] = mapped_column(Text)
    beschreibung: Mapped[str | None] = mapped_column(Text, nullable=True)
    aktualisiert_am: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
