"""Admin-only user management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import require_admin
from app.models.benutzer import Benutzer, BenutzerRolle, BenutzerStatus
from app.schemas.benutzer import BenutzerResponse, BenutzerUpdate

router = APIRouter(prefix="/benutzer", tags=["Benutzerverwaltung"])


@router.get("", response_model=list[BenutzerResponse])
async def liste_benutzer(
    admin: Benutzer = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users (admin only)."""
    result = await db.execute(select(Benutzer).order_by(Benutzer.erstellt_am.desc()))
    return result.scalars().all()


@router.patch("/{benutzer_id}", response_model=BenutzerResponse)
async def benutzer_aktualisieren(
    benutzer_id: uuid.UUID,
    update: BenutzerUpdate,
    admin: Benutzer = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update user role or status (admin only)."""
    benutzer = await db.get(Benutzer, benutzer_id)
    if not benutzer:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    # Prevent admin from demoting themselves
    if benutzer.id == admin.id and update.rolle and update.rolle != BenutzerRolle.ADMIN.value:
        raise HTTPException(status_code=400, detail="Sie können sich nicht selbst die Admin-Rolle entziehen")

    if benutzer.id == admin.id and update.status and update.status != BenutzerStatus.AKTIV.value:
        raise HTTPException(status_code=400, detail="Sie können sich nicht selbst sperren")

    if update.rolle is not None:
        if update.rolle not in [r.value for r in BenutzerRolle]:
            raise HTTPException(status_code=400, detail=f"Ungültige Rolle: {update.rolle}")
        benutzer.rolle = update.rolle

    if update.status is not None:
        if update.status not in [s.value for s in BenutzerStatus]:
            raise HTTPException(status_code=400, detail=f"Ungültiger Status: {update.status}")
        benutzer.status = update.status

    await db.commit()
    await db.refresh(benutzer)
    return benutzer


@router.post("/{benutzer_id}/freigeben", response_model=BenutzerResponse)
async def benutzer_freigeben(
    benutzer_id: uuid.UUID,
    admin: Benutzer = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending user registration (admin only)."""
    benutzer = await db.get(Benutzer, benutzer_id)
    if not benutzer:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    benutzer.status = BenutzerStatus.AKTIV.value
    await db.commit()
    await db.refresh(benutzer)
    return benutzer


@router.post("/{benutzer_id}/sperren", response_model=BenutzerResponse)
async def benutzer_sperren(
    benutzer_id: uuid.UUID,
    admin: Benutzer = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Block a user (admin only)."""
    benutzer = await db.get(Benutzer, benutzer_id)
    if not benutzer:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    if benutzer.id == admin.id:
        raise HTTPException(status_code=400, detail="Sie können sich nicht selbst sperren")

    benutzer.status = BenutzerStatus.GESPERRT.value
    await db.commit()
    await db.refresh(benutzer)
    return benutzer
