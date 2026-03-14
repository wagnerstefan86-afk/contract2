from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr


class RegistrierungRequest(BaseModel):
    name: str
    email: str
    passwort: str


class LoginRequest(BaseModel):
    email: str
    passwort: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BenutzerResponse(BaseModel):
    id: UUID
    name: str
    email: str
    rolle: str
    status: str
    erstellt_am: datetime
    aktualisiert_am: datetime

    model_config = {"from_attributes": True}


class BenutzerUpdate(BaseModel):
    rolle: str | None = None
    status: str | None = None
