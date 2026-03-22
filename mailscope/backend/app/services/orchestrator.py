"""Background orchestrator: runs the full analysis pipeline for a job."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from app.config import settings
from app.database import SessionLocal
from app.models import AnalysisJob, ExtractedLink, ExternalCheckResult, LlmAssessment
from app.services import (
    header_analyzer,
    link_analyzer,
    link_extractor,
    llm_client,
    parser,
    pre_scorer,
    url_normalizer,
    virustotal,
    urlscan,
)

logger = logging.getLogger(__name__)


def _update_status(db, job: AnalysisJob, status: str):
    job.status = status
    db.commit()


def _add_warning(db, job: AnalysisJob, warning: str):
    warnings = json.loads(job.warnings) if job.warnings else []
    warnings.append(warning)
    job.warnings = json.dumps(warnings, ensure_ascii=False)
    db.commit()


def run_analysis(job_id: str, file_path: str, extension: str):
    """Entry point for background task. Runs the async pipeline."""
    asyncio.run(_run_pipeline(job_id, file_path, extension))


async def _run_pipeline(job_id: str, file_path: str, extension: str):
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        if not job:
            logger.error("Job %s not found", job_id)
            return

        # Snapshot service flags
        vt_enabled = settings.enable_virustotal and bool(settings.virustotal_api_key)
        us_enabled = settings.enable_urlscan and bool(settings.urlscan_api_key)
        llm_enabled = settings.enable_llm and bool(settings.openai_api_key)

        job.vt_enabled = int(vt_enabled)
        job.urlscan_enabled = int(us_enabled)
        job.llm_enabled = int(llm_enabled)
        db.commit()

        if not vt_enabled:
            _add_warning(db, job, "VirusTotal ist deaktiviert oder kein API-Key konfiguriert.")
        if not us_enabled:
            _add_warning(db, job, "urlscan.io ist deaktiviert oder kein API-Key konfiguriert.")
        if not llm_enabled:
            _add_warning(db, job, "LLM-Analyse ist deaktiviert. Es wird nur die deterministische Bewertung verwendet.")

        # --- Step 1: Parse ---
        _update_status(db, job, "parsing")
        try:
            parsed = parser.parse_email_file(file_path, extension)
        except Exception as e:
            job.status = "failed"
            job.error_message = f"Fehler beim Parsen: {str(e)}"
            db.commit()
            return
        finally:
            try:
                os.unlink(file_path)
            except OSError:
                pass

        job.subject = parsed.subject
        job.sender = parsed.sender
        job.reply_to = parsed.reply_to
        job.return_path = parsed.return_path
        job.to_address = parsed.to
        job.date = parsed.date
        job.message_id = parsed.message_id
        job.authentication_results = parsed.authentication_results
        job.received_chain = json.dumps(parsed.received_chain)
        job.raw_headers = parsed.raw_headers
        job.structured_headers = json.dumps(parsed.structured_headers)
        job.body_text = parsed.body_text
        job.body_html = parsed.body_html
        job.attachment_metadata = json.dumps(
            [{"filename": a.filename, "content_type": a.content_type, "size": a.size} for a in parsed.attachments]
        )
        db.commit()

        # --- Step 2: Extract links ---
        _update_status(db, job, "extracting_links")
        raw_links = link_extractor.extract_all_links(parsed.body_text, parsed.body_html)
        deduped = url_normalizer.deduplicate_links(raw_links)

        all_link_hostnames: list[str] = []
        link_records: list[ExtractedLink] = []

        for norm_url, raw_link in deduped:
            analysis = link_analyzer.analyze_link(raw_link.url, norm_url, raw_link.display_text)
            hostname = analysis["final_hostname"]
            all_link_hostnames.append(hostname)

            link_rec = ExtractedLink(
                job_id=job_id,
                original_url=raw_link.url,
                normalized_url=norm_url,
                final_hostname=hostname,
                display_text=raw_link.display_text,
                display_text_mismatch=int(analysis["display_text_mismatch"]),
                suspicious_tld=int(analysis["suspicious_tld"]),
                ip_literal=int(analysis["ip_literal"]),
                punycode=int(analysis["punycode"]),
                url_shortener=int(analysis["url_shortener"]),
                tracking_heavy=int(analysis["tracking_heavy"]),
                link_findings=json.dumps(analysis),
            )
            db.add(link_rec)
            link_records.append(link_rec)
        db.commit()

        # --- Step 3: Header heuristics ---
        header_findings = header_analyzer.analyze_headers(
            structured_headers=parsed.structured_headers,
            sender=parsed.sender,
            reply_to=parsed.reply_to,
            return_path=parsed.return_path,
            authentication_results=parsed.authentication_results,
            received_chain=parsed.received_chain,
            all_link_hostnames=all_link_hostnames,
        )
        job.header_findings = json.dumps(header_findings)
        db.commit()

        # --- Step 4: External scans (with partial failure tolerance) ---
        has_scan_warnings = False
        if vt_enabled or us_enabled:
            _update_status(db, job, "checking_reputation")
            scan_tasks = []
            for link_rec in link_records:
                scan_tasks.append(_scan_link(db, link_rec, vt_enabled, us_enabled))
            if scan_tasks:
                await asyncio.gather(*scan_tasks)
            db.commit()

            # Check for scan failures
            for link_rec in link_records:
                db.refresh(link_rec)
                for check in link_rec.checks:
                    if check.status in ("error", "timeout"):
                        has_scan_warnings = True
                        _add_warning(db, job, f"{check.service} für {link_rec.normalized_url[:80]}: {check.status}")
        else:
            # Mark all as skipped
            for link_rec in link_records:
                for service in ["virustotal", "urlscan"]:
                    skip = ExternalCheckResult(
                        link_id=link_rec.id, service=service, status="skipped",
                        summary=json.dumps({"info": "Service deaktiviert"}),
                    )
                    db.add(skip)
            db.commit()

        # --- Step 5: Deterministic pre-scoring ---
        link_dicts = []
        external_checks_dicts = []
        for link_rec in link_records:
            db.refresh(link_rec)
            link_dicts.append({
                "display_text_mismatch": bool(link_rec.display_text_mismatch),
                "suspicious_tld": bool(link_rec.suspicious_tld),
                "ip_literal": bool(link_rec.ip_literal),
                "punycode": bool(link_rec.punycode),
                "url_shortener": bool(link_rec.url_shortener),
                "tracking_heavy": bool(link_rec.tracking_heavy),
            })
            for check in link_rec.checks:
                external_checks_dicts.append({
                    "service": check.service,
                    "status": check.status,
                    "score": check.score,
                    "verdict": check.verdict,
                    "summary": check.summary,
                })

        scores = pre_scorer.compute_pre_scores(header_findings, link_dicts, external_checks_dicts)
        job.phishing_score = scores.phishing_score
        job.advertising_score = scores.advertising_score
        job.legitimacy_score = scores.legitimacy_score
        job.pre_score_details = json.dumps(scores.breakdown)
        db.commit()

        # --- Step 6: LLM assessment (or deterministic fallback) ---
        _update_status(db, job, "llm_assessment")

        link_analyses = []
        for link_rec in link_records:
            la = {
                "url": link_rec.normalized_url,
                "hostname": link_rec.final_hostname,
                "flags": json.loads(link_rec.link_findings) if link_rec.link_findings else {},
            }
            for check in link_rec.checks:
                if check.summary and check.status not in ("skipped",):
                    la[f"{check.service}_summary"] = json.loads(check.summary)
            link_analyses.append(la)

        pre_scores_dict = {
            "phishing_score": scores.phishing_score,
            "advertising_score": scores.advertising_score,
            "legitimacy_score": scores.legitimacy_score,
            "breakdown": scores.breakdown,
        }

        assessment_source = "deterministic"
        assessment_data = None

        if llm_enabled:
            payload = llm_client.build_analysis_payload(
                sender=parsed.sender,
                reply_to=parsed.reply_to,
                return_path=parsed.return_path,
                subject=parsed.subject,
                date=parsed.date,
                authentication_results=parsed.authentication_results,
                body_text_snippet=parsed.body_text,
                header_findings=header_findings,
                link_analyses=link_analyses,
                attachment_metadata=json.loads(job.attachment_metadata) if job.attachment_metadata else [],
                pre_scores=pre_scores_dict,
            )

            assessment_data, source = await llm_client.get_assessment(payload)
            if assessment_data:
                assessment_source = source
            else:
                # LLM failed -> deterministic fallback
                _add_warning(db, job, "LLM-Bewertung fehlgeschlagen. Deterministische Fallback-Bewertung wird verwendet.")
                assessment_data = pre_scorer.build_deterministic_assessment(scores, header_findings)
                assessment_source = "fallback"
        else:
            # LLM disabled -> deterministic only
            assessment_data = pre_scorer.build_deterministic_assessment(scores, header_findings)
            assessment_source = "deterministic"

        if assessment_data:
            llm_rec = LlmAssessment(
                job_id=job_id,
                source=assessment_source,
                classification=assessment_data.get("classification"),
                risk_score=assessment_data.get("risk_score"),
                confidence=assessment_data.get("confidence"),
                recommended_action=assessment_data.get("recommended_action"),
                rationale=assessment_data.get("rationale"),
                evidence=json.dumps(assessment_data.get("evidence", []), ensure_ascii=False),
                analyst_summary=assessment_data.get("analyst_summary"),
                raw_response=json.dumps(assessment_data, ensure_ascii=False),
            )
            db.add(llm_rec)

        # Final status
        if has_scan_warnings or assessment_source in ("fallback", "deterministic"):
            _update_status(db, job, "completed_with_warnings")
        else:
            _update_status(db, job, "completed")
        logger.info("Analysis complete for job %s (source=%s)", job_id, assessment_source)

    except Exception as e:
        logger.exception("Pipeline error for job %s", job_id)
        try:
            job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = f"Pipeline-Fehler: {str(e)}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _scan_link(db, link_rec: ExtractedLink, vt_enabled: bool, us_enabled: bool):
    """Run VT and urlscan for a single link, tolerating failures."""
    url = link_rec.normalized_url

    # VirusTotal
    if vt_enabled:
        vt_check = ExternalCheckResult(link_id=link_rec.id, service="virustotal", status="pending")
        db.add(vt_check)
        db.commit()

        try:
            analysis_id = await virustotal.submit_url(url)
            if analysis_id:
                vt_check.submission_id = analysis_id
                vt_check.status = "polling"
                db.commit()

                result = await virustotal.poll_analysis(analysis_id)
                summary = virustotal.summarize_result(result)
                vt_check.raw_result = json.dumps(result) if result else None
                vt_check.summary = json.dumps(summary)
                vt_check.score = summary.get("malicious", 0)
                vt_check.verdict = "malicious" if summary.get("malicious", 0) > 0 else "clean"
                vt_check.status = "done" if result else "timeout"
            else:
                vt_check.status = "error"
                vt_check.summary = json.dumps({"error": "Submission failed or API key missing"})
        except Exception as e:
            logger.warning("VT scan error for %s: %s", url[:60], e)
            vt_check.status = "error"
            vt_check.summary = json.dumps({"error": str(e)})
        db.commit()

    # urlscan
    if us_enabled:
        us_check = ExternalCheckResult(link_id=link_rec.id, service="urlscan", status="pending")
        db.add(us_check)
        db.commit()

        try:
            scan_uuid = await urlscan.submit_scan(url)
            if scan_uuid:
                us_check.submission_id = scan_uuid
                us_check.status = "polling"
                db.commit()

                result = await urlscan.poll_result(scan_uuid)
                summary = urlscan.summarize_result(result)
                us_check.raw_result = json.dumps(result) if result else None
                us_check.summary = json.dumps(summary)
                us_check.score = summary.get("score", 0)
                us_check.verdict = "malicious" if summary.get("malicious") else "clean"
                us_check.status = "done" if result else "timeout"
            else:
                us_check.status = "error"
                us_check.summary = json.dumps({"error": "Submission failed or API key missing"})
        except Exception as e:
            logger.warning("urlscan error for %s: %s", url[:60], e)
            us_check.status = "error"
            us_check.summary = json.dumps({"error": str(e)})
        db.commit()
