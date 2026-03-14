"""Authentication utilities: JWT tokens, password hashing, FastAPI dependencies."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.benutzer import Benutzer, BenutzerStatus, BenutzerRolle

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT config
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours for MVP

# OAuth2 scheme — expects token in Authorization: Bearer <token>
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_passwort(passwort: str) -> str:
    return pwd_context.hash(passwort)


def verify_passwort(passwort: str, passwort_hash: str) -> bool:
    return pwd_context.verify(passwort, passwort_hash)


def create_access_token(benutzer_id: uuid.UUID, rolle: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(benutzer_id),
        "rolle": rolle,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token ungültig oder abgelaufen",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Benutzer:
    """Dependency: returns the authenticated, active user or raises 401/403."""
    payload = decode_token(token)
    benutzer_id = payload.get("sub")
    if not benutzer_id:
        raise HTTPException(status_code=401, detail="Token ungültig")

    benutzer = await db.get(Benutzer, uuid.UUID(benutzer_id))
    if not benutzer:
        raise HTTPException(status_code=401, detail="Benutzer nicht gefunden")

    if benutzer.status == BenutzerStatus.AUSSTEHEND.value:
        raise HTTPException(status_code=403, detail="Registrierung noch nicht freigegeben")
    if benutzer.status == BenutzerStatus.GESPERRT.value:
        raise HTTPException(status_code=403, detail="Benutzer ist gesperrt")

    return benutzer


async def require_admin(
    benutzer: Benutzer = Depends(get_current_user),
) -> Benutzer:
    """Dependency: requires the current user to be Admin."""
    if benutzer.rolle != BenutzerRolle.ADMIN.value:
        raise HTTPException(status_code=403, detail="Nur Administratoren haben Zugriff")
    return benutzer
