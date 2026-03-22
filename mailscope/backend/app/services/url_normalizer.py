"""URL normalization: decode entities, unwrap SafeLinks, strip tracking, dedup."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

from app.services.link_extractor import RawLink

# Microsoft SafeLinks patterns (multiple variants)
_SAFELINKS_RE = re.compile(
    r"https?://[\w.-]*safelinks\.protection\.outlook\.com", re.IGNORECASE
)

# Google redirect
_GOOGLE_REDIRECT_RE = re.compile(
    r"https?://www\.google\.com/url\?", re.IGNORECASE
)

# Common redirect parameters (order matters: prefer more specific first)
_REDIRECT_PARAMS = ["url", "u", "redirect", "redirect_uri", "goto", "target", "link", "dest", "q"]

# Tracking parameters to strip
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "gclsrc", "mc_cid", "mc_eid",
    "oly_anon_id", "oly_enc_id", "s_kwcid", "msclkid",
    "_hsenc", "_hsmi", "hsa_cam", "hsa_grp", "hsa_mt", "hsa_src", "hsa_ad",
    "hsa_acc", "hsa_net", "hsa_ver", "hsa_la", "hsa_ol", "hsa_kw", "hsa_tgt",
    "vero_id", "vero_conv",
}
_TRACKING_PREFIXES = ("utm_", "hsa_", "oly_")


def _decode_html_entities(url: str) -> str:
    """Decode HTML entities like &amp; in URLs."""
    return html.unescape(url)


def _unwrap_safelinks(url: str) -> str:
    """Unwrap Microsoft SafeLinks wrapped URLs."""
    if not _SAFELINKS_RE.match(url):
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "url" in qs:
        return unquote(qs["url"][0])
    # Some SafeLinks encode the target differently
    if "data" in qs:
        # Try to extract URL from data param
        data = unquote(qs["data"][0])
        url_match = re.search(r'https?://[^\s|]+', data)
        if url_match:
            return url_match.group(0)
    return url


def _unwrap_google_redirect(url: str) -> str:
    """Unwrap Google redirect URLs."""
    if not _GOOGLE_REDIRECT_RE.match(url):
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for param in ("q", "url", "u"):
        if param in qs:
            candidate = unquote(qs[param][0])
            if candidate.startswith("http://") or candidate.startswith("https://"):
                return candidate
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
        if k.lower() not in _TRACKING_PARAMS
        and not any(k.lower().startswith(prefix) for prefix in _TRACKING_PREFIXES)
    }
    new_query = urlencode(cleaned, doseq=True) if cleaned else ""
    return urlunparse(parsed._replace(query=new_query))


def _normalize_scheme_and_host(url: str) -> str:
    """Lowercase scheme and hostname for canonical form."""
    parsed = urlparse(url)
    if parsed.hostname:
        normalized = parsed._replace(
            netloc=parsed.netloc.lower(),
            scheme=parsed.scheme.lower(),
        )
        return urlunparse(normalized)
    return url


def normalize_url(url: str) -> str:
    """Apply full normalization pipeline to a URL."""
    url = url.strip()
    url = _decode_html_entities(url)
    url = _unwrap_safelinks(url)
    url = _unwrap_google_redirect(url)
    url = _unwrap_redirects(url)
    url = _strip_tracking_params(url)
    url = _normalize_scheme_and_host(url)
    # Remove trailing slash for consistency on root paths
    if url.endswith("/") and urlparse(url).path == "/":
        url = url.rstrip("/")
    # Remove fragment
    parsed = urlparse(url)
    if parsed.fragment:
        url = urlunparse(parsed._replace(fragment=""))
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
