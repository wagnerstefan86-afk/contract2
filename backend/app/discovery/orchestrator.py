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
from app.discovery.final_editorial import final_editorial_pass
from app.discovery.passes.base import RawFinding, VALID_PERSPECTIVES
from app.discovery.dedup import deduplicate_raw_findings
from app.models.risikothema import RisikoThema, risikothema_fundstellen

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


async def run_discovery(analyse_id: uuid.UUID, db: AsyncSession,
                        perspective: str = "provider") -> None:
    """Run the full discovery pipeline for one analysis.

    This is the main entry point called by the background task.
    It manages its own commits and error handling.

    Args:
        perspective: Analysis perspective — "provider", "client", or "neutral".
    """
    if perspective not in VALID_PERSPECTIVES:
        perspective = "provider"

    analyse = await db.get(Analyse, analyse_id)
    if not analyse:
        logger.error(f"Analyse {analyse_id} nicht gefunden")
        return

    vertrag = await db.get(Vertrag, analyse.vertrag_id)
    if not vertrag:
        logger.error(f"Vertrag für Analyse {analyse_id} nicht gefunden")
        return

    try:
        await _run_pipeline(db, analyse, vertrag, perspective=perspective)
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


async def _run_pipeline(db: AsyncSession, analyse: Analyse, vertrag: Vertrag,
                        perspective: str = "provider") -> None:
    """Inner pipeline logic with full observability."""

    vid = vertrag.id
    aid = analyse.id
    pipeline_start = time.monotonic()

    # Accumulates evaluation data for the auswertung field
    auswertung: dict = {"passes": {}, "segmente": {}, "konsolidierung": {}, "zeiten": {}}
    auswertung["perspective"] = perspective

    # --- Step 1: Text extraction ---
    await _update_analyse(db, analyse, AnalyseStatus.GESTARTET.value, "Textextraktion", 5)
    await _log(db, aid, vid, f"Analyse gestartet (Perspektive: {perspective}). Textextraktion beginnt.")
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
    findings_p1 = await pass1.run(segments, llm_config, full_text, perspective=perspective)
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
    findings_p2 = await pass2.run(segments, llm_config, full_text, perspective=perspective)
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
    findings_p3 = await pass3.run(segments, llm_config, full_text, perspective=perspective)
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
    findings_p4 = await pass4.run(segments, llm_config, full_text, perspective=perspective)
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

    # --- Step 4a: Early semantic deduplication ---
    t0 = time.monotonic()
    dedup_result = deduplicate_raw_findings(all_raw_findings)
    dur_dedup = round(time.monotonic() - t0, 1)

    all_raw_findings = dedup_result.findings

    auswertung["dedup"] = {
        "raw_findings_before_dedup": dedup_result.raw_before,
        "after_pass_dedup": dedup_result.after_pass_dedup,
        "after_cross_dedup": dedup_result.after_cross_dedup,
        "raw_findings_after_dedup": dedup_result.raw_after,
        "duplicates_removed": dedup_result.duplicates_removed,
        "dauer_sekunden": dur_dedup,
    }
    await _log(db, aid, vid,
               f"Dedup: {dedup_result.raw_before} → "
               f"{dedup_result.after_pass_dedup} (pass) → "
               f"{dedup_result.after_cross_dedup} (cross-seg), "
               f"{dedup_result.duplicates_removed} removed, {dur_dedup}s.",
               details=auswertung["dedup"])
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
                {"titel": t.titel, "evidence_count": len(t.evidence_refs)}
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
        "dedup_sekunden": dur_dedup,
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
            # Paragraph-level evidence fields
            scope_type=raw.scope_type or None,
            scope_text=raw.scope_text or None,
            trigger_spans=raw.trigger_spans or None,
            evidence_heading_path=raw.evidence_heading_path or None,
        )
        db.add(fundstelle)
        persisted_fundstellen.append(fundstelle)

    # Flush to assign IDs to all Fundstellen before linking topics
    await db.flush()

    # --- Step 6b: Persist topic clusters ---
    # NOTE: We must NOT access ORM relationship collections (e.g. thema.fundstellen)
    # in async context — this triggers lazy loading which fails with greenlet_spawn.
    # Instead, we insert into the junction table explicitly using plain UUIDs.
    if topic_clusters:
        logger.info("Persist topic clusters: resolving evidence → Fundstellen mapping")

        # Build deterministic mapping: raw_finding_index (0-based) → Fundstelle objects.
        # ConsolidatedFinding.source_raw_indices tracks which RawFindings were merged
        # into each consolidated finding, and persisted_fundstellen is in the same
        # order as consolidated.
        raw_index_to_fundstelle: dict[int, list] = {}
        for cf_idx, cf in enumerate(consolidated):
            fs = persisted_fundstellen[cf_idx]
            for raw_idx in cf.source_raw_indices:
                raw_index_to_fundstelle.setdefault(raw_idx, []).append(fs)

        # Build deterministic mapping: source_fingerprint → Fundstelle objects.
        # Uses the canonical fingerprint from textstelle + absatz_ids, computed
        # identically to RawFinding.source_fingerprint (same hash function).
        from app.discovery.passes.base import build_source_fingerprint
        fingerprint_to_fundstelle: dict[str, list] = {}
        for fs in persisted_fundstellen:
            fp = build_source_fingerprint(fs.textstelle, fs.absatz_ids)
            fingerprint_to_fundstelle.setdefault(fp, []).append(fs)

        # --- Enrich TopicEvidenceRef provenance BEFORE resolution ---
        # Two-pass enrichment ensures maximum fingerprint coverage:
        # Pass 1: Populate source_fingerprint from source_raw_index (direct).
        # Pass 2: For refs still missing both identifiers, attempt to recover
        #         source_raw_index and source_fingerprint by matching source_title
        #         against known raw findings. This closes the gap where the LLM
        #         omits finding_nr but provides ursprungstitel.
        # After enrichment, refs with neither index nor fingerprint will be
        # counted as refs_missing_provenance and remain unresolved unless
        # the title fallback flag is enabled.

        # Build title→raw_index lookup for Pass 2 (kurzbeschreibung is LLM-generated
        # but is deterministically set at RawFinding creation, not editable later)
        title_to_raw_index: dict[str, int] = {}
        for idx, raw in enumerate(all_raw_findings):
            key = raw.kurzbeschreibung.lower().strip()
            if key and key not in title_to_raw_index:
                title_to_raw_index[key] = idx

        for cluster in topic_clusters:
            for ref in cluster.evidence_refs:
                # Pass 1: Direct index → fingerprint
                if ref.source_fingerprint:
                    continue
                if ref.source_raw_index is not None and ref.source_raw_index < len(all_raw_findings):
                    raw = all_raw_findings[ref.source_raw_index]
                    if raw.source_fingerprint:
                        ref.source_fingerprint = raw.source_fingerprint
                    continue

                # Pass 2: Recover index + fingerprint from title (one-time enrichment).
                # This does NOT use title for linkage resolution — it uses title
                # to recover the deterministic identifiers that the LLM failed to
                # provide, so that resolution can proceed via Strategy 1 or 2.
                if ref.source_title:
                    title_key = ref.source_title.lower().strip()
                    raw_idx = title_to_raw_index.get(title_key)
                    if raw_idx is not None:
                        raw = all_raw_findings[raw_idx]
                        ref.source_raw_index = raw_idx
                        ref.source_fingerprint = raw.source_fingerprint
                        logger.debug(
                            f"Enrichment: recovered index={raw_idx} + fingerprint "
                            f"for ref '{ref.source_title[:50]}' via title→raw lookup"
                        )

        resolved, linkage_stats = resolve_topic_fundstellen(
            topic_clusters, persisted_fundstellen,
            raw_index_to_fundstelle=raw_index_to_fundstelle,
            fingerprint_to_fundstelle=fingerprint_to_fundstelle,
        )

        junction_rows = []
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
            await db.flush()  # assigns thema.id
            logger.debug(f"RisikoThema erstellt: '{cluster.titel}' (id={thema.id})")

            # Collect junction table rows — use plain UUIDs, no relationship access
            for fs in linked_fundstellen:
                junction_rows.append({
                    "risikothema_id": thema.id,
                    "fundstelle_id": fs.id,
                })

        # Bulk insert junction table rows (no ORM relationship loading)
        if junction_rows:
            logger.info(f"Persist topic clusters: {len(junction_rows)} Zuordnungen in Junction-Tabelle")
            await db.execute(risikothema_fundstellen.insert(), junction_rows)
            await db.flush()

        logger.info(f"Persist topic clusters: {len(resolved)} Themen gespeichert")

        # Compute quality metrics using plain data (no lazy loads)
        metriken = berechne_clustering_metriken(resolved, len(persisted_fundstellen))
        titel_liste = [c.titel for c, _ in resolved]
        aehnliche_themen = berechne_titel_aehnlichkeit(titel_liste)
        metriken["aehnliche_themen"] = aehnliche_themen
        metriken["evidence_linkage"] = linkage_stats.to_dict()

        auswertung["clustering_metriken"] = metriken

        await _log(db, aid, vid,
                   f"{len(resolved)} Risikothemen mit Fundstellen verknüpft. "
                   f"Linkage: {linkage_stats.direct_index_matches} index, "
                   f"{linkage_stats.source_fingerprint_matches} fp, "
                   f"{linkage_stats.unresolved_references} unresolved, "
                   f"{linkage_stats.refs_missing_provenance} missing-prov.",
                   details=metriken)

    # --- Step 7: Final Editorial Pass ---
    if topic_clusters and len(resolved) > 0:
        await _update_analyse(db, analyse, AnalyseStatus.EDITORIAL.value,
                              "Final Editorial Pass", 95)
        await _log(db, aid, vid,
                   f"Final Editorial Pass gestartet: {len(resolved)} Themen reduzieren.")
        await db.commit()

        t0 = time.monotonic()

        # Build input data for the editorial pass
        editorial_input = []
        # We need a mapping from resolved index to (RisikoThema, fundstellen)
        # resolved was built earlier; we stored thema objects in DB already.
        # Re-query is not needed — we can reconstruct from what we have.
        resolved_thema_ids: list[uuid.UUID] = []
        for idx, (cluster, linked_fs) in enumerate(resolved):
            thema_data = {
                "titel": cluster.titel,
                "kategorie": cluster.kategorie,
                "risikostufe": cluster.risikostufe,
                "beschreibung": cluster.beschreibung,
                "fundstellen": [
                    {
                        "kurzbeschreibung": fs.kurzbeschreibung,
                        "textstelle": fs.textstelle[:300],
                        "risikostufe": fs.risikostufe,
                    }
                    for fs in linked_fs
                ],
            }
            editorial_input.append(thema_data)

        editorial_result = await final_editorial_pass(
            themen_daten=editorial_input,
            text_laenge=len(full_text),
            config=llm_config,
        )
        dur_editorial = round(time.monotonic() - t0, 1)

        if editorial_result:
            # We need to map resolved indices back to persisted RisikoThema objects.
            # The themen were persisted earlier in Step 6b in the same order as `resolved`.
            # Re-query them by analyse_id + sortierung to get the same order.
            from sqlalchemy import select as sa_select
            thema_result = await db.execute(
                sa_select(RisikoThema)
                .where(RisikoThema.analyse_id == aid)
                .order_by(RisikoThema.sortierung)
            )
            persisted_themen = list(thema_result.scalars().all())

            # Build a lookup: resolved_index -> persisted RisikoThema
            # and resolved_index -> list of linked Fundstelle objects
            resolved_fs_map: dict[int, list] = {}
            for idx, (cluster, linked_fs) in enumerate(resolved):
                resolved_fs_map[idx] = linked_fs

            # Mark selected themes
            selected_indices = {ft.quell_thema_index for ft in editorial_result.finale_themen}

            for ft in editorial_result.finale_themen:
                idx = ft.quell_thema_index
                if idx < len(persisted_themen):
                    thema = persisted_themen[idx]
                    thema.final_selected = True
                    thema.titel = ft.titel  # Use improved editorial title

                    # Determine primary and secondary fundstelle IDs
                    linked_fs = resolved_fs_map.get(idx, [])
                    prim_id = None
                    sek_ids = []
                    if linked_fs and ft.primaerfundstelle_index < len(linked_fs):
                        prim_id = str(linked_fs[ft.primaerfundstelle_index].id)
                    elif linked_fs:
                        prim_id = str(linked_fs[0].id)
                    for si in ft.sekundaerfundstelle_indices:
                        if si < len(linked_fs):
                            sek_ids.append(str(linked_fs[si].id))

                    thema.final_editorial = {
                        "kurzbeschreibung": ft.kurzbeschreibung,
                        "warum_verhandlungsrelevant": ft.warum_verhandlungsrelevant,
                        "alternativformulierung": ft.alternativformulierung,
                        "bieterfrage": ft.bieterfrage,
                        "verhandlungsargumente": ft.verhandlungsargumente,
                        "primaerfundstelle_id": prim_id,
                        "sekundaerfundstelle_ids": sek_ids,
                    }

            for vt in editorial_result.verworfene_themen:
                idx = vt.quell_thema_index
                if idx < len(persisted_themen):
                    thema = persisted_themen[idx]
                    thema.final_selected = False
                    thema.final_verwerfungsgrund = vt.grund

            # Also mark any themes not mentioned as not selected
            mentioned = selected_indices | {vt.quell_thema_index for vt in editorial_result.verworfene_themen}
            for idx, thema in enumerate(persisted_themen):
                if idx not in mentioned:
                    thema.final_selected = False
                    thema.final_verwerfungsgrund = "Vom LLM nicht adressiert"

            # --- Evidence integrity check (hard invariant) ---
            # A final_selected theme MUST have ≥1 linked Fundstelle.
            # No heuristic fallback — incorrect linkage is worse than dropping.
            # If linkage failed, the theme is dropped from final selection.
            themes_dropped_no_evidence = 0
            for idx, thema in enumerate(persisted_themen):
                if not thema.final_selected:
                    continue
                linked_fs = resolved_fs_map.get(idx, [])
                if len(linked_fs) == 0:
                    thema.final_selected = False
                    thema.final_verwerfungsgrund = "Keine zugeordneten Evidenzen (Linkage fehlgeschlagen)"
                    themes_dropped_no_evidence += 1
                    logger.warning(
                        f"RisikoThema '{thema.titel}' (id={thema.id}, analyse_id={thema.analyse_id}) "
                        f"final_selected zurückgesetzt: 0 Evidenzen nach deterministischer Auflösung."
                    )

            await db.flush()

            # Recount after evidence integrity check
            anzahl_finale = sum(1 for t in persisted_themen if t.final_selected)
            anzahl_verworfen = len(persisted_themen) - anzahl_finale
            themes_with_evidence = sum(
                1 for idx, t in enumerate(persisted_themen)
                if t.final_selected and len(resolved_fs_map.get(idx, [])) > 0
            )
            auswertung["final_editorial"] = {
                "anzahl_cluster_themen_vorher": len(persisted_themen),
                "anzahl_finale_themen_nachher": anzahl_finale,
                "anzahl_verworfene_themen": anzahl_verworfen,
                "themes_with_evidence": themes_with_evidence,
                "themes_dropped_no_evidence": themes_dropped_no_evidence,
                "dauer_sekunden": dur_editorial,
                "finale_themen": [
                    {"titel": ft.titel, "kategorie": ft.kategorie, "risikostufe": ft.risikostufe}
                    for ft in editorial_result.finale_themen
                ],
                "verworfene_themen": [
                    {"index": vt.quell_thema_index, "grund": vt.grund}
                    for vt in editorial_result.verworfene_themen
                ],
            }
            auswertung["zeiten"]["editorial_sekunden"] = dur_editorial

            await _log(db, aid, vid,
                       f"Final Editorial Pass abgeschlossen: {anzahl_finale} finale Themen "
                       f"aus {len(persisted_themen)} Cluster-Themen in {dur_editorial}s. "
                       f"{anzahl_verworfen} Themen verworfen.",
                       details=auswertung["final_editorial"])
        else:
            auswertung["final_editorial"] = {
                "status": "uebersprungen",
                "dauer_sekunden": dur_editorial,
            }
            await _log(db, aid, vid,
                       "Final Editorial Pass übersprungen (LLM-Ergebnis ungültig).",
                       ebene=ProtokollEbene.WARNUNG.value)

        await db.commit()

    # --- Step 8: Finalize with auswertung ---
    total_duration = round(time.monotonic() - pipeline_start, 1)
    auswertung["zeiten"]["gesamt_sekunden"] = total_duration

    analyse.auswertung = auswertung
    analyse.status = AnalyseStatus.ABGESCHLOSSEN.value
    analyse.aktueller_pass = None
    analyse.fortschritt = 100
    analyse.beendet_am = datetime.utcnow()
    vertrag.status = VertragStatus.ANALYSIERT.value

    # Count evidence across persisted fundstellen
    evidence_count = sum(
        1 for fs in persisted_fundstellen
        if fs.scope_text or fs.textstelle
    )
    # Count kernthemen (final_selected themes) — use actual DB state after integrity check
    kernthemen_count = 0
    try:
        if topic_clusters and persisted_themen:
            kernthemen_count = sum(1 for t in persisted_themen if t.final_selected)
    except NameError:
        pass

    # --- Pipeline invariant check ---
    # Verify no final_selected theme has zero evidences
    try:
        if topic_clusters and persisted_themen:
            invalid = [
                t for idx, t in enumerate(persisted_themen)
                if t.final_selected and len(resolved_fs_map.get(idx, [])) == 0
            ]
            if invalid:
                titles = [t.titel for t in invalid]
                logger.error(
                    f"INVARIANT VIOLATION: {len(invalid)} final themes without evidences: {titles}"
                )
                # Enforce: drop them rather than let invalid data through
                for t in invalid:
                    t.final_selected = False
                    t.final_verwerfungsgrund = "Invariant-Check: 0 Evidenzen"
                kernthemen_count -= len(invalid)
                await db.flush()
    except NameError:
        pass

    # Collect linkage stats if available
    linkage_dict = {}
    try:
        linkage_dict = linkage_stats.to_dict()
    except NameError:
        pass

    analysis_stats = {
        "perspective": perspective,
        "raw_findings": dedup_result.raw_before,
        "after_pass_dedup": dedup_result.after_pass_dedup,
        "after_cross_dedup": dedup_result.after_cross_dedup,
        "after_consolidation": len(consolidated),
        "clusters": len(topic_clusters) if topic_clusters else 0,
        "kernthemen": kernthemen_count,
        "evidence_count": evidence_count,
        "evidence_linkage": linkage_dict,
    }
    auswertung["analysis_stats"] = analysis_stats

    await _log(db, aid, vid,
               f"Analyse abgeschlossen in {total_duration}s. "
               f"{len(consolidated)} Fundstellen gespeichert "
               f"(aus {total_raw} Rohkandidaten).",
               details=auswertung)
    logger.info(
        f"Pipeline summary: raw_findings={analysis_stats['raw_findings']}, "
        f"after_pass_dedup={analysis_stats['after_pass_dedup']}, "
        f"after_cross_dedup={analysis_stats['after_cross_dedup']}, "
        f"clusters={analysis_stats['clusters']}, "
        f"kernthemen={analysis_stats['kernthemen']}, "
        f"evidence_count={analysis_stats['evidence_count']}"
    )
    logger.info(f"Pipeline final commit: {len(consolidated)} Fundstellen, "
                f"{len(topic_clusters) if topic_clusters else 0} Themen")
    await db.commit()
    logger.info("Pipeline final commit erfolgreich")


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
    # Paragraph-level evidence fields
    if f.scope_type:
        d["scope_type"] = f.scope_type
    if f.scope_text:
        d["scope_text"] = f.scope_text
    if f.trigger_spans:
        d["trigger_spans"] = f.trigger_spans
    if f.evidence_heading_path:
        d["evidence_heading_path"] = f.evidence_heading_path
    return d
