import os
import uuid
import shutil
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.models.vertrag import Vertrag, VertragStatus
from app.schemas.vertrag import VertragResponse, VertragDetail

router = APIRouter(prefix="/vertraege", tags=["Verträge"])


@router.get("", response_model=list[VertragResponse])
async def liste_vertraege(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Vertrag).order_by(Vertrag.erstellt_am.desc()))
    return result.scalars().all()


@router.get("/{vertrag_id}", response_model=VertragDetail)
async def vertrag_detail(vertrag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    vertrag = await db.get(Vertrag, vertrag_id)
    if not vertrag:
        raise HTTPException(status_code=404, detail="Vertrag nicht gefunden")
    return vertrag


@router.post("", response_model=VertragResponse, status_code=201)
async def vertrag_hochladen(datei: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    upload_dir = settings.upload_dir
    os.makedirs(upload_dir, exist_ok=True)

    file_id = str(uuid.uuid4())
    ext = os.path.splitext(datei.filename or "upload")[1]
    dateipfad = os.path.join(upload_dir, f"{file_id}{ext}")

    with open(dateipfad, "wb") as f:
        shutil.copyfileobj(datei.file, f)

    vertrag = Vertrag(
        dateiname=datei.filename or "unbekannt",
        dateipfad=dateipfad,
        status=VertragStatus.HOCHGELADEN.value,
    )
    db.add(vertrag)
    await db.commit()
    await db.refresh(vertrag)
    return vertrag


@router.delete("/{vertrag_id}", status_code=204)
async def vertrag_loeschen(vertrag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    vertrag = await db.get(Vertrag, vertrag_id)
    if not vertrag:
        raise HTTPException(status_code=404, detail="Vertrag nicht gefunden")

    if vertrag.dateipfad and os.path.exists(vertrag.dateipfad):
        os.remove(vertrag.dateipfad)

    await db.delete(vertrag)
    await db.commit()
