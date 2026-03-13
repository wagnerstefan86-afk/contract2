import asyncio
import uuid
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, async_session
from app.models.analyse import Analyse
from app.models.fundstelle import Fundstelle
from app.models.vertrag import Vertrag
from app.schemas.analyse import AnalyseResponse
from app.discovery.orchestrator import run_discovery
from app.evaluation.evaluator import evaluiere

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


@router.get("/{analyse_id}/auswertung")
async def analyse_auswertung(analyse_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Debug/evaluation endpoint: full pipeline observability for one analysis run.

    Returns pass-level stats, consolidation mapping, category/risk distribution,
    timing, and per-finding merge provenance.
    """
    analyse = await db.get(Analyse, analyse_id)
    if not analyse:
        raise HTTPException(status_code=404, detail="Analyse nicht gefunden")

    # Load all findings for this analysis
    result = await db.execute(
        select(Fundstelle).where(Fundstelle.analyse_id == analyse_id)
    )
    fundstellen = result.scalars().all()

    # Build per-finding debug info
    fundstellen_debug = []
    for f in fundstellen:
        fundstellen_debug.append({
            "id": str(f.id),
            "kurzbeschreibung": f.kurzbeschreibung,
            "kategorie": f.kategorie,
            "risikostufe": f.risikostufe,
            "quelle_pass": f.quelle_pass,
            "textstelle": f.textstelle,
            "erklaerung": f.erklaerung,
            "empfehlung": f.empfehlung,
            "segment_ids": f.absatz_ids,
            "zusammenfuehrung": f.zusammenfuehrung,
        })

    # Source pass distribution from final findings
    quellen = Counter()
    for f in fundstellen:
        if f.quelle_pass:
            for part in f.quelle_pass.split(", "):
                quellen[part.strip()] += 1

    return {
        "analyse_id": str(analyse.id),
        "status": analyse.status,
        "pipeline_auswertung": analyse.auswertung,
        "fundstellen_gesamt": len(fundstellen),
        "quellen_verteilung_final": dict(quellen),
        "kategorien_final": dict(Counter(f.kategorie for f in fundstellen)),
        "risikostufen_final": dict(Counter(f.risikostufe for f in fundstellen)),
        "fundstellen_detail": fundstellen_debug,
    }


@router.get("/{analyse_id}/erwartungspruefung")
async def analyse_erwartungspruefung(analyse_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Evaluate pipeline findings against curated expected themes for the demo contract.

    Returns per-theme match status, recall quote, and unmatched extras.
    """
    analyse = await db.get(Analyse, analyse_id)
    if not analyse:
        raise HTTPException(status_code=404, detail="Analyse nicht gefunden")

    result = await db.execute(
        select(Fundstelle).where(Fundstelle.analyse_id == analyse_id)
    )
    fundstellen = result.scalars().all()

    fundstellen_dicts = [
        {
            "id": str(f.id),
            "kurzbeschreibung": f.kurzbeschreibung,
            "kategorie": f.kategorie,
            "risikostufe": f.risikostufe,
            "quelle_pass": f.quelle_pass,
            "textstelle": f.textstelle,
            "erklaerung": f.erklaerung,
            "empfehlung": f.empfehlung,
        }
        for f in fundstellen
    ]

    ergebnis = evaluiere(fundstellen_dicts)
    return ergebnis.to_dict()


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
