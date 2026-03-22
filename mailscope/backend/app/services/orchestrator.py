"""Background orchestrator: runs the full analysis pipeline for a job."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from urllib.parse import urlparse

from app.config import settings
from app.database import SessionLocal
from app.models import AnalysisJob, ExtractedLink, ExternalCheckResult, LlmAssessment
from app.services import (
    header_analyzer,
    link_analyzer,
    link_extractor,
    llm_client,
    parser,
    url_normalizer,
    virustotal,
    urlscan,
)

logger = logging.getLogger(__name__)


def _update_status(db, job: AnalysisJob, status: str):
    job.status = status
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

        # --- Step 1: Parse ---
        _update_status(db, job, "parsing")
        try:
            parsed = parser.parse_email_file(file_path, extension)
        except Exception as e:
            job.status = "error"
            job.error_message = f"Fehler beim Parsen: {str(e)}"
            db.commit()
            return
        finally:
            # Clean up temp file
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
        _update_status(db, job, "extracting")
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

        # --- Step 4: External scans ---
        _update_status(db, job, "scanning")
        scan_tasks = []
        for link_rec in link_records:
            scan_tasks.append(_scan_link(db, link_rec))
        if scan_tasks:
            await asyncio.gather(*scan_tasks)
        db.commit()

        # --- Step 5: LLM assessment ---
        _update_status(db, job, "analyzing")
        link_analyses = []
        for link_rec in link_records:
            db.refresh(link_rec)
            la = {
                "url": link_rec.normalized_url,
                "hostname": link_rec.final_hostname,
                "flags": json.loads(link_rec.link_findings) if link_rec.link_findings else {},
            }
            for check in link_rec.checks:
                if check.summary:
                    la[f"{check.service}_summary"] = json.loads(check.summary)
            link_analyses.append(la)

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
        )

        assessment = await llm_client.get_assessment(payload)
        if assessment:
            llm_rec = LlmAssessment(
                job_id=job_id,
                classification=assessment.get("classification"),
                risk_score=assessment.get("risk_score"),
                confidence=assessment.get("confidence"),
                recommended_action=assessment.get("recommended_action"),
                rationale=assessment.get("rationale"),
                evidence=json.dumps(assessment.get("evidence", []), ensure_ascii=False),
                analyst_summary=assessment.get("analyst_summary"),
                raw_response=json.dumps(assessment, ensure_ascii=False),
            )
            db.add(llm_rec)
        else:
            logger.warning("LLM assessment returned no result for job %s", job_id)

        _update_status(db, job, "done")
        logger.info("Analysis complete for job %s", job_id)

    except Exception as e:
        logger.exception("Pipeline error for job %s", job_id)
        try:
            job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
            if job:
                job.status = "error"
                job.error_message = f"Pipeline-Fehler: {str(e)}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


async def _scan_link(db, link_rec: ExtractedLink):
    """Run VT and urlscan for a single link."""
    url = link_rec.normalized_url

    # VirusTotal
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
        vt_check.status = "error"
        vt_check.summary = json.dumps({"error": str(e)})
    db.commit()

    # urlscan
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
        us_check.status = "error"
        us_check.summary = json.dumps({"error": str(e)})
    db.commit()
