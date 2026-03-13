from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.einstellung import Einstellung
from app.schemas.einstellung import EinstellungResponse, EinstellungUpdate

router = APIRouter(prefix="/einstellungen", tags=["Einstellungen"])


@router.get("", response_model=list[EinstellungResponse])
async def liste_einstellungen(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Einstellung).order_by(Einstellung.schluessel))
    return result.scalars().all()


@router.put("/{schluessel}", response_model=EinstellungResponse)
async def einstellung_setzen(schluessel: str, update: EinstellungUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Einstellung).where(Einstellung.schluessel == schluessel))
    einstellung = result.scalar_one_or_none()

    if einstellung:
        einstellung.wert = update.wert
    else:
        einstellung = Einstellung(schluessel=schluessel, wert=update.wert)
        db.add(einstellung)

    await db.commit()
    await db.refresh(einstellung)
    return einstellung
