"""urlscan.io scanning client."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

URLSCAN_BASE = "https://urlscan.io/api/v1"


def _headers() -> dict[str, str]:
    return {
        "API-Key": settings.urlscan_api_key,
        "Content-Type": "application/json",
    }


async def submit_scan(url: str) -> str | None:
    """Submit a URL to urlscan.io. Returns the scan UUID."""
    if not settings.urlscan_api_key:
        logger.warning("urlscan API key not configured, skipping.")
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{URLSCAN_BASE}/scan/",
                headers=_headers(),
                json={
                    "url": url,
                    "visibility": settings.urlscan_visibility,
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return data.get("uuid")
            logger.warning("urlscan submit failed (%s): %s", resp.status_code, resp.text[:200])
            return None
    except Exception as e:
        logger.error("urlscan submit error: %s", e)
        return None


async def poll_result(scan_uuid: str) -> dict | None:
    """Poll urlscan.io for scan result with retries."""
    if not settings.urlscan_api_key or not scan_uuid:
        return None

    # urlscan needs a short initial delay
    await asyncio.sleep(10)

    elapsed = 10
    interval = settings.poll_interval_seconds
    async with httpx.AsyncClient(timeout=30) as client:
        while elapsed < settings.max_poll_seconds:
            try:
                resp = await client.get(f"{URLSCAN_BASE}/result/{scan_uuid}/")
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 404:
                    pass  # Not ready yet
                else:
                    logger.warning("urlscan poll (%s): %s", resp.status_code, resp.text[:100])
            except Exception as e:
                logger.warning("urlscan poll error: %s", e)

            await asyncio.sleep(interval)
            elapsed += interval

    logger.warning("urlscan poll timed out for %s", scan_uuid)
    return None


def summarize_result(data: dict | None) -> dict:
    """Extract compact summary from urlscan result."""
    if not data:
        return {"malicious": False, "score": 0, "categories": [], "brands": []}

    verdicts = data.get("verdicts", {})
    overall = verdicts.get("overall", {})

    return {
        "malicious": overall.get("malicious", False),
        "score": overall.get("score", 0),
        "categories": overall.get("categories", []),
        "brands": [b.get("name", "") for b in overall.get("brands", [])],
    }
