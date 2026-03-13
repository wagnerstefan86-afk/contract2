import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.fundstelle import Fundstelle
from app.schemas.fundstelle import FundstelleResponse, FundstelleUpdate

router = APIRouter(prefix="/fundstellen", tags=["Fundstellen"])


@router.get("/vertrag/{vertrag_id}", response_model=list[FundstelleResponse])
async def fundstellen_fuer_vertrag(vertrag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Fundstelle).where(Fundstelle.vertrag_id == vertrag_id).order_by(Fundstelle.erstellt_am.desc())
    )
    return result.scalars().all()


@router.get("/offen", response_model=list[FundstelleResponse])
async def offene_fundstellen(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Fundstelle).where(Fundstelle.pruef_status == "Offen").order_by(Fundstelle.erstellt_am.desc())
    )
    return result.scalars().all()


@router.get("/{fundstelle_id}", response_model=FundstelleResponse)
async def fundstelle_detail(fundstelle_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    fundstelle = await db.get(Fundstelle, fundstelle_id)
    if not fundstelle:
        raise HTTPException(status_code=404, detail="Fundstelle nicht gefunden")
    return fundstelle


@router.patch("/{fundstelle_id}", response_model=FundstelleResponse)
async def fundstelle_bewerten(fundstelle_id: uuid.UUID, update: FundstelleUpdate, db: AsyncSession = Depends(get_db)):
    fundstelle = await db.get(Fundstelle, fundstelle_id)
    if not fundstelle:
        raise HTTPException(status_code=404, detail="Fundstelle nicht gefunden")

    if update.pruef_status is not None:
        fundstelle.pruef_status = update.pruef_status
    if update.pruef_kommentar is not None:
        fundstelle.pruef_kommentar = update.pruef_kommentar

    await db.commit()
    await db.refresh(fundstelle)
    return fundstelle
