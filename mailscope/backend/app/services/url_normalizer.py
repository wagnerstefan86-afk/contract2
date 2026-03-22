"""URL normalization: decode entities, unwrap SafeLinks, strip tracking, dedup."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from app.services.link_extractor import RawLink

# Microsoft SafeLinks pattern
_SAFELINKS_RE = re.compile(
    r"https?://[\w.-]*safelinks\.protection\.outlook\.com/?\?", re.IGNORECASE
)

# Common redirect parameters
_REDIRECT_PARAMS = {"url", "u", "redirect", "redirect_uri", "goto", "target", "link", "dest"}

# Tracking parameters to strip
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "oly_", "s_kwcid", "msclkid")


def _decode_html_entities(url: str) -> str:
    return html.unescape(url)


def _unwrap_safelinks(url: str) -> str:
    """Unwrap Microsoft SafeLinks wrapped URLs."""
    if not _SAFELINKS_RE.match(url):
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "url" in qs:
        return unquote(qs["url"][0])
    return url


def _unwrap_redirects(url: str) -> str:
    """Attempt to unwrap common redirect parameters."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for param in _REDIRECT_PARAMS:
        if param in qs:
            candidate = unquote(qs[param][0])
            if candidate.startswith("http://") or candidate.startswith("https://"):
                return candidate
    return url


def _strip_tracking_params(url: str) -> str:
    """Remove utm_* and other tracking query parameters."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    cleaned = {
        k: v
        for k, v in qs.items()
        if not any(k.lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    }
    new_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return urlunparse(parsed._replace(query=new_query))


def normalize_url(url: str) -> str:
    """Apply full normalization pipeline to a URL."""
    url = _decode_html_entities(url)
    url = _unwrap_safelinks(url)
    url = _unwrap_redirects(url)
    url = _strip_tracking_params(url)
    # Remove trailing slash for consistency
    if url.endswith("/") and urlparse(url).path == "/":
        url = url.rstrip("/")
    return url


def deduplicate_links(links: list[RawLink]) -> list[tuple[str, RawLink]]:
    """Normalize all links and deduplicate by normalized URL.

    Returns list of (normalized_url, original_link) tuples, keeping
    the first occurrence.
    """
    seen: dict[str, RawLink] = {}
    for link in links:
        norm = normalize_url(link.url)
        if norm not in seen:
            seen[norm] = link
    return list(seen.items())
