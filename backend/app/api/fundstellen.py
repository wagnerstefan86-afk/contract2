import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth import get_current_user
from app.models.benutzer import Benutzer
from app.models.fundstelle import Fundstelle
from app.schemas.fundstelle import FundstelleResponse, FundstelleUpdate
from app.discovery.gruppierung import gruppiere_fundstellen

router = APIRouter(prefix="/fundstellen", tags=["Fundstellen"])


def _fundstelle_to_dict(f: Fundstelle) -> dict:
    """Convert ORM Fundstelle to dict for grouping logic."""
    return {
        "id": str(f.id),
        "analyse_id": str(f.analyse_id),
        "vertrag_id": str(f.vertrag_id),
        "textstelle": f.textstelle,
        "absatz_ids": f.absatz_ids,
        "kategorie": f.kategorie,
        "risikostufe": f.risikostufe,
        "kurzbeschreibung": f.kurzbeschreibung,
        "erklaerung": f.erklaerung,
        "empfehlung": f.empfehlung,
        "quelle_pass": f.quelle_pass,
        "pruef_status": f.pruef_status,
        "pruef_kommentar": f.pruef_kommentar,
        "erstellt_am": f.erstellt_am.isoformat() if f.erstellt_am else None,
        "detail": f.detail if hasattr(f, 'detail') else None,
        "zusammenfuehrung": f.zusammenfuehrung,
    }


@router.get("/vertrag/{vertrag_id}", response_model=list[FundstelleResponse])
async def fundstellen_fuer_vertrag(vertrag_id: uuid.UUID, user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Fundstelle).where(Fundstelle.vertrag_id == vertrag_id).order_by(Fundstelle.erstellt_am.desc())
    )
    return result.scalars().all()


@router.get("/vertrag/{vertrag_id}/gruppiert")
async def fundstellen_gruppiert(vertrag_id: uuid.UUID, user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return findings grouped into thematic clusters for reviewer-friendly display."""
    result = await db.execute(
        select(Fundstelle).where(Fundstelle.vertrag_id == vertrag_id).order_by(Fundstelle.erstellt_am.desc())
    )
    rows = result.scalars().all()
    return gruppiere_fundstellen([_fundstelle_to_dict(f) for f in rows])


@router.get("/offen", response_model=list[FundstelleResponse])
async def offene_fundstellen(user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Fundstelle).where(Fundstelle.pruef_status == "Offen").order_by(Fundstelle.erstellt_am.desc())
    )
    return result.scalars().all()


@router.get("/offen/gruppiert")
async def offene_fundstellen_gruppiert(user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return open findings grouped into thematic clusters."""
    result = await db.execute(
        select(Fundstelle).where(Fundstelle.pruef_status == "Offen").order_by(Fundstelle.erstellt_am.desc())
    )
    rows = result.scalars().all()
    return gruppiere_fundstellen([_fundstelle_to_dict(f) for f in rows])


@router.get("/{fundstelle_id}", response_model=FundstelleResponse)
async def fundstelle_detail(fundstelle_id: uuid.UUID, user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    fundstelle = await db.get(Fundstelle, fundstelle_id)
    if not fundstelle:
        raise HTTPException(status_code=404, detail="Fundstelle nicht gefunden")
    return fundstelle


@router.patch("/{fundstelle_id}", response_model=FundstelleResponse)
async def fundstelle_bewerten(fundstelle_id: uuid.UUID, update: FundstelleUpdate, user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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
