"""Link analysis heuristics."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Suspicious TLDs
_SUSPICIOUS_TLDS = {
    ".xyz", ".top", ".click", ".buzz", ".gq", ".ml", ".cf", ".tk", ".ga",
    ".pw", ".cc", ".icu", ".cam", ".rest", ".surf", ".monster",
}

# Known URL shorteners
_SHORTENERS = {
    "bit.ly", "t.co", "goo.gl", "tinyurl.com", "ow.ly", "is.gd",
    "buff.ly", "cutt.ly", "rb.gy", "shorturl.at", "tiny.cc",
}


def analyze_link(
    original_url: str,
    normalized_url: str,
    display_text: str = "",
) -> dict:
    """Analyze a single link and return heuristic flags."""
    parsed = urlparse(normalized_url)
    hostname = parsed.hostname or ""

    # IP literal check
    ip_literal = bool(re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", hostname))

    # Punycode
    punycode = hostname.startswith("xn--") or any(part.startswith("xn--") for part in hostname.split("."))

    # Suspicious TLD
    suspicious_tld = any(hostname.endswith(tld) for tld in _SUSPICIOUS_TLDS)

    # URL shortener
    url_shortener = hostname.lower() in _SHORTENERS

    # Display text mismatch: display text looks like a URL but points elsewhere
    display_text_mismatch = False
    if display_text:
        dt = display_text.strip()
        if dt.startswith("http://") or dt.startswith("https://"):
            dt_parsed = urlparse(dt)
            if dt_parsed.hostname and dt_parsed.hostname != hostname:
                display_text_mismatch = True

    # Tracking-heavy: lots of query params
    tracking_heavy = len(parsed.query) > 200

    return {
        "final_hostname": hostname,
        "display_text_mismatch": display_text_mismatch,
        "suspicious_tld": suspicious_tld,
        "ip_literal": ip_literal,
        "punycode": punycode,
        "url_shortener": url_shortener,
        "tracking_heavy": tracking_heavy,
    }
