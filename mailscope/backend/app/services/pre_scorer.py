"""Deterministic pre-scoring: compute phishing, advertising, and legitimacy likelihood scores."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class PreScoreResult:
    phishing_score: int = 0
    advertising_score: int = 0
    legitimacy_score: int = 0
    breakdown: dict = field(default_factory=dict)


def compute_pre_scores(
    header_findings: list[dict],
    link_records: list[dict],
    external_checks: list[dict],
) -> PreScoreResult:
    """Compute weighted pre-classification scores from deterministic findings.

    Args:
        header_findings: list of {id, severity, title, detail}
        link_records: list of {display_text_mismatch, suspicious_tld, ip_literal,
                               punycode, url_shortener, tracking_heavy}
        external_checks: list of {service, status, score, verdict, summary}

    Returns:
        PreScoreResult with three 0-100 scores and a breakdown dict.
    """
    phishing = 0.0
    advertising = 0.0
    legitimacy = 0.0
    breakdown: dict[str, float] = {}

    # --- Header-based signals ---
    for hf in header_findings:
        title = hf.get("title", "").lower()
        severity = hf.get("severity", "")

        # Authentication failures
        if "spf" in title and "fehlgeschlagen" in title:
            phishing += 20
            breakdown["spf_fail"] = 20
        elif "spf" in title and "bestanden" in title:
            legitimacy += 10
            breakdown["spf_pass"] = 10

        if "dkim" in title and "fehlgeschlagen" in title:
            phishing += 20
            breakdown["dkim_fail"] = 20
        elif "dkim" in title and "bestanden" in title:
            legitimacy += 10
            breakdown["dkim_pass"] = 10

        if "dmarc" in title and "fehlgeschlagen" in title:
            phishing += 15
            breakdown["dmarc_fail"] = 15
        elif "dmarc" in title and "bestanden" in title:
            legitimacy += 10
            breakdown["dmarc_pass"] = 10

        # Domain mismatches
        if "reply-to" in title and "abweichung" in title:
            phishing += 15
            breakdown["reply_to_mismatch"] = 15

        if "return-path" in title and "abweichung" in title:
            phishing += 10
            breakdown["return_path_mismatch"] = 10

        # Display name inconsistency
        if "anzeigename" in title and "inkonsistenz" in title:
            phishing += 12
            breakdown["display_name_inconsistency"] = 12

        # Bulk/marketing indicators
        if "massen" in title or "marketing" in title:
            advertising += 25
            legitimacy += 5
            breakdown["bulk_headers"] = 25

        # Spam confidence
        if "spam-confidence" in title and severity == "warning":
            phishing += 10
            breakdown["high_scl"] = 10

        if "antispam" in title and "spam" in title:
            phishing += 10
            breakdown["antispam_spam"] = 10

        # Received chain
        if "received-kette" in title:
            phishing += 5
            breakdown["long_received_chain"] = 5

        # Tracking links
        if "tracking" in title:
            advertising += 10
            breakdown["tracking_links"] = 10

    # --- Link-based signals ---
    n_links = len(link_records)
    if n_links > 0:
        mismatches = sum(1 for lr in link_records if lr.get("display_text_mismatch"))
        suspicious_tlds = sum(1 for lr in link_records if lr.get("suspicious_tld"))
        ip_literals = sum(1 for lr in link_records if lr.get("ip_literal"))
        punycode_links = sum(1 for lr in link_records if lr.get("punycode"))
        shorteners = sum(1 for lr in link_records if lr.get("url_shortener"))
        tracking_heavy = sum(1 for lr in link_records if lr.get("tracking_heavy"))

        if mismatches > 0:
            pts = min(20, mismatches * 15)
            phishing += pts
            breakdown["display_text_mismatch"] = pts
        if suspicious_tlds > 0:
            pts = min(15, suspicious_tlds * 10)
            phishing += pts
            breakdown["suspicious_tld"] = pts
        if ip_literals > 0:
            phishing += 15
            breakdown["ip_literal"] = 15
        if punycode_links > 0:
            phishing += 12
            breakdown["punycode"] = 12
        if shorteners > 0:
            pts = min(10, shorteners * 5)
            phishing += pts
            breakdown["url_shortener"] = pts
        if tracking_heavy > 0:
            advertising += min(10, tracking_heavy * 5)
            breakdown["tracking_heavy_links"] = min(10, tracking_heavy * 5)

    # --- External check signals ---
    vt_malicious_total = 0
    vt_suspicious_total = 0
    urlscan_malicious = False

    for ec in external_checks:
        service = ec.get("service", "")
        status = ec.get("status", "")
        verdict = ec.get("verdict", "")
        summary = ec.get("summary") or {}
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except (json.JSONDecodeError, TypeError):
                summary = {}

        if service == "virustotal" and status == "done":
            vt_malicious_total += summary.get("malicious", 0)
            vt_suspicious_total += summary.get("suspicious", 0)
        elif service == "urlscan" and status == "done":
            if summary.get("malicious") or verdict == "malicious":
                urlscan_malicious = True

    if vt_malicious_total > 0:
        pts = min(30, vt_malicious_total * 10)
        phishing += pts
        breakdown["vt_malicious"] = pts
    if vt_suspicious_total > 0:
        pts = min(15, vt_suspicious_total * 5)
        phishing += pts
        breakdown["vt_suspicious"] = pts
    if urlscan_malicious:
        phishing += 20
        breakdown["urlscan_malicious"] = 20

    # --- Normalize to 0-100 ---
    phishing_score = min(100, max(0, int(phishing)))
    advertising_score = min(100, max(0, int(advertising)))
    legitimacy_score = min(100, max(0, int(legitimacy)))

    return PreScoreResult(
        phishing_score=phishing_score,
        advertising_score=advertising_score,
        legitimacy_score=legitimacy_score,
        breakdown=breakdown,
    )


def build_deterministic_assessment(scores: PreScoreResult, header_findings: list[dict]) -> dict:
    """Build a fallback deterministic assessment when LLM is unavailable or fails."""
    evidence = []
    for hf in header_findings:
        sev = hf.get("severity", "")
        if sev in ("critical", "warning"):
            evidence.append(f"{hf['title']}: {hf['detail'][:100]}")

    if scores.phishing_score >= 60:
        classification = "suspicious"
        risk_score = scores.phishing_score
        action = "open_ticket"
        rationale = (
            f"Deterministische Analyse ergibt einen Phishing-Score von {scores.phishing_score}. "
            "Mehrere Indikatoren deuten auf potenzielle Gefahr hin. Manuelle Prüfung dringend empfohlen."
        )
    elif scores.advertising_score >= 30 and scores.phishing_score < 30:
        classification = "advertising"
        risk_score = max(10, scores.phishing_score)
        action = "allow"
        rationale = (
            f"Deterministische Analyse ergibt Marketing-/Newsletter-Merkmale (Score: {scores.advertising_score}). "
            "Kein starker Phishing-Verdacht erkennbar."
        )
    elif scores.legitimacy_score >= 20 and scores.phishing_score < 20:
        classification = "legitimate"
        risk_score = max(5, scores.phishing_score)
        action = "allow"
        rationale = (
            "Authentifizierungsprüfungen bestanden. Keine verdächtigen Merkmale erkannt."
        )
    else:
        classification = "suspicious"
        risk_score = max(40, scores.phishing_score)
        action = "manual_review"
        rationale = (
            "Die Evidenzlage ist nicht eindeutig. Manuelle Prüfung empfohlen."
        )

    confidence = min(80, 30 + abs(scores.phishing_score - scores.advertising_score))

    return {
        "classification": classification,
        "risk_score": risk_score,
        "confidence": confidence,
        "recommended_action": action,
        "rationale": rationale,
        "evidence": evidence[:10],
        "analyst_summary": (
            f"Automatische Bewertung (ohne KI): Klassifikation={classification}, "
            f"Risiko={risk_score}, Empfehlung={action}."
        ),
    }
