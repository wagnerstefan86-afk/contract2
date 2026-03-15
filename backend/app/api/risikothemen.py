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
from app.schemas.risikothema import (
    RisikoThemaResponse,
    FinalEditorialResponse,
    FinalesThemaResponse,
    FinalesThemaFundstelleResponse,
    VerworfenesThemaResponse,
)
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


@router.get("/vertrag/{vertrag_id}/final", response_model=FinalEditorialResponse)
async def finale_themen_fuer_vertrag(
    vertrag_id: uuid.UUID,
    user: Benutzer = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the final editorial pass result — reduced core themes for reviewers."""
    result = await db.execute(
        select(RisikoThema)
        .where(RisikoThema.vertrag_id == vertrag_id)
        .options(selectinload(RisikoThema.fundstellen))
        .order_by(RisikoThema.sortierung)
    )
    alle_themen = list(result.scalars().all())

    # Check if editorial pass has run (at least one theme has final_selected=True)
    hat_editorial = any(t.final_selected for t in alle_themen)

    finale_themen: list[FinalesThemaResponse] = []
    verworfene: list[VerworfenesThemaResponse] = []

    if hat_editorial:
        for thema in alle_themen:
            if thema.final_selected and thema.final_editorial:
                ed = thema.final_editorial
                prim_id = ed.get("primaerfundstelle_id")
                sek_ids = set(ed.get("sekundaerfundstelle_ids", []))

                # Build filtered fundstellen list (primary + secondary only)
                fundstellen_out = []
                for fs in thema.fundstellen:
                    fs_id_str = str(fs.id)
                    if fs_id_str == prim_id or fs_id_str in sek_ids:
                        fundstellen_out.append(FinalesThemaFundstelleResponse(
                            id=fs.id,
                            kurzbeschreibung=fs.kurzbeschreibung,
                            kategorie=fs.kategorie,
                            risikostufe=fs.risikostufe,
                            textstelle=fs.textstelle,
                            pruef_status=fs.pruef_status,
                            ist_primaer=(fs_id_str == prim_id),
                            scope_type=getattr(fs, "scope_type", None),
                            scope_text=getattr(fs, "scope_text", None),
                            trigger_spans=getattr(fs, "trigger_spans", None),
                            evidence_heading_path=getattr(fs, "evidence_heading_path", None),
                        ))

                # If no fundstellen matched (edge case), include all but cap at 3
                if not fundstellen_out:
                    for fs in thema.fundstellen[:3]:
                        fundstellen_out.append(FinalesThemaFundstelleResponse(
                            id=fs.id,
                            kurzbeschreibung=fs.kurzbeschreibung,
                            kategorie=fs.kategorie,
                            risikostufe=fs.risikostufe,
                            textstelle=fs.textstelle,
                            pruef_status=fs.pruef_status,
                            ist_primaer=(len(fundstellen_out) == 0),
                            scope_type=getattr(fs, "scope_type", None),
                            scope_text=getattr(fs, "scope_text", None),
                            trigger_spans=getattr(fs, "trigger_spans", None),
                            evidence_heading_path=getattr(fs, "evidence_heading_path", None),
                        ))

                # Sort: primary first
                fundstellen_out.sort(key=lambda f: (not f.ist_primaer, str(f.id)))

                finale_themen.append(FinalesThemaResponse(
                    id=thema.id,
                    titel=thema.titel,
                    kategorie=thema.kategorie,
                    risikostufe=thema.risikostufe,
                    kurzbeschreibung=ed.get("kurzbeschreibung", thema.beschreibung),
                    warum_verhandlungsrelevant=ed.get("warum_verhandlungsrelevant", ""),
                    alternativformulierung=ed.get("alternativformulierung", ""),
                    bieterfrage=ed.get("bieterfrage", ""),
                    verhandlungsargumente=ed.get("verhandlungsargumente", []),
                    fundstellen=fundstellen_out,
                    sortierung=thema.sortierung,
                ))
            elif not thema.final_selected:
                verworfene.append(VerworfenesThemaResponse(
                    id=thema.id,
                    titel=thema.titel,
                    kategorie=thema.kategorie,
                    grund=thema.final_verwerfungsgrund or "Kein eigenständiger Risikokern",
                ))

    metriken = {
        "anzahl_cluster_themen_vorher": len(alle_themen),
        "anzahl_finale_themen_nachher": len(finale_themen),
        "anzahl_verworfene_themen": len(verworfene),
        "hat_editorial": hat_editorial,
        "anzahl_ausgewaehlte_evidenzen": sum(len(ft.fundstellen) for ft in finale_themen),
    }

    return FinalEditorialResponse(
        finale_themen=finale_themen,
        verworfene_themen=verworfene,
        metriken=metriken,
    )


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
