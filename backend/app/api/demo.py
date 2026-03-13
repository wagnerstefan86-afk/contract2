"""Demo / testing endpoints.

MVP-only: provides a way to seed a demo contract and trigger analysis
without needing file upload infrastructure.
"""

import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.models.vertrag import Vertrag, VertragStatus
from app.models.analyse import Analyse
from app.schemas.analyse import AnalyseResponse
from app.schemas.vertrag import VertragResponse
from app.discovery.orchestrator import run_discovery

router = APIRouter(prefix="/demo", tags=["Demo"])

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "..", "fixtures", "demo_vertrag.txt")


@router.post("/vertrag-anlegen", response_model=VertragResponse, status_code=201)
async def demo_vertrag_anlegen(db: AsyncSession = Depends(get_db)):
    """Seed the demo contract with pre-loaded text. For testing only."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    vertrag = Vertrag(
        dateiname="demo_vertrag.txt",
        dateipfad=FIXTURE_PATH,
        volltext=text,
        status=VertragStatus.EXTRAHIERT.value,
    )
    db.add(vertrag)
    await db.commit()
    await db.refresh(vertrag)
    return vertrag


class PlainTextInput(BaseModel):
    text: str
    dateiname: str = "Freitext-Eingabe"


@router.post("/text-analyse", response_model=AnalyseResponse, status_code=201)
async def text_analyse(eingabe: PlainTextInput, db: AsyncSession = Depends(get_db)):
    """Create a contract from plain text and immediately start analysis.

    MVP convenience endpoint: skips file upload, directly inserts text.
    """
    if len(eingabe.text.strip()) < 50:
        raise HTTPException(status_code=400, detail="Text ist zu kurz für eine Analyse (mind. 50 Zeichen).")

    vertrag = Vertrag(
        dateiname=eingabe.dateiname,
        dateipfad="",
        volltext=eingabe.text,
        status=VertragStatus.EXTRAHIERT.value,
    )
    db.add(vertrag)
    await db.flush()

    analyse = Analyse(vertrag_id=vertrag.id)
    db.add(analyse)
    await db.commit()
    await db.refresh(analyse)

    analyse_id = analyse.id
    asyncio.create_task(_run_bg(analyse_id))

    return analyse


async def _run_bg(analyse_id: uuid.UUID) -> None:
    async with async_session() as db:
        await run_discovery(analyse_id, db)
