import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.auth import get_current_user
from app.models.benutzer import Benutzer
from app.models.analyse import Analyse
from app.models.fundstelle import Fundstelle
from app.models.risikothema import RisikoThema, risikothema_fundstellen
from app.schemas.fundstelle import FundstelleResponse, FundstelleDetailResponse, FundstelleUpdate, ThemaEditorialContext
from app.api.risikothemen import _build_evidences

logger = logging.getLogger(__name__)

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
        # Paragraph-level evidence
        "scope_type": getattr(f, "scope_type", None),
        "scope_text": getattr(f, "scope_text", None),
        "trigger_spans": getattr(f, "trigger_spans", None),
        "evidence_heading_path": getattr(f, "evidence_heading_path", None),
    }


@router.get("/vertrag/{vertrag_id}", response_model=list[FundstelleResponse])
async def fundstellen_fuer_vertrag(vertrag_id: uuid.UUID, user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    fs_ids = await _final_fundstelle_ids(db, vertrag_id=vertrag_id)
    if not fs_ids:
        return []
    result = await db.execute(
        select(Fundstelle)
        .where(Fundstelle.id.in_(fs_ids))
        .order_by(Fundstelle.erstellt_am.desc())
    )
    return result.scalars().all()


def _themen_to_gruppen(themen: list[RisikoThema],
                       only_open: bool = False) -> dict:
    """Build the grouped response from consolidated RisikoThema objects.

    Returns the same shape as the old gruppiere_fundstellen() so the
    frontend works unchanged:
      { gruppen: [...], debug: { vorher, nachher, ... } }
    """
    _RISK_ORDER = {"Kritisch": 0, "Hoch": 1, "Mittel": 2, "Niedrig": 3, "Hinweis": 4}
    gruppen = []
    total_fundstellen = 0

    for idx, thema in enumerate(themen):
        fs_list = thema.fundstellen
        if only_open:
            fs_list = [f for f in fs_list if f.pruef_status == "Offen"]
        if not fs_list:
            continue

        total_fundstellen += len(fs_list)

        # Build evidence items for the expanded view
        evidences = _build_evidences(fs_list)

        gruppen.append({
            "gruppe_id": f"thema-{idx}",
            "titel": thema.titel,
            "kategorie": thema.kategorie,
            "risikostufe": thema.risikostufe,
            "zusammenfassung": (
                thema.final_editorial.get("kurzbeschreibung", thema.beschreibung)
                if thema.final_editorial
                else thema.beschreibung
            ),
            "anzahl": len(fs_list),
            "fundstellen_ids": [str(f.id) for f in fs_list],
            "fundstellen": [_fundstelle_to_dict(f) for f in fs_list],
            "themen_familie": thema.kategorie,
            "evidences": [
                {
                    "scope_text": e.scope_text,
                    "segment_id": e.segment_id,
                    "heading_path": e.heading_path,
                    "trigger_spans": e.trigger_spans,
                }
                for e in evidences
            ],
        })

    # Sort by risk level, then by count descending
    gruppen.sort(key=lambda g: (_RISK_ORDER.get(g["risikostufe"], 9), -g["anzahl"]))

    return {
        "gruppen": gruppen,
        "debug": {
            "vorher": total_fundstellen,
            "nachher": len(gruppen),
            "reduktion_prozent": round(
                (1 - len(gruppen) / total_fundstellen) * 100, 1
            ) if total_fundstellen else 0,
            "gruppen_details": [],
            "quelle": "consolidated_themes",
            "themes_total": len(themen),
            "themes_with_evidence": len(gruppen),
            "themes_dropped_no_evidence": len(themen) - len(gruppen),
        },
    }


async def _latest_analyse_ids(db: AsyncSession,
                              vertrag_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """Find the latest analyse_id per contract.

    Multiple pipeline runs on the same contract create separate Analyse rows,
    each with their own RisikoThema set. We only want themes from the most
    recent run per contract.
    """
    # Subquery: max(gestartet_am) per vertrag_id
    sub = (
        select(
            Analyse.vertrag_id,
            func.max(Analyse.gestartet_am).label("latest"),
        )
        .group_by(Analyse.vertrag_id)
    )
    if vertrag_id:
        sub = sub.where(Analyse.vertrag_id == vertrag_id)
    sub = sub.subquery()

    # Join to get the actual analyse IDs matching the max timestamp
    q = (
        select(Analyse.id)
        .join(sub, (Analyse.vertrag_id == sub.c.vertrag_id) & (Analyse.gestartet_am == sub.c.latest))
    )
    result = await db.execute(q)
    return [row[0] for row in result.all()]


async def _final_fundstelle_ids(db: AsyncSession,
                                vertrag_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """Return Fundstelle IDs that belong to final-selected RisikoThema
    from the latest analysis per contract.

    This is the single source of truth for which raw findings are
    'user-relevant' — only those linked to editorial-surviving themes.
    """
    analyse_ids = await _latest_analyse_ids(db, vertrag_id=vertrag_id)
    if not analyse_ids:
        return []

    q = (
        select(risikothema_fundstellen.c.fundstelle_id)
        .join(RisikoThema, RisikoThema.id == risikothema_fundstellen.c.risikothema_id)
        .where(RisikoThema.analyse_id.in_(analyse_ids))
        .where(RisikoThema.final_selected.is_(True))
    )
    if vertrag_id:
        q = q.where(RisikoThema.vertrag_id == vertrag_id)

    result = await db.execute(q)
    return list({row[0] for row in result.all()})


async def _load_final_themen(db: AsyncSession,
                             vertrag_id: uuid.UUID | None = None) -> list[RisikoThema]:
    """Load final-selected themes from the latest analysis per contract.

    Only includes themes from the most recent pipeline run to avoid
    duplicates from repeated analyses on the same contract.
    """
    analyse_ids = await _latest_analyse_ids(db, vertrag_id=vertrag_id)
    if not analyse_ids:
        return []

    q = (
        select(RisikoThema)
        .where(RisikoThema.analyse_id.in_(analyse_ids))
        .options(selectinload(RisikoThema.fundstellen))
        .order_by(RisikoThema.sortierung)
    )

    result = await db.execute(q)
    alle = list(result.scalars().all())

    # Prefer final_selected themes (editorial pass output).
    # LEGACY SAFETY NET: The pipeline now enforces deterministic evidence linkage
    # and drops themes without evidence before persistence. This API-level filter
    # guards against data from older pipeline runs that may still contain
    # zero-evidence final themes. It is NOT the primary correctness mechanism.
    final = [t for t in alle if t.final_selected and len(t.fundstellen) > 0]
    if final:
        return final
    # Fallback: no final themes with evidence — return all themes that have evidence
    return [t for t in alle if len(t.fundstellen) > 0]


@router.get("/vertrag/{vertrag_id}/gruppiert")
async def fundstellen_gruppiert(vertrag_id: uuid.UUID, user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return findings grouped by consolidated themes for reviewer-friendly display."""
    themen = await _load_final_themen(db, vertrag_id=vertrag_id)
    if themen:
        return _themen_to_gruppen(themen, only_open=False)
    # Fallback: no themes exist yet (analysis not complete)
    analyse_ids = await _latest_analyse_ids(db, vertrag_id=vertrag_id)
    q = select(Fundstelle).where(Fundstelle.vertrag_id == vertrag_id).order_by(Fundstelle.erstellt_am.desc())
    if analyse_ids:
        q = q.where(Fundstelle.analyse_id.in_(analyse_ids))
    result = await db.execute(q)
    rows = result.scalars().all()
    return {
        "gruppen": [{
            "gruppe_id": "ungrouped",
            "titel": "Ungegruppierte Fundstellen",
            "kategorie": "",
            "risikostufe": "Mittel",
            "zusammenfassung": "Themen-Clustering noch nicht abgeschlossen.",
            "anzahl": len(rows),
            "fundstellen_ids": [str(f.id) for f in rows],
            "fundstellen": [_fundstelle_to_dict(f) for f in rows],
            "themen_familie": None,
            "evidences": [],
        }] if rows else [],
        "debug": {"vorher": len(rows), "nachher": 1 if rows else 0, "reduktion_prozent": 0, "gruppen_details": [], "quelle": "fallback_ungrouped"},
    }


@router.get("/offen", response_model=list[FundstelleResponse])
async def offene_fundstellen(user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    fs_ids = await _final_fundstelle_ids(db)
    if not fs_ids:
        return []
    result = await db.execute(
        select(Fundstelle)
        .where(Fundstelle.pruef_status == "Offen")
        .where(Fundstelle.id.in_(fs_ids))
        .order_by(Fundstelle.erstellt_am.desc())
    )
    return result.scalars().all()


@router.get("/offen/gruppiert")
async def offene_fundstellen_gruppiert(user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Return open findings grouped by consolidated themes."""
    themen = await _load_final_themen(db, vertrag_id=None)
    if themen:
        return _themen_to_gruppen(themen, only_open=True)
    # Fallback: no themes at all
    return {"gruppen": [], "debug": {"vorher": 0, "nachher": 0, "reduktion_prozent": 0, "gruppen_details": [], "quelle": "no_themes"}}


@router.get("/{fundstelle_id}", response_model=FundstelleDetailResponse)
async def fundstelle_detail(fundstelle_id: uuid.UUID, user: Benutzer = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    fundstelle = await db.get(Fundstelle, fundstelle_id)
    if not fundstelle:
        raise HTTPException(status_code=404, detail="Fundstelle nicht gefunden")

    thema_editorial = await _build_thema_editorial(fundstelle, db)

    resp = FundstelleDetailResponse.model_validate(fundstelle)
    resp.thema_editorial = thema_editorial
    return resp


async def _build_thema_editorial(fundstelle: Fundstelle, db: AsyncSession) -> ThemaEditorialContext:
    """Build ThemaEditorialContext with fallback mapping.

    Resolution strategy:
    1. Try final_selected theme with editorial JSONB
    2. Try any linked (non-final) theme
    3. Build minimal editorial from fundstelle's own fields

    Within each level, map old fields → new structured fields when new ones are empty:
    - recommendation[] ← alternativformulierung, empfehlung
    - negotiation[] ← verhandlungsargumente, bieterfrage
    - problem_summary ← kurzbeschreibung
    """
    fundstelle_id = fundstelle.id
    field_sources: dict[str, str] = {}

    # --- Strategy 1: Final-selected theme ---
    result = await db.execute(
        select(RisikoThema)
        .join(risikothema_fundstellen, RisikoThema.id == risikothema_fundstellen.c.risikothema_id)
        .where(risikothema_fundstellen.c.fundstelle_id == fundstelle_id)
        .where(RisikoThema.final_selected.is_(True))
        .limit(1)
    )
    thema = result.scalar_one_or_none()

    # --- Strategy 2: Any linked theme (non-final) ---
    if not thema:
        result = await db.execute(
            select(RisikoThema)
            .join(risikothema_fundstellen, RisikoThema.id == risikothema_fundstellen.c.risikothema_id)
            .where(risikothema_fundstellen.c.fundstelle_id == fundstelle_id)
            .limit(1)
        )
        thema = result.scalar_one_or_none()
        if thema:
            field_sources["theme_type"] = "non-final linked theme"

    if thema:
        ed = thema.final_editorial or {}
        if not field_sources.get("theme_type"):
            field_sources["theme_type"] = "final_selected theme"

        # --- Title: always from theme ---
        titel = thema.titel or ""
        field_sources["titel"] = f"thema.titel='{titel[:40]}'"

        # --- Kurzbeschreibung ---
        kurzbeschreibung = ed.get("kurzbeschreibung") or thema.beschreibung or fundstelle.kurzbeschreibung or ""
        field_sources["kurzbeschreibung"] = (
            "ed.kurzbeschreibung" if ed.get("kurzbeschreibung")
            else "thema.beschreibung" if thema.beschreibung
            else "fundstelle.kurzbeschreibung"
        )

        # --- Problem summary: fallback to kurzbeschreibung ---
        problem_summary = ed.get("problem_summary") or ""
        if not problem_summary:
            problem_summary = kurzbeschreibung
            field_sources["problem_summary"] = "FALLBACK→kurzbeschreibung"
        else:
            field_sources["problem_summary"] = "ed.problem_summary"

        # --- Impact ---
        impact = ed.get("impact", [])
        field_sources["impact"] = f"ed.impact[{len(impact)}]"

        # --- Recommendation: fallback to old fields ---
        recommendation = ed.get("recommendation", [])
        if recommendation:
            field_sources["recommendation"] = f"ed.recommendation[{len(recommendation)}]"
        else:
            recommendation = _synthesize_recommendation(ed, fundstelle)
            field_sources["recommendation"] = f"SYNTHESIZED[{len(recommendation)}] from alternativformulierung/empfehlung"

        # --- Negotiation: fallback to old fields ---
        negotiation = ed.get("negotiation", [])
        if negotiation:
            field_sources["negotiation"] = f"ed.negotiation[{len(negotiation)}]"
        else:
            negotiation = _synthesize_negotiation(ed, fundstelle)
            field_sources["negotiation"] = f"SYNTHESIZED[{len(negotiation)}] from verhandlungsargumente/bieterfrage"

        # --- Remaining old fields (pass through) ---
        warum = ed.get("warum_verhandlungsrelevant", "")
        alternativ = ed.get("alternativformulierung", "")
        bieterfrage = ed.get("bieterfrage", "")
        verhandlungsargs = ed.get("verhandlungsargumente", [])

        logger.info(
            "[editorial-debug] fundstelle=%s thema=%s sources=%s",
            fundstelle_id, thema.id, field_sources,
        )

        return ThemaEditorialContext(
            thema_id=thema.id,
            titel=titel,
            kategorie=thema.kategorie or fundstelle.kategorie or "",
            risikostufe=thema.risikostufe or fundstelle.risikostufe or "Mittel",
            kurzbeschreibung=kurzbeschreibung,
            problem_summary=problem_summary,
            impact=impact,
            recommendation=recommendation,
            negotiation=negotiation,
            warum_verhandlungsrelevant=warum,
            alternativformulierung=alternativ,
            bieterfrage=bieterfrage,
            verhandlungsargumente=verhandlungsargs,
            decision_status=thema.decision_status or "OPEN",
            decision_comment=thema.decision_comment,
            recommendation_override=thema.recommendation_override,
            negotiation_override=thema.negotiation_override,
        )

    # --- Strategy 3: No linked theme at all — build from fundstelle ---
    field_sources["theme_type"] = "NO_THEME (fundstelle-only)"
    detail = fundstelle.detail or {}

    recommendation = _synthesize_recommendation({}, fundstelle)
    negotiation = _synthesize_negotiation_from_detail(detail)
    problem_summary = fundstelle.kurzbeschreibung or ""

    field_sources["recommendation"] = f"FUNDSTELLE[{len(recommendation)}]"
    field_sources["negotiation"] = f"FUNDSTELLE_DETAIL[{len(negotiation)}]"
    field_sources["problem_summary"] = "fundstelle.kurzbeschreibung"

    logger.info(
        "[editorial-debug] fundstelle=%s NO_THEME sources=%s",
        fundstelle_id, field_sources,
    )

    return ThemaEditorialContext(
        thema_id=None,
        titel=_truncate_words(problem_summary, 8),
        kategorie=fundstelle.kategorie or "",
        risikostufe=fundstelle.risikostufe or "Mittel",
        kurzbeschreibung=fundstelle.kurzbeschreibung or "",
        problem_summary=problem_summary,
        impact=[],
        recommendation=recommendation,
        negotiation=negotiation,
        warum_verhandlungsrelevant="",
        alternativformulierung=detail.get("alternativformulierung", ""),
        bieterfrage=detail.get("bieterfrage", ""),
        verhandlungsargumente=(
            [detail["verhandlungsargumente"]] if isinstance(detail.get("verhandlungsargumente"), str) and detail["verhandlungsargumente"]
            else detail.get("verhandlungsargumente", []) if isinstance(detail.get("verhandlungsargumente"), list)
            else []
        ),
        decision_status="OPEN",
        decision_comment=None,
        recommendation_override=None,
        negotiation_override=None,
    )


def _synthesize_recommendation(ed: dict, fundstelle: Fundstelle) -> list[str]:
    """Build recommendation[] from old-model fields when new field is empty."""
    items: list[str] = []
    alt = ed.get("alternativformulierung", "")
    if alt:
        items.append(alt)
    if fundstelle.empfehlung:
        items.append(fundstelle.empfehlung)
    return items


def _synthesize_negotiation(ed: dict, fundstelle: Fundstelle) -> list[str]:
    """Build negotiation[] from old-model fields when new field is empty."""
    items: list[str] = []
    verh = ed.get("verhandlungsargumente", [])
    if isinstance(verh, list):
        items.extend(verh)
    elif isinstance(verh, str) and verh:
        items.append(verh)
    bf = ed.get("bieterfrage", "")
    if bf:
        items.append(bf)
    # Also check fundstelle detail
    detail = fundstelle.detail or {}
    if not items:
        dv = detail.get("verhandlungsargumente", "")
        if isinstance(dv, str) and dv:
            items.append(dv)
        elif isinstance(dv, list):
            items.extend(dv)
    return items


def _synthesize_negotiation_from_detail(detail: dict) -> list[str]:
    """Build negotiation[] from fundstelle.detail when no theme exists."""
    items: list[str] = []
    dv = detail.get("verhandlungsargumente", "")
    if isinstance(dv, str) and dv:
        items.append(dv)
    elif isinstance(dv, list):
        items.extend(dv)
    bf = detail.get("bieterfrage", "")
    if bf:
        items.append(bf)
    return items


def _truncate_words(text: str, max_words: int) -> str:
    """Truncate text to max_words."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "…"


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
