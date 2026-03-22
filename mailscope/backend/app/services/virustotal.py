"""VirusTotal URL scanning client."""

from __future__ import annotations

import asyncio
import base64
import logging
from urllib.parse import quote

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

VT_BASE = "https://www.virustotal.com/api/v3"


def _headers() -> dict[str, str]:
    return {"x-apikey": settings.virustotal_api_key}


async def submit_url(url: str) -> str | None:
    """Submit a URL to VirusTotal for analysis. Returns the analysis ID."""
    if not settings.virustotal_api_key:
        logger.warning("VirusTotal API key not configured, skipping.")
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{VT_BASE}/urls",
                headers=_headers(),
                data={"url": url},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("data", {}).get("id")
            logger.warning("VT submit failed (%s): %s", resp.status_code, resp.text[:200])
            return None
    except Exception as e:
        logger.error("VT submit error: %s", e)
        return None


async def get_url_report(url: str) -> dict | None:
    """Get existing report for a URL by its ID (base64-encoded URL without padding)."""
    if not settings.virustotal_api_key:
        return None
    url_id = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{VT_BASE}/urls/{url_id}",
                headers=_headers(),
            )
            if resp.status_code == 200:
                return resp.json()
            return None
    except Exception as e:
        logger.error("VT report error: %s", e)
        return None


async def poll_analysis(analysis_id: str) -> dict | None:
    """Poll for analysis completion with retries."""
    if not settings.virustotal_api_key or not analysis_id:
        return None

    elapsed = 0
    interval = settings.poll_interval_seconds
    async with httpx.AsyncClient(timeout=30) as client:
        while elapsed < settings.max_poll_seconds:
            try:
                resp = await client.get(
                    f"{VT_BASE}/analyses/{analysis_id}",
                    headers=_headers(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("data", {}).get("attributes", {}).get("status")
                    if status == "completed":
                        return data
            except Exception as e:
                logger.warning("VT poll error: %s", e)

            await asyncio.sleep(interval)
            elapsed += interval

    logger.warning("VT poll timed out for %s", analysis_id)
    return None


def summarize_result(data: dict | None) -> dict:
    """Extract a compact summary from VT analysis result."""
    if not data:
        return {"malicious": 0, "suspicious": 0, "harmless": 0, "undetected": 0, "total": 0}

    stats = (
        data.get("data", {})
        .get("attributes", {})
        .get("stats", {})
    )
    if not stats:
        # Try results format
        results = data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
        stats = results

    return {
        "malicious": stats.get("malicious", 0),
        "suspicious": stats.get("suspicious", 0),
        "harmless": stats.get("harmless", 0),
        "undetected": stats.get("undetected", 0),
        "total": sum(stats.values()) if stats else 0,
    }
