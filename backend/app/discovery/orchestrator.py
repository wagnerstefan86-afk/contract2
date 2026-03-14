"""Discovery orchestrator: runs the full multi-pass pipeline.

Reads contract text, segments it, runs passes sequentially, consolidates,
and persists findings + protocol entries + evaluation data to the database.
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from collections import Counter
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.vertrag import Vertrag, VertragStatus
from app.models.analyse import Analyse, AnalyseStatus
from app.models.fundstelle import Fundstelle, PruefStatus
from app.models.protokoll import Protokoll, ProtokollEbene
from app.services.extraktion import extrahiere_mit_seitenmap
from app.discovery.chunking import text_in_absaetze, absaetze_zu_segmente
from app.discovery.llm_client import lade_llm_config, LLMConfig
from app.discovery.passes.breit import BreitPass
from app.discovery.passes.perspektive import PerspektivePass
from app.discovery.passes.implizit import ImplizitPass
from app.discovery.passes.bankregulatorik import BankregulatorikPass
from app.discovery.passes.themen_cluster import (
    clustere_findings, resolve_topic_fundstellen,
    berechne_clustering_metriken, berechne_titel_aehnlichkeit,
)
from app.discovery.consolidation import konsolidiere, ConsolidatedFinding
from app.discovery.anreicherung import anreichern
from app.discovery.passes.base import RawFinding
from app.models.risikothema import RisikoThema

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
    """Inner pipeline logic with full observability."""

    vid = vertrag.id
    aid = analyse.id
    pipeline_start = time.monotonic()

    # Accumulates evaluation data for the auswertung field
    auswertung: dict = {"passes": {}, "segmente": {}, "konsolidierung": {}, "zeiten": {}}

    # --- Step 1: Text extraction ---
    await _update_analyse(db, analyse, AnalyseStatus.GESTARTET.value, "Textextraktion", 5)
    await _log(db, aid, vid, "Analyse gestartet. Textextraktion beginnt.")
    await db.commit()

    if vertrag.volltext:
        full_text = vertrag.volltext
        await _log(db, aid, vid, "Volltext bereits vorhanden, überspringe Extraktion.")
    else:
        try:
            ergebnis = extrahiere_mit_seitenmap(vertrag.dateipfad)
            full_text = ergebnis.text
            vertrag.volltext = full_text
            if ergebnis.seiten_map:
                vertrag.seiten_map = ergebnis.seiten_map
            vertrag.status = VertragStatus.EXTRAHIERT.value
            await _log(db, aid, vid,
                       f"Text extrahiert: {len(full_text)} Zeichen, "
                       f"{len(ergebnis.seiten_map)} Seiten aus {vertrag.dateiname}")
        except Exception as e:
            await _log(db, aid, vid,
                       f"Textextraktion fehlgeschlagen: {e}",
                       ebene=ProtokollEbene.FEHLER.value)
            raise ValueError(f"Textextraktion fehlgeschlagen: {e}") from e

    if not full_text or len(full_text.strip()) < 50:
        raise ValueError("Vertrag enthält zu wenig Text für eine Analyse.")

    auswertung["text_laenge"] = len(full_text)
    await db.commit()

    # --- Step 2: Segmentation ---
    await _log(db, aid, vid, "Segmentierung beginnt.")
    absaetze = text_in_absaetze(full_text)
    vertrag.absaetze = absaetze
    segments = absaetze_zu_segmente(absaetze)

    auswertung["segmente"] = {
        "absaetze": len(absaetze),
        "segmente": len(segments),
        "segment_ids": [s.id for s in segments],
    }

    await _log(db, aid, vid,
               f"Segmentierung abgeschlossen: {len(absaetze)} Absätze, {len(segments)} Segmente.",
               details=auswertung["segmente"])
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

    vertrag.status = VertragStatus.IN_ANALYSE.value
    await db.commit()

    # --- Step 4: Discovery passes ---
    all_raw_findings: list[RawFinding] = []
    # Raw findings per pass for debugging/evaluation (serialized to auswertung)
    roh_kandidaten_pro_pass: dict[str, list[dict]] = {}

    # Pass 1: Breite Ersterfassung
    await _update_analyse(db, analyse, AnalyseStatus.PASS_1.value, "Breite Ersterfassung", 15)
    await _log(db, aid, vid, "Pass 1: Breite Ersterfassung gestartet.")
    await db.commit()

    t0 = time.monotonic()
    pass1 = BreitPass()
    findings_p1 = await pass1.run(segments, llm_config, full_text)
    dur_p1 = round(time.monotonic() - t0, 1)

    p1_cats = Counter(f.kategorie for f in findings_p1)
    auswertung["passes"]["pass1_breit"] = {
        "kandidaten": len(findings_p1),
        "dauer_sekunden": dur_p1,
        "kategorien": dict(p1_cats),
    }

    roh_kandidaten_pro_pass["Pass 1: Breite Ersterfassung"] = [
        _raw_finding_to_dict(f) for f in findings_p1
    ]

    await _log(db, aid, vid,
               f"Pass 1 abgeschlossen: {len(findings_p1)} Kandidaten in {dur_p1}s.",
               details=auswertung["passes"]["pass1_breit"])
    all_raw_findings.extend(findings_p1)
    await db.commit()

    # Pass 2: Perspektivische Vertiefung
    await _update_analyse(db, analyse, AnalyseStatus.PASS_2.value, "Perspektivische Vertiefung", 35)
    await _log(db, aid, vid, "Pass 2: Perspektivische Vertiefung gestartet (5 Perspektiven).")
    await db.commit()

    t0 = time.monotonic()
    pass2 = PerspektivePass()
    findings_p2 = await pass2.run(segments, llm_config, full_text)
    dur_p2 = round(time.monotonic() - t0, 1)

    # Break down pass 2 by perspective
    p2_by_perspective: dict[str, int] = {}
    for f in findings_p2:
        p2_by_perspective[f.quelle_pass] = p2_by_perspective.get(f.quelle_pass, 0) + 1

    p2_cats = Counter(f.kategorie for f in findings_p2)
    auswertung["passes"]["pass2_perspektive"] = {
        "kandidaten": len(findings_p2),
        "dauer_sekunden": dur_p2,
        "pro_perspektive": p2_by_perspective,
        "kategorien": dict(p2_cats),
    }

    # Store pass 2 findings grouped by perspective sub-pass
    for f in findings_p2:
        pass_key = f.quelle_pass or "Pass 2: Unbekannt"
        roh_kandidaten_pro_pass.setdefault(pass_key, []).append(
            _raw_finding_to_dict(f)
        )

    await _log(db, aid, vid,
               f"Pass 2 abgeschlossen: {len(findings_p2)} Kandidaten in {dur_p2}s.",
               details=auswertung["passes"]["pass2_perspektive"])
    all_raw_findings.extend(findings_p2)
    await db.commit()

    # Pass 3: Implizite Pflichten
    await _update_analyse(db, analyse, AnalyseStatus.PASS_3.value, "Implizite Pflichten", 60)
    await _log(db, aid, vid, "Pass 3: Implizite Pflichten gestartet.")
    await db.commit()

    t0 = time.monotonic()
    pass3 = ImplizitPass()
    findings_p3 = await pass3.run(segments, llm_config, full_text)
    dur_p3 = round(time.monotonic() - t0, 1)

    p3_cats = Counter(f.kategorie for f in findings_p3)
    auswertung["passes"]["pass3_implizit"] = {
        "kandidaten": len(findings_p3),
        "dauer_sekunden": dur_p3,
        "kategorien": dict(p3_cats),
    }

    roh_kandidaten_pro_pass["Pass 3: Implizite Pflichten"] = [
        _raw_finding_to_dict(f) for f in findings_p3
    ]

    await _log(db, aid, vid,
               f"Pass 3 abgeschlossen: {len(findings_p3)} Kandidaten in {dur_p3}s.",
               details=auswertung["passes"]["pass3_implizit"])
    all_raw_findings.extend(findings_p3)
    await db.commit()

    # Pass 4: Bankregulatorik
    await _update_analyse(db, analyse, AnalyseStatus.PASS_4.value, "Bankregulatorik", 75)
    await _log(db, aid, vid, "Pass 4: Bankregulatorik gestartet (KWG, MaRisk, BAIT, DORA).")
    await db.commit()

    t0 = time.monotonic()
    pass4 = BankregulatorikPass()
    findings_p4 = await pass4.run(segments, llm_config, full_text)
    dur_p4 = round(time.monotonic() - t0, 1)

    p4_cats = Counter(f.kategorie for f in findings_p4)
    auswertung["passes"]["pass4_bankregulatorik"] = {
        "kandidaten": len(findings_p4),
        "dauer_sekunden": dur_p4,
        "kategorien": dict(p4_cats),
    }

    roh_kandidaten_pro_pass["Pass 4: Bankregulatorik"] = [
        _raw_finding_to_dict(f) for f in findings_p4
    ]

    await _log(db, aid, vid,
               f"Pass 4 abgeschlossen: {len(findings_p4)} Kandidaten in {dur_p4}s.",
               details=auswertung["passes"]["pass4_bankregulatorik"])
    all_raw_findings.extend(findings_p4)
    await db.commit()

    # --- Step 4b: Topic Clustering ---
    await _update_analyse(db, analyse, AnalyseStatus.CLUSTERING.value, "Topic Clustering", 85)
    await _log(db, aid, vid,
               f"Topic Clustering gestartet: {len(all_raw_findings)} Findings clustern.")
    await db.commit()

    t0 = time.monotonic()
    topic_clusters = await clustere_findings(all_raw_findings, llm_config)
    dur_cluster = round(time.monotonic() - t0, 1)

    if topic_clusters:
        auswertung["clustering"] = {
            "themen_anzahl": len(topic_clusters),
            "dauer_sekunden": dur_cluster,
            "themen": [
                {"titel": t.titel, "evidence_count": len(t.evidence_titles)}
                for t in topic_clusters
            ],
        }
        await _log(db, aid, vid,
                   f"Topic Clustering abgeschlossen: {len(topic_clusters)} Risikothemen in {dur_cluster}s.",
                   details=auswertung["clustering"])
    else:
        auswertung["clustering"] = {"status": "uebersprungen", "dauer_sekunden": dur_cluster}
        await _log(db, aid, vid,
                   "Topic Clustering übersprungen (LLM-Ergebnis ungültig).",
                   ebene=ProtokollEbene.WARNUNG.value)
    await db.commit()

    # --- Step 5: Consolidation ---
    await _update_analyse(db, analyse, AnalyseStatus.KONSOLIDIERUNG.value, "Konsolidierung", 92)
    total_raw = len(all_raw_findings)
    await _log(db, aid, vid,
               f"Konsolidierung gestartet: {total_raw} Gesamtkandidaten aus 4 Passes.")
    await db.commit()

    t0 = time.monotonic()
    consolidated = konsolidiere(all_raw_findings)
    dur_cons = round(time.monotonic() - t0, 1)

    # Build consolidation stats
    merged_count = sum(1 for c in consolidated if c.raw_count > 1)
    solo_count = sum(1 for c in consolidated if c.raw_count == 1)
    max_merge = max((c.raw_count for c in consolidated), default=0)

    # Category distribution after consolidation
    final_cats = Counter(c.finding.kategorie for c in consolidated)
    final_risk = Counter(c.finding.risikostufe for c in consolidated)

    # Source pass distribution after consolidation
    source_pass_dist: dict[str, int] = {}
    for c in consolidated:
        for part in c.finding.quelle_pass.split(", "):
            cleaned = part.strip()
            if cleaned:
                source_pass_dist[cleaned] = source_pass_dist.get(cleaned, 0) + 1

    auswertung["konsolidierung"] = {
        "roh_gesamt": total_raw,
        "nach_konsolidierung": len(consolidated),
        "entfernte_duplikate": total_raw - len(consolidated),
        "zusammengefuehrt": merged_count,
        "unveraendert": solo_count,
        "max_zusammenfuehrungen": max_merge,
        "dauer_sekunden": dur_cons,
    }
    auswertung["ergebnis"] = {
        "fundstellen_gesamt": len(consolidated),
        "kategorien": dict(final_cats),
        "risikostufen": dict(final_risk),
        "quellen_verteilung": source_pass_dist,
    }
    auswertung["zeiten"] = {
        "pass1_sekunden": dur_p1,
        "pass2_sekunden": dur_p2,
        "pass3_sekunden": dur_p3,
        "pass4_sekunden": dur_p4,
        "clustering_sekunden": dur_cluster,
        "konsolidierung_sekunden": dur_cons,
    }
    auswertung["roh_kandidaten"] = roh_kandidaten_pro_pass

    await _log(db, aid, vid,
               f"Konsolidierung abgeschlossen: {len(consolidated)} Fundstellen "
               f"({merged_count} zusammengeführt, {solo_count} unverändert, "
               f"{total_raw - len(consolidated)} Duplikate entfernt).",
               details=auswertung["konsolidierung"])

    # --- Step 6: Enrich and persist findings ---
    seiten_map = vertrag.seiten_map if hasattr(vertrag, 'seiten_map') else None
    persisted_fundstellen: list[Fundstelle] = []
    for cf in consolidated:
        raw = cf.finding
        # Build enriched detail from contract context
        detail = anreichern(
            finding_text=raw.textstelle,
            full_text=full_text,
            absaetze=absaetze,
            seiten_map=seiten_map,
            segment_ids=raw.segment_ids,
            raw_fields={
                "risiko_detail": raw.risiko_detail,
                "alternativformulierung": raw.alternativformulierung,
                "bieterfrage": raw.bieterfrage,
                "verhandlungsargumente": raw.verhandlungsargumente,
            },
        )
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
            detail=detail,
            zusammenfuehrung=cf.merge_info(),
        )
        db.add(fundstelle)
        persisted_fundstellen.append(fundstelle)

    # Flush to assign IDs to all Fundstellen before linking topics
    await db.flush()

    # --- Step 6b: Persist topic clusters ---
    if topic_clusters:
        resolved = resolve_topic_fundstellen(topic_clusters, persisted_fundstellen)
        for idx, (cluster, linked_fundstellen) in enumerate(resolved):
            thema = RisikoThema(
                analyse_id=aid,
                vertrag_id=vid,
                titel=cluster.titel,
                kategorie=cluster.kategorie,
                risikostufe=cluster.risikostufe,
                beschreibung=cluster.beschreibung,
                sortierung=idx,
            )
            db.add(thema)
            await db.flush()
            for fs in linked_fundstellen:
                thema.fundstellen.append(fs)

        # Compute quality metrics
        metriken = berechne_clustering_metriken(resolved, len(persisted_fundstellen))
        titel_liste = [c.titel for c, _ in resolved]
        aehnliche_themen = berechne_titel_aehnlichkeit(titel_liste)
        metriken["aehnliche_themen"] = aehnliche_themen

        auswertung["clustering_metriken"] = metriken

        await _log(db, aid, vid,
                   f"{len(resolved)} Risikothemen mit Fundstellen verknüpft. "
                   f"Metriken: Ø {metriken['durchschnittliche_fundstellen_pro_thema']} Evidence/Thema, "
                   f"{metriken['anzahl_themen_mit_nur_1_fundstelle']} Themen mit nur 1 Fundstelle, "
                   f"{metriken['anzahl_evidence_mehrfach_zugeordnet']} mehrfach zugeordnet.",
                   details=metriken)

    # --- Step 7: Finalize with auswertung ---
    total_duration = round(time.monotonic() - pipeline_start, 1)
    auswertung["zeiten"]["gesamt_sekunden"] = total_duration

    analyse.auswertung = auswertung
    analyse.status = AnalyseStatus.ABGESCHLOSSEN.value
    analyse.aktueller_pass = None
    analyse.fortschritt = 100
    analyse.beendet_am = datetime.utcnow()
    vertrag.status = VertragStatus.ANALYSIERT.value

    await _log(db, aid, vid,
               f"Analyse abgeschlossen in {total_duration}s. "
               f"{len(consolidated)} Fundstellen gespeichert "
               f"(aus {total_raw} Rohkandidaten).",
               details=auswertung)
    await db.commit()


def _raw_finding_to_dict(f: RawFinding) -> dict:
    """Serialize a RawFinding to a JSON-safe dict for storage in auswertung."""
    d = {
        "textstelle": f.textstelle,
        "kategorie": f.kategorie,
        "kurzbeschreibung": f.kurzbeschreibung,
        "erklaerung": f.erklaerung,
        "empfehlung": f.empfehlung,
        "risikostufe": f.risikostufe,
        "segment_ids": f.segment_ids,
        "quelle_pass": f.quelle_pass,
    }
    # Include structured fields if populated
    if f.risiko_detail:
        d["risiko_detail"] = f.risiko_detail
    if f.alternativformulierung:
        d["alternativformulierung"] = f.alternativformulierung
    if f.bieterfrage:
        d["bieterfrage"] = f.bieterfrage
    if f.verhandlungsargumente:
        d["verhandlungsargumente"] = f.verhandlungsargumente
    return d
