"""API endpoints for RisikoThema (LLM-generated topic clusters)."""

import uuid
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import get_current_user
from app.models.benutzer import Benutzer
from app.models.fundstelle import Fundstelle
from app.models.risikothema import RisikoThema
from app.schemas.risikothema import RisikoThemaResponse
from app.discovery.passes.themen_cluster import berechne_titel_aehnlichkeit

router = APIRouter(prefix="/risikothemen", tags=["Risikothemen"])


@router.get("/vertrag/{vertrag_id}", response_model=list[RisikoThemaResponse])
async def risikothemen_fuer_vertrag(
    vertrag_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all risk topics for a contract, with nested findings."""
    result = await db.execute(
        select(RisikoThema)
        .where(RisikoThema.vertrag_id == vertrag_id)
        .options(selectinload(RisikoThema.fundstellen))
        .order_by(RisikoThema.sortierung)
    )
    return result.scalars().all()


@router.get("/vertrag/{vertrag_id}/debug")
async def risikothemen_debug(
    vertrag_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Debug view: quality metrics, warnings, and similarity analysis."""
    # Load all topics with their findings
    result = await db.execute(
        select(RisikoThema)
        .where(RisikoThema.vertrag_id == vertrag_id)
        .options(selectinload(RisikoThema.fundstellen))
        .order_by(RisikoThema.sortierung)
    )
    themen = result.scalars().all()

    if not themen:
        return {"themen": [], "metriken": {}, "warnungen": [], "aehnliche_themen": []}

    # Count total individual findings for this contract
    fs_count_result = await db.execute(
        select(Fundstelle.id).where(Fundstelle.vertrag_id == vertrag_id)
    )
    anzahl_einzelfindings = len(fs_count_result.all())

    # Build per-topic debug info and collect warnings
    warnungen: list[dict] = []
    themen_debug = []
    fundstelle_themen_map: Counter = Counter()  # fundstelle_id -> how many topics

    for thema in themen:
        fs_list = [
            {
                "id": str(f.id),
                "kurzbeschreibung": f.kurzbeschreibung,
                "kategorie": f.kategorie,
                "risikostufe": f.risikostufe,
            }
            for f in thema.fundstellen
        ]
        for f in thema.fundstellen:
            fundstelle_themen_map[str(f.id)] += 1

        themen_debug.append({
            "id": str(thema.id),
            "titel": thema.titel,
            "kategorie": thema.kategorie,
            "risikostufe": thema.risikostufe,
            "anzahl_evidence": len(fs_list),
            "fundstellen": fs_list,
        })

        if len(thema.fundstellen) == 1:
            warnungen.append({
                "typ": "einzelne_fundstelle",
                "thema": thema.titel,
                "nachricht": f"Thema '{thema.titel}' hat nur 1 Fundstelle.",
            })

    # Check for evidence in multiple topics
    for fs_id, count in fundstelle_themen_map.items():
        if count > 1:
            warnungen.append({
                "typ": "mehrfach_zugeordnet",
                "fundstelle_id": fs_id,
                "nachricht": f"Fundstelle {fs_id[:8]}... ist {count} Themen zugeordnet.",
                "anzahl_themen": count,
            })

    # Pairwise title similarity
    titel_liste = [t.titel for t in themen]
    aehnliche_themen = berechne_titel_aehnlichkeit(titel_liste)
    for pair in aehnliche_themen:
        warnungen.append({
            "typ": "aehnliche_titel",
            "thema_a": pair["thema_a"],
            "thema_b": pair["thema_b"],
            "nachricht": (
                f"Themen '{pair['thema_a']}' und '{pair['thema_b']}' "
                f"sind zu {int(pair['aehnlichkeit'] * 100)}% ähnlich — Merge-Kandidat?"
            ),
            "aehnlichkeit": pair["aehnlichkeit"],
        })

    # Compute metrics
    evidence_counts = [len(t.fundstellen) for t in themen]
    total_evidence = sum(evidence_counts)
    anzahl_themen = len(themen)
    mehrfach = sum(1 for c in fundstelle_themen_map.values() if c > 1)

    metriken = {
        "anzahl_einzelfindings": anzahl_einzelfindings,
        "anzahl_risikothemen": anzahl_themen,
        "durchschnittliche_fundstellen_pro_thema": round(total_evidence / anzahl_themen, 1) if anzahl_themen else 0,
        "anzahl_themen_ohne_evidence": sum(1 for c in evidence_counts if c == 0),
        "anzahl_evidence_mehrfach_zugeordnet": mehrfach,
        "anzahl_themen_mit_nur_1_fundstelle": sum(1 for c in evidence_counts if c == 1),
    }

    return {
        "themen": themen_debug,
        "metriken": metriken,
        "warnungen": warnungen,
        "aehnliche_themen": aehnliche_themen,
    }
