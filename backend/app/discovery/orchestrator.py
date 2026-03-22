"""Discovery orchestrator: 2-stage pipeline (universal risk read + deep checks).

Architecture:
  A. Text extraction + clause-aware segmentation
  B. Universal risk read — every clause read once, strict problem screen
  C. Hard filter — drop non-problematic clauses
  D. Domain deep checks — only for flagged clauses
  E. Dedup / merge / consolidation
  F. Theme building (clustering)
  G. Editorial / negotiation generation
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
from app.discovery.passes.risk_screen import (
    run_risk_screen, filter_problematic, ClauseScreenResult,
)
from app.discovery.passes.deep_checks import (
    run_deep_checks, merge_deep_checks_into_findings,
)
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


class PipelineFailure(Exception):
    """Raised when the entire pipeline fails (zero successful steps).

    Not a generic RuntimeError — only raised when no pass produced results,
    so the caller can handle total-failure distinctly from partial success.
    """
    pass


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
    except PipelineFailure as e:
        # Expected total-failure — all passes failed, status already set inside pipeline
        # Log clearly but without full stacktrace (this is not an unexpected crash)
        logger.error(f"Pipeline: alle Schritte fehlgeschlagen – {e}")
        # fehler/fehler_details already set by the deterministic logic inside _run_pipeline
        # Only set them here as fallback if pipeline raised before finalization
        if not analyse.fehler:
            analyse.fehler = _user_facing_error(e)
        if not analyse.fehler_details:
            analyse.fehler_details = {
                "error_type": "PipelineFailure",
                "raw_message": str(e),
            }
        analyse.status = AnalyseStatus.FEHLGESCHLAGEN.value
        analyse.beendet_am = datetime.utcnow()
        await _log(db, analyse.id, vertrag.id,
                   f"Pipeline fehlgeschlagen: alle Schritte gescheitert",
                   ebene=ProtokollEbene.FEHLER.value,
                   details=analyse.fehler_details)
        await db.commit()
    except Exception as e:
        logger.exception(f"Discovery-Pipeline fehlgeschlagen: {e}")
        analyse.status = AnalyseStatus.FEHLGESCHLAGEN.value
        analyse.fehler = _user_facing_error(e)
        analyse.fehler_details = {
            "error_type": type(e).__name__,
            "raw_message": str(e),
            "traceback": traceback.format_exc(),
        }
        analyse.beendet_am = datetime.utcnow()
        await _log(db, analyse.id, vertrag.id,
                   f"Pipeline fehlgeschlagen: {type(e).__name__}",
                   ebene=ProtokollEbene.FEHLER.value,
                   details=analyse.fehler_details)
        await db.commit()


def _user_facing_error(e: Exception) -> str:
    """Convert an exception to a user-friendly message.

    Hides raw API error details, rate limit internals, and tracebacks.
    """
    msg = str(e).lower()
    if "429" in msg or "rate" in msg:
        return "Die KI-Schnittstelle ist vorübergehend überlastet. Bitte versuchen Sie es in einigen Minuten erneut."
    if "401" in msg or "auth" in msg or "api_key" in msg or "api-schlüssel" in msg:
        return "Der KI-API-Schlüssel ist ungültig oder fehlt. Bitte prüfen Sie die Einstellungen."
    if "timeout" in msg:
        return "Die KI-Anfrage hat zu lange gedauert (Zeitüberschreitung). Bitte erneut versuchen."
    if any(code in msg for code in ("500", "502", "503")):
        return "Der KI-Dienst ist vorübergehend nicht erreichbar. Bitte später erneut versuchen."
    if "textextraktion" in msg:
        return "Die Textextraktion aus dem Dokument ist fehlgeschlagen. Bitte prüfen Sie das Dateiformat."
    if "zu wenig text" in msg:
        return "Das Dokument enthält zu wenig Text für eine Analyse."
    # Generic fallback — do NOT expose raw exception message
    return "Bei der Analyse ist ein unerwarteter Fehler aufgetreten. Bitte versuchen Sie es erneut."


async def _run_pipeline(db: AsyncSession, analyse: Analyse, vertrag: Vertrag,
                        perspective: str = "provider") -> None:
    """2-stage pipeline: universal risk read → selective deep checks.

    Stages:
      1. Text extraction
      2. Clause-aware segmentation
      3. Universal risk read (every clause, once)
      4. Hard filter (drop non-problematic)
      5. Domain deep checks (only flagged clauses)
      6. Dedup / consolidation
      7. Topic clustering
      8. Editorial / negotiation generation
      9. Persist + finalize
    """

    vid = vertrag.id
    aid = analyse.id
    pipeline_start = time.monotonic()

    # Accumulates evaluation data for the auswertung field
    auswertung: dict = {"stages": {}, "segmente": {}, "konsolidierung": {}, "zeiten": {}}
    auswertung["perspective"] = perspective
    auswertung["pipeline_version"] = "v2_two_stage"

    # Deterministic step outcome tracking
    total_steps = 4  # risk_screen + deep_checks + clustering + editorial
    successful_steps = 0
    failed_steps: list[dict] = []

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
            "pipeline_version": "v2_two_stage",
        }
        await _log(db, aid, vid,
                   f"LLM-Konfiguration geladen: {llm_config.provider}/{llm_config.model}")
        await db.commit()
    except ValueError as e:
        raise ValueError(str(e)) from e

    vertrag.status = VertragStatus.IN_ANALYSE.value
    await db.commit()

    # ===================================================================
    # STAGE B: Universal Risk Read — every clause, once
    # ===================================================================
    await _update_analyse(db, analyse, AnalyseStatus.RISK_SCREEN.value,
                          "Risiko-Erstprüfung", 15)
    await _log(db, aid, vid,
               f"Risiko-Erstprüfung gestartet: {len(segments)} Segmente.")
    await db.commit()

    t0 = time.monotonic()
    screen_results: list[ClauseScreenResult] = []
    try:
        screen_results = await run_risk_screen(
            segments, llm_config, full_text, perspective=perspective,
        )
        dur_screen = round(time.monotonic() - t0, 1)
        successful_steps += 1
    except Exception as e:
        dur_screen = round(time.monotonic() - t0, 1)
        logger.error(f"Risiko-Erstprüfung fehlgeschlagen: {e}", exc_info=True)
        failed_steps.append({
            "step": "risk_screen",
            "error_type": type(e).__name__,
            "message": str(e),
        })

    # STAGE C: Hard filter — drop non-problematic
    problematic, dropped = filter_problematic(screen_results)

    # Collect screen metrics
    problem_type_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    for r in problematic:
        for pt in r.problem_types:
            problem_type_counts[pt] = problem_type_counts.get(pt, 0) + 1
        for td in r.trigger_domains:
            domain_counts[td] = domain_counts.get(td, 0) + 1

    auswertung["stages"]["risk_screen"] = {
        "total_clauses_read": len(screen_results),
        "clauses_flagged_problematic": len(problematic),
        "clauses_dropped_non_problematic": len(dropped),
        "dauer_sekunden": dur_screen,
        "counts_by_problem_type": problem_type_counts,
        "counts_by_trigger_domain": domain_counts,
        "status": "ok" if screen_results else "failed",
    }

    await _log(db, aid, vid,
               f"Risiko-Erstprüfung abgeschlossen in {dur_screen}s: "
               f"{len(problematic)} problematisch, "
               f"{len(dropped)} nicht-problematisch verworfen "
               f"(von {len(screen_results)} Segmenten).",
               details=auswertung["stages"]["risk_screen"])
    await db.commit()

    # If risk screen produced nothing at all, abort early
    if not screen_results and failed_steps:
        from app.discovery.llm_client import get_throttle as _get_throttle
        _throttle_stats = _get_throttle(llm_config).stats
        analyse.auswertung = auswertung
        analyse.fehler = (
            "Alle Verarbeitungsschritte sind fehlgeschlagen "
            f"(z.B. {failed_steps[0]['error_type']})."
        )
        analyse.fehler_details = {
            "successful_steps": 0,
            "failed_steps": failed_steps,
            "rate_limit_hits": _throttle_stats.get("rate_limit_hits", 0),
            "total_retries": _throttle_stats.get("total_retries", 0),
        }
        await db.flush()
        raise PipelineFailure(
            f"Risiko-Erstprüfung fehlgeschlagen. Keine Ergebnisse verfügbar."
        )

    # ===================================================================
    # STAGE D: Domain deep checks — only for flagged clauses
    # ===================================================================
    all_raw_findings: list[RawFinding] = []
    deep_check_results = {}

    clauses_needing_deep = [c for c in problematic if c.needs_deep_check]
    deep_checks_run_total = 0

    if clauses_needing_deep:
        await _update_analyse(db, analyse, AnalyseStatus.DEEP_CHECKS.value,
                              "Tiefenprüfung", 40)
        await _log(db, aid, vid,
                   f"Tiefenprüfung gestartet: {len(clauses_needing_deep)} Klauseln "
                   f"mit {sum(len(c.deep_check_domains) for c in clauses_needing_deep)} Domain-Checks.")
        await db.commit()

        t0 = time.monotonic()
        try:
            deep_check_results = await run_deep_checks(clauses_needing_deep, llm_config)
            dur_deep = round(time.monotonic() - t0, 1)
            deep_checks_run_total = sum(len(v) for v in deep_check_results.values())
            successful_steps += 1
        except Exception as e:
            dur_deep = round(time.monotonic() - t0, 1)
            logger.error(f"Tiefenprüfung fehlgeschlagen: {e}", exc_info=True)
            failed_steps.append({
                "step": "deep_checks",
                "error_type": type(e).__name__,
                "message": str(e),
            })

        auswertung["stages"]["deep_checks"] = {
            "clauses_checked": len(clauses_needing_deep),
            "deep_checks_run_total": deep_checks_run_total,
            "dauer_sekunden": dur_deep,
            "status": "ok" if deep_check_results else "failed",
        }

        await _log(db, aid, vid,
                   f"Tiefenprüfung abgeschlossen in {dur_deep}s: "
                   f"{deep_checks_run_total} Domain-Checks für "
                   f"{len(clauses_needing_deep)} Klauseln.",
                   details=auswertung["stages"]["deep_checks"])
        await db.commit()
    else:
        auswertung["stages"]["deep_checks"] = {
            "clauses_checked": 0,
            "deep_checks_run_total": 0,
            "dauer_sekunden": 0,
            "status": "skipped",
        }

    # Merge first-read + deep checks into RawFindings
    all_raw_findings = merge_deep_checks_into_findings(problematic, deep_check_results)

    # If no problematic findings and no error, it just means the contract is clean
    if not all_raw_findings:
        if failed_steps:
            from app.discovery.llm_client import get_throttle as _get_throttle
            _throttle_stats = _get_throttle(llm_config).stats
            analyse.auswertung = auswertung
            analyse.fehler = (
                "Alle Verarbeitungsschritte sind fehlgeschlagen "
                f"(z.B. {failed_steps[0]['error_type']})."
            )
            analyse.fehler_details = {
                "successful_steps": 0,
                "failed_steps": failed_steps,
                "rate_limit_hits": _throttle_stats.get("rate_limit_hits", 0),
                "total_retries": _throttle_stats.get("total_retries", 0),
            }
            await db.flush()
            raise PipelineFailure(
                f"Risiko-Erstprüfung fehlgeschlagen. Keine Ergebnisse verfügbar."
            )
        # Contract is genuinely clean — no problems found
        logger.info("Keine problematischen Klauseln gefunden — Vertrag ist sauber.")

    await _log(db, aid, vid,
               f"Risiko-Screening: {len(all_raw_findings)} Rohfunde aus "
               f"{len(problematic)} problematischen Klauseln.")
    await db.commit()

    # ===================================================================
    # STAGE E: Dedup / merge / consolidation
    # ===================================================================
    # --- Early semantic deduplication ---
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

    topic_clusters = None
    t0 = time.monotonic()
    try:
        topic_clusters = await clustere_findings(all_raw_findings, llm_config)
        dur_cluster = round(time.monotonic() - t0, 1)
    except Exception as e:
        dur_cluster = round(time.monotonic() - t0, 1)
        logger.error(f"Topic Clustering fehlgeschlagen: {e}", exc_info=True)
        failed_steps.append({"step": "clustering", "error_type": type(e).__name__, "message": str(e)})
        await _log(db, aid, vid,
                   f"Topic Clustering fehlgeschlagen: {type(e).__name__}. "
                   f"Schritt fehlgeschlagen, versuche verbleibende Schritte.",
                   ebene=ProtokollEbene.WARNUNG.value)

    if topic_clusters:
        successful_steps += 1
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
                   "Topic Clustering übersprungen (LLM-Ergebnis ungültig oder fehlgeschlagen).",
                   ebene=ProtokollEbene.WARNUNG.value)
    await db.commit()

    # --- Step 5: Consolidation ---
    await _update_analyse(db, analyse, AnalyseStatus.KONSOLIDIERUNG.value, "Konsolidierung", 92)
    total_raw = len(all_raw_findings)
    await _log(db, aid, vid,
               f"Konsolidierung gestartet: {total_raw} Gesamtkandidaten aus Risiko-Screening.")
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
        "risk_screen_sekunden": dur_screen,
        "deep_checks_sekunden": auswertung["stages"].get("deep_checks", {}).get("dauer_sekunden", 0),
        "dedup_sekunden": dur_dedup,
        "clustering_sekunden": dur_cluster,
        "konsolidierung_sekunden": dur_cons,
    }

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
        # counted as refs_missing_provenance and remain unresolved.

        # Build title→raw_index lookup for Pass 2 (kurzbeschreibung is LLM-generated
        # but is deterministically set at RawFinding creation, not editable later).
        # We track ALL indices per title to detect ambiguity — if multiple raw
        # findings share the same title, we must NOT enrich (arbitrary selection
        # would violate deterministic linkage).
        title_to_raw_indices: dict[str, list[int]] = {}
        for idx, raw in enumerate(all_raw_findings):
            key = raw.kurzbeschreibung.lower().strip()
            if key:
                title_to_raw_indices.setdefault(key, []).append(idx)

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
                # IMPORTANT: Only enrich when title maps to exactly one raw finding.
                # Ambiguous titles (multiple raw findings with same kurzbeschreibung)
                # must NOT be enriched — the ref stays unresolved.
                if ref.source_title:
                    title_key = ref.source_title.lower().strip()
                    matching_indices = title_to_raw_indices.get(title_key, [])
                    if len(matching_indices) == 1:
                        raw_idx = matching_indices[0]
                        raw = all_raw_findings[raw_idx]
                        ref.source_raw_index = raw_idx
                        ref.source_fingerprint = raw.source_fingerprint
                        logger.debug(
                            f"Enrichment: recovered index={raw_idx} + fingerprint "
                            f"for ref '{ref.source_title[:50]}' via title→raw lookup"
                        )
                    elif len(matching_indices) > 1:
                        logger.warning(
                            f"Enrichment: title '{ref.source_title[:50]}' matches "
                            f"{len(matching_indices)} raw findings — ambiguous, "
                            f"skipping enrichment"
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

        editorial_result = None
        try:
            editorial_result = await final_editorial_pass(
                themen_daten=editorial_input,
                text_laenge=len(full_text),
                config=llm_config,
            )
        except Exception as e:
            logger.error(f"Final Editorial Pass fehlgeschlagen: {e}", exc_info=True)
            failed_steps.append({"step": "editorial", "error_type": type(e).__name__, "message": str(e)})
            await _log(db, aid, vid,
                       f"Final Editorial Pass fehlgeschlagen: {type(e).__name__}. "
                       f"Schritt fehlgeschlagen, Themen bleiben ohne Editorial.",
                       ebene=ProtokollEbene.WARNUNG.value)
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
                        "problem_summary": ft.problem_summary,
                        "impact": ft.impact,
                        "recommendation": ft.recommendation,
                        "negotiation": ft.negotiation,
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
            successful_steps += 1

            await _log(db, aid, vid,
                       f"Final Editorial Pass abgeschlossen: {anzahl_finale} finale Themen"
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

    # Record failed steps in auswertung for debug
    if failed_steps:
        auswertung["failed_steps"] = failed_steps
    auswertung["step_summary"] = {
        "successful": successful_steps,
        "failed": len(failed_steps),
        "total": total_steps,
    }

    # Record LLM throttle stats
    from app.discovery.llm_client import get_throttle
    throttle_stats = get_throttle(llm_config).stats
    auswertung["llm_stats"] = throttle_stats

    analyse.auswertung = auswertung

    # --- Deterministic final status decision ---
    if successful_steps == 0:
        analyse.status = AnalyseStatus.FEHLGESCHLAGEN.value
        analyse.fehler = (
            "Alle Verarbeitungsschritte sind fehlgeschlagen "
            f"(z.B. {failed_steps[0]['error_type'] if failed_steps else 'Unbekannt'})."
        )
        analyse.fehler_details = {
            "successful_steps": successful_steps,
            "failed_steps": failed_steps,
            "rate_limit_hits": throttle_stats.get("rate_limit_hits", 0),
            "total_retries": throttle_stats.get("total_retries", 0),
        }
    elif successful_steps < total_steps:
        analyse.status = AnalyseStatus.TEILWEISE_ABGESCHLOSSEN.value
        analyse.fehler = (
            f"{len(failed_steps)} Analyse-Schritt(e) fehlgeschlagen. "
            f"Ergebnisse basieren auf den {successful_steps} erfolgreichen Schritten."
        )
        analyse.fehler_details = {
            "successful_steps": successful_steps,
            "failed_steps": failed_steps,
            "rate_limit_hits": throttle_stats.get("rate_limit_hits", 0),
            "total_retries": throttle_stats.get("total_retries", 0),
        }
    else:
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

    # Pipeline metrics (new 2-stage architecture)
    screen_stage = auswertung["stages"].get("risk_screen", {})
    deep_stage = auswertung["stages"].get("deep_checks", {})
    analysis_stats = {
        "pipeline_version": "v2_two_stage",
        "perspective": perspective,
        # Stage B metrics
        "total_clauses_read": screen_stage.get("total_clauses_read", 0),
        "clauses_flagged_problematic": screen_stage.get("clauses_flagged_problematic", 0),
        "clauses_dropped_non_problematic": screen_stage.get("clauses_dropped_non_problematic", 0),
        "counts_by_problem_type": screen_stage.get("counts_by_problem_type", {}),
        "counts_by_trigger_domain": screen_stage.get("counts_by_trigger_domain", {}),
        # Stage D metrics
        "deep_checks_run_total": deep_stage.get("deep_checks_run_total", 0),
        # Dedup / consolidation metrics
        "problems_after_dedup": dedup_result.raw_after,
        "after_consolidation": len(consolidated),
        # Theme metrics
        "themes_before_editorial": len(topic_clusters) if topic_clusters else 0,
        "themes_after_editorial": kernthemen_count,
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
