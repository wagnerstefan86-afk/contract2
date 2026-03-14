"""Authentication endpoints: register, login, current user."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import hash_passwort, verify_passwort, create_access_token, get_current_user
from app.models.benutzer import Benutzer, BenutzerStatus, BenutzerRolle
from app.schemas.benutzer import (
    RegistrierungRequest, LoginRequest, TokenResponse, BenutzerResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentifizierung"])


@router.post("/registrieren", response_model=BenutzerResponse)
async def registrieren(req: RegistrierungRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user. Status will be 'Ausstehend' until approved by admin."""
    # Check if email already exists
    existing = await db.execute(
        select(Benutzer).where(Benutzer.email == req.email.lower().strip())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="E-Mail-Adresse bereits registriert")

    if len(req.passwort) < 6:
        raise HTTPException(status_code=400, detail="Passwort muss mindestens 6 Zeichen lang sein")

    benutzer = Benutzer(
        name=req.name.strip(),
        email=req.email.lower().strip(),
        passwort_hash=hash_passwort(req.passwort),
        rolle=BenutzerRolle.BENUTZER.value,
        status=BenutzerStatus.AUSSTEHEND.value,
    )
    db.add(benutzer)
    await db.commit()
    await db.refresh(benutzer)
    return benutzer


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate and return JWT token."""
    result = await db.execute(
        select(Benutzer).where(Benutzer.email == req.email.lower().strip())
    )
    benutzer = result.scalar_one_or_none()

    if not benutzer or not verify_passwort(req.passwort, benutzer.passwort_hash):
        raise HTTPException(status_code=401, detail="E-Mail oder Passwort falsch")

    if benutzer.status == BenutzerStatus.AUSSTEHEND.value:
        raise HTTPException(
            status_code=403,
            detail="Registrierung noch nicht freigegeben. Bitte warten Sie auf die Freigabe durch einen Administrator."
        )

    if benutzer.status == BenutzerStatus.GESPERRT.value:
        raise HTTPException(
            status_code=403,
            detail="Ihr Konto wurde gesperrt. Bitte kontaktieren Sie einen Administrator."
        )

    token = create_access_token(benutzer.id, benutzer.rolle)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=BenutzerResponse)
async def aktueller_benutzer(benutzer: Benutzer = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return benutzer
