"""Deterministic header analysis heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass
class HeaderFinding:
    id: str
    severity: str  # info | warning | critical
    title: str
    detail: str


def _get_header(headers: dict[str, list[str]], key: str) -> str:
    vals = headers.get(key.lower(), [])
    return vals[0] if vals else ""


def _extract_domain(address: str) -> str:
    """Extract domain from email address string."""
    match = re.search(r"@([\w.-]+)", address)
    return match.group(1).lower() if match else ""


def _extract_display_name(address: str) -> str:
    match = re.match(r'^"?([^"<]+)"?\s*<', address)
    return match.group(1).strip() if match else ""


def analyze_headers(
    structured_headers: dict[str, list[str]],
    sender: str,
    reply_to: str,
    return_path: str,
    authentication_results: str,
    received_chain: list[str],
    all_link_hostnames: list[str],
) -> list[dict[str, Any]]:
    """Run all heuristic checks and return findings."""
    findings: list[HeaderFinding] = []
    finding_counter = 0

    def _add(severity: str, title: str, detail: str):
        nonlocal finding_counter
        finding_counter += 1
        findings.append(HeaderFinding(id=f"H{finding_counter:03d}", severity=severity, title=title, detail=detail))

    # SPF
    auth = authentication_results.lower()
    if "spf=fail" in auth or "spf=softfail" in auth:
        _add("critical", "SPF-Prüfung fehlgeschlagen", f"Authentication-Results enthält SPF-Fehler: {authentication_results[:200]}")
    elif "spf=pass" in auth:
        _add("info", "SPF-Prüfung bestanden", "SPF-Authentifizierung erfolgreich.")
    elif authentication_results:
        _add("warning", "SPF-Ergebnis unklar", f"Kein eindeutiges SPF-Ergebnis gefunden: {authentication_results[:200]}")

    # DKIM
    if "dkim=fail" in auth:
        _add("critical", "DKIM-Prüfung fehlgeschlagen", "DKIM-Signatur ist ungültig.")
    elif "dkim=pass" in auth:
        _add("info", "DKIM-Prüfung bestanden", "DKIM-Signatur gültig.")

    # DMARC
    if "dmarc=fail" in auth:
        _add("critical", "DMARC-Prüfung fehlgeschlagen", "DMARC-Richtlinienprüfung fehlgeschlagen.")
    elif "dmarc=pass" in auth:
        _add("info", "DMARC-Prüfung bestanden", "DMARC-Authentifizierung erfolgreich.")

    # From vs Reply-To mismatch
    from_domain = _extract_domain(sender)
    if reply_to:
        rt_domain = _extract_domain(reply_to)
        if rt_domain and from_domain and rt_domain != from_domain:
            _add("warning", "From/Reply-To Domain-Abweichung", f"From-Domain ({from_domain}) weicht von Reply-To-Domain ({rt_domain}) ab.")

    # From vs Return-Path mismatch
    if return_path:
        rp_domain = _extract_domain(return_path)
        if rp_domain and from_domain and rp_domain != from_domain:
            _add("warning", "From/Return-Path Domain-Abweichung", f"From-Domain ({from_domain}) weicht von Return-Path-Domain ({rp_domain}) ab.")

    # Display name vs domain inconsistency
    display_name = _extract_display_name(sender)
    if display_name and from_domain:
        name_lower = display_name.lower()
        # Check if display name contains a different domain-like pattern
        domain_in_name = re.search(r'[\w.-]+\.\w{2,}', name_lower)
        if domain_in_name:
            name_domain = domain_in_name.group(0)
            if name_domain != from_domain and not from_domain.endswith("." + name_domain):
                _add("warning", "Anzeigename/Domain-Inkonsistenz",
                     f"Anzeigename '{display_name}' enthält '{name_domain}', aber Absender-Domain ist '{from_domain}'.")

    # Bulk/marketing indicators
    bulk_headers = []
    if structured_headers.get("list-unsubscribe"):
        bulk_headers.append("List-Unsubscribe")
    if structured_headers.get("feedback-id"):
        bulk_headers.append("Feedback-ID")
    if structured_headers.get("x-mailer"):
        bulk_headers.append("X-Mailer")
    precedence = _get_header(structured_headers, "precedence")
    if precedence and precedence.lower() in ("bulk", "list"):
        bulk_headers.append(f"Precedence: {precedence}")
    if bulk_headers:
        _add("info", "Massen-/Marketing-Indikatoren", f"Folgende Header deuten auf Newsletter/Marketing hin: {', '.join(bulk_headers)}")

    # Spam confidence headers
    scl = _get_header(structured_headers, "x-ms-exchange-organization-scl")
    if scl:
        try:
            scl_val = int(scl)
            if scl_val >= 5:
                _add("warning", "Hoher Spam-Confidence-Level", f"SCL = {scl_val}")
            else:
                _add("info", "Spam-Confidence-Level", f"SCL = {scl_val}")
        except ValueError:
            pass

    sfv = _get_header(structured_headers, "x-forefront-antispam-report")
    if sfv and "SFV:SPM" in sfv.upper():
        _add("warning", "Antispam-Ergebnis: Spam", f"X-Forefront-Antispam-Report enthält SFV:SPM")

    # Received chain anomalies
    if len(received_chain) > 10:
        _add("warning", "Ungewöhnlich lange Received-Kette", f"Die E-Mail hat {len(received_chain)} Received-Hops durchlaufen.")

    # SafeLinks presence
    for link_host in all_link_hostnames:
        if "safelinks.protection.outlook.com" in link_host:
            _add("info", "SafeLinks-geschützte URLs", "Links sind durch Microsoft SafeLinks geschützt.")
            break

    # Multiple distinct domains in links
    unique_domains = set(all_link_hostnames)
    # Remove common CDN/tracking domains
    if len(unique_domains) > 5:
        _add("info", "Viele verschiedene Link-Domains", f"{len(unique_domains)} unterschiedliche Domains in den Links gefunden: {', '.join(sorted(unique_domains)[:10])}")

    # External tracking links
    tracking_domains = {"click.", "track.", "trk.", "t.co", "bit.ly", "goo.gl", "tinyurl.com"}
    found_tracking = [h for h in all_link_hostnames if any(td in h.lower() for td in tracking_domains)]
    if found_tracking:
        _add("info", "Externe Tracking-Links", f"Tracking-Domains gefunden: {', '.join(set(found_tracking)[:5])}")

    return [{"id": f.id, "severity": f.severity, "title": f.title, "detail": f.detail} for f in findings]
