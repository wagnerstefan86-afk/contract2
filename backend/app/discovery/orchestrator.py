"""Discovery orchestrator: runs the full multi-pass pipeline.

Reads contract text, segments it, runs passes sequentially, consolidates,
and persists findings + protocol entries to the database.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vertrag import Vertrag, VertragStatus
from app.models.analyse import Analyse, AnalyseStatus
from app.models.fundstelle import Fundstelle, PruefStatus
from app.models.protokoll import Protokoll, ProtokollEbene
from app.services.extraktion import text_aus_datei, normalisiere_text
from app.discovery.chunking import text_in_absaetze, absaetze_zu_segmente
from app.discovery.llm_client import lade_llm_config, LLMConfig
from app.discovery.passes.breit import BreitPass
from app.discovery.passes.perspektive import PerspektivePass
from app.discovery.passes.implizit import ImplizitPass
from app.discovery.consolidation import konsolidiere
from app.discovery.passes.base import RawFinding

logger = logging.getLogger(__name__)


async def _log(db: AsyncSession, analyse_id: uuid.UUID, vertrag_id: uuid.UUID,
               nachricht: str, ebene: str = ProtokollEbene.INFO.value,
               details: dict | None = None) -> None:
    """Write a protocol entry."""
    entry = Protokoll(
        analyse_id=analyse_id,
        vertrag_id=vertrag_id,
        ebene=ebene,
        nachricht=nachricht,
        details=details,
    )
    db.add(entry)
    await db.flush()


async def _update_analyse(db: AsyncSession, analyse: Analyse,
                          status: str, pass_name: str = "",
                          fortschritt: int = 0) -> None:
    """Update analysis status and progress."""
    analyse.status = status
    analyse.aktueller_pass = pass_name or None
    analyse.fortschritt = fortschritt
    await db.flush()


async def run_discovery(analyse_id: uuid.UUID, db: AsyncSession) -> None:
    """Run the full discovery pipeline for one analysis.

    This is the main entry point called by the background task.
    It manages its own commits and error handling.
    """
    analyse = await db.get(Analyse, analyse_id)
    if not analyse:
        logger.error(f"Analyse {analyse_id} nicht gefunden")
        return

    vertrag = await db.get(Vertrag, analyse.vertrag_id)
    if not vertrag:
        logger.error(f"Vertrag für Analyse {analyse_id} nicht gefunden")
        return

    try:
        await _run_pipeline(db, analyse, vertrag)
    except Exception as e:
        logger.exception(f"Discovery-Pipeline fehlgeschlagen: {e}")
        analyse.status = AnalyseStatus.FEHLGESCHLAGEN.value
        analyse.fehler = str(e)
        analyse.beendet_am = datetime.utcnow()
        await _log(db, analyse.id, vertrag.id,
                   f"Pipeline fehlgeschlagen: {e}",
                   ebene=ProtokollEbene.FEHLER.value,
                   details={"traceback": traceback.format_exc()})
        await db.commit()


async def _run_pipeline(db: AsyncSession, analyse: Analyse, vertrag: Vertrag) -> None:
    """Inner pipeline logic."""

    vid = vertrag.id
    aid = analyse.id

    # --- Step 1: Text extraction ---
    await _update_analyse(db, analyse, AnalyseStatus.GESTARTET.value, "Textextraktion", 5)
    await _log(db, aid, vid, "Analyse gestartet. Textextraktion beginnt.")
    await db.commit()

    if vertrag.volltext:
        full_text = vertrag.volltext
        await _log(db, aid, vid, "Volltext bereits vorhanden, überspringe Extraktion.")
    else:
        try:
            full_text = text_aus_datei(vertrag.dateipfad)
            vertrag.volltext = full_text
            vertrag.status = VertragStatus.EXTRAHIERT.value
            await _log(db, aid, vid,
                       f"Text extrahiert: {len(full_text)} Zeichen aus {vertrag.dateiname}")
        except Exception as e:
            await _log(db, aid, vid,
                       f"Textextraktion fehlgeschlagen: {e}",
                       ebene=ProtokollEbene.FEHLER.value)
            raise ValueError(f"Textextraktion fehlgeschlagen: {e}") from e

    if not full_text or len(full_text.strip()) < 50:
        raise ValueError("Vertrag enthält zu wenig Text für eine Analyse.")

    await db.commit()

    # --- Step 2: Segmentation ---
    await _log(db, aid, vid, "Segmentierung beginnt.")
    absaetze = text_in_absaetze(full_text)
    vertrag.absaetze = absaetze
    segments = absaetze_zu_segmente(absaetze)
    await _log(db, aid, vid,
               f"Segmentierung abgeschlossen: {len(absaetze)} Absätze, {len(segments)} Segmente.")
    await db.commit()

    # --- Step 3: Load LLM config ---
    try:
        llm_config = await lade_llm_config(db)
        analyse.konfig_snapshot = {
            "provider": llm_config.provider,
            "model": llm_config.model,
            "base_url": llm_config.base_url,
        }
        await _log(db, aid, vid,
                   f"LLM-Konfiguration geladen: {llm_config.provider}/{llm_config.model}")
        await db.commit()
    except ValueError as e:
        raise ValueError(str(e)) from e

    # Update contract status
    vertrag.status = VertragStatus.IN_ANALYSE.value
    await db.commit()

    # --- Step 4: Discovery passes ---
    all_raw_findings: list[RawFinding] = []

    # Pass 1: Breite Ersterfassung
    await _update_analyse(db, analyse, AnalyseStatus.PASS_1.value, "Breite Ersterfassung", 15)
    await _log(db, aid, vid, "Pass 1: Breite Ersterfassung gestartet.")
    await db.commit()

    pass1 = BreitPass()
    findings_p1 = await pass1.run(segments, llm_config, full_text)
    await _log(db, aid, vid,
               f"Pass 1 abgeschlossen: {len(findings_p1)} Kandidaten gefunden.")
    all_raw_findings.extend(findings_p1)
    await db.commit()

    # Pass 2: Perspektivische Vertiefung
    await _update_analyse(db, analyse, AnalyseStatus.PASS_2.value, "Perspektivische Vertiefung", 35)
    await _log(db, aid, vid, "Pass 2: Perspektivische Vertiefung gestartet (5 Perspektiven).")
    await db.commit()

    pass2 = PerspektivePass()
    findings_p2 = await pass2.run(segments, llm_config, full_text)
    await _log(db, aid, vid,
               f"Pass 2 abgeschlossen: {len(findings_p2)} zusätzliche Kandidaten.")
    all_raw_findings.extend(findings_p2)
    await db.commit()

    # Pass 3: Implizite Pflichten
    await _update_analyse(db, analyse, AnalyseStatus.PASS_3.value, "Implizite Pflichten", 70)
    await _log(db, aid, vid, "Pass 3: Implizite Pflichten gestartet.")
    await db.commit()

    pass3 = ImplizitPass()
    findings_p3 = await pass3.run(segments, llm_config, full_text)
    await _log(db, aid, vid,
               f"Pass 3 abgeschlossen: {len(findings_p3)} zusätzliche Kandidaten.")
    all_raw_findings.extend(findings_p3)
    await db.commit()

    # --- Step 5: Consolidation ---
    await _update_analyse(db, analyse, AnalyseStatus.KONSOLIDIERUNG.value, "Konsolidierung", 85)
    await _log(db, aid, vid,
               f"Konsolidierung gestartet: {len(all_raw_findings)} Gesamtkandidaten.")
    await db.commit()

    consolidated = konsolidiere(all_raw_findings)
    await _log(db, aid, vid,
               f"Konsolidierung abgeschlossen: {len(consolidated)} Fundstellen nach Deduplizierung.")

    # --- Step 6: Persist findings ---
    for raw in consolidated:
        fundstelle = Fundstelle(
            analyse_id=aid,
            vertrag_id=vid,
            textstelle=raw.textstelle,
            absatz_ids=raw.segment_ids,
            kategorie=raw.kategorie,
            risikostufe=raw.risikostufe,
            kurzbeschreibung=raw.kurzbeschreibung,
            erklaerung=raw.erklaerung,
            empfehlung=raw.empfehlung,
            quelle_pass=raw.quelle_pass,
            pruef_status=PruefStatus.OFFEN.value,
        )
        db.add(fundstelle)

    # --- Step 7: Finalize ---
    analyse.status = AnalyseStatus.ABGESCHLOSSEN.value
    analyse.aktueller_pass = None
    analyse.fortschritt = 100
    analyse.beendet_am = datetime.utcnow()
    vertrag.status = VertragStatus.ANALYSIERT.value

    await _log(db, aid, vid,
               f"Analyse abgeschlossen. {len(consolidated)} Fundstellen gespeichert.",
               details={
                   "pass1_kandidaten": len(findings_p1),
                   "pass2_kandidaten": len(findings_p2),
                   "pass3_kandidaten": len(findings_p3),
                   "gesamt_vor_konsolidierung": len(all_raw_findings),
                   "nach_konsolidierung": len(consolidated),
               })
    await db.commit()
