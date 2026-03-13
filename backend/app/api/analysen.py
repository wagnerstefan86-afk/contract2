import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.models.analyse import Analyse
from app.models.vertrag import Vertrag
from app.schemas.analyse import AnalyseResponse
from app.discovery.orchestrator import run_discovery

router = APIRouter(prefix="/analysen", tags=["Analysen"])


@router.get("/vertrag/{vertrag_id}", response_model=list[AnalyseResponse])
async def analysen_fuer_vertrag(vertrag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Analyse).where(Analyse.vertrag_id == vertrag_id).order_by(Analyse.gestartet_am.desc())
    )
    return result.scalars().all()


@router.get("/{analyse_id}", response_model=AnalyseResponse)
async def analyse_detail(analyse_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    analyse = await db.get(Analyse, analyse_id)
    if not analyse:
        raise HTTPException(status_code=404, detail="Analyse nicht gefunden")
    return analyse


@router.post("/vertrag/{vertrag_id}", response_model=AnalyseResponse, status_code=201)
async def analyse_starten(vertrag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    vertrag = await db.get(Vertrag, vertrag_id)
    if not vertrag:
        raise HTTPException(status_code=404, detail="Vertrag nicht gefunden")

    analyse = Analyse(vertrag_id=vertrag_id)
    db.add(analyse)
    await db.commit()
    await db.refresh(analyse)

    # Launch discovery pipeline as background task with its own DB session
    analyse_id = analyse.id
    asyncio.create_task(_run_discovery_background(analyse_id))

    return analyse


async def _run_discovery_background(analyse_id: uuid.UUID) -> None:
    """Run discovery in background with a fresh DB session."""
    async with async_session() as db:
        await run_discovery(analyse_id, db)
