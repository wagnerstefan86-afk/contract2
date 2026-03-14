"""LLM client abstraction using litellm.

Reads provider/model/key from the Einstellung table at call time.
Falls back to environment variables if DB settings are missing.

Includes rate-limiting, retry with exponential backoff + jitter,
and token estimation for safe dispatch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field

import litellm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.einstellung import Einstellung

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


@dataclass
class LLMConfig:
    provider: str  # e.g. "openai", "anthropic", "azure"
    model: str     # e.g. "gpt-4o", "claude-sonnet-4-20250514"
    api_key: str
    base_url: str | None = None
    # Rate limiting configuration
    max_rpm: int = 60          # max requests per minute
    max_concurrent: int = 5     # max concurrent requests
    max_retries: int = 4        # max retries on 429/5xx


# ---------------------------------------------------------------------------
# Simple concurrency / rate limiter
# ---------------------------------------------------------------------------

class LLMThrottle:
    """Simple token-aware throttle for LLM requests.

    Limits concurrent requests and enforces a minimum delay between requests
    to stay within RPM limits.
    """

    def __init__(self, max_concurrent: int = 5, min_interval: float = 1.0):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._min_interval = min_interval
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()
        self._total_requests: int = 0
        self._total_tokens_est: int = 0

    async def acquire(self, token_estimate: int = 0):
        """Acquire a slot, waiting if necessary."""
        await self._semaphore.acquire()
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
            self._total_requests += 1
            self._total_tokens_est += token_estimate

    def release(self):
        self._semaphore.release()

    @property
    def stats(self) -> dict:
        return {
            "total_requests": self._total_requests,
            "total_tokens_estimated": self._total_tokens_est,
        }


# Global throttle instance (initialized lazily per config)
_throttle: LLMThrottle | None = None


def get_throttle(config: LLMConfig) -> LLMThrottle:
    """Get or create the global throttle instance."""
    global _throttle
    if _throttle is None:
        min_interval = 60.0 / max(config.max_rpm, 1)
        _throttle = LLMThrottle(
            max_concurrent=config.max_concurrent,
            min_interval=min_interval,
        )
    return _throttle


def estimate_tokens(text: str) -> int:
    """Rough token count estimate: ~4 chars per token for mixed de/en text."""
    return len(text) // 4


async def lade_llm_config(db: AsyncSession) -> LLMConfig:
    """Load LLM config from Einstellung table, fall back to env vars."""
    result = await db.execute(select(Einstellung))
    settings_map = {e.schluessel: e.wert for e in result.scalars().all()}

    provider = settings_map.get("llm_anbieter", os.getenv("LLM_PROVIDER", "openai"))
    model = settings_map.get("llm_modell", os.getenv("LLM_MODEL", "gpt-4o"))
    api_key = settings_map.get("llm_api_schluessel", os.getenv("LLM_API_KEY", ""))
    base_url = settings_map.get("llm_basis_url", os.getenv("LLM_BASE_URL")) or None

    if not api_key:
        raise ValueError(
            "Kein LLM API-Schlüssel konfiguriert. "
            "Bitte unter Einstellungen oder als Umgebungsvariable LLM_API_KEY setzen."
        )

    return LLMConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)


def _build_model_string(config: LLMConfig) -> str:
    """Build the litellm model string from config."""
    # litellm uses provider/model format for some providers
    if config.provider == "openai" or config.base_url:
        return config.model
    elif config.provider == "anthropic":
        return f"anthropic/{config.model}"
    elif config.provider == "azure":
        return f"azure/{config.model}"
    else:
        return f"{config.provider}/{config.model}"


async def llm_completion(
    config: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """Send a completion request and return the response text.

    Uses litellm for provider abstraction.
    Includes retry with exponential backoff + jitter on 429/5xx errors.
    Respects concurrency limits via LLMThrottle.
    """
    model = _build_model_string(config)
    throttle = get_throttle(config)
    token_est = estimate_tokens(system_prompt + user_prompt)

    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_key": config.api_key,
    }
    if config.base_url:
        kwargs["api_base"] = config.base_url

    last_error: Exception | None = None

    for attempt in range(config.max_retries + 1):
        await throttle.acquire(token_estimate=token_est)
        try:
            logger.info(
                f"LLM-Aufruf: model={model}, temp={temperature}, "
                f"tokens={max_tokens}, attempt={attempt + 1}"
            )
            response = await litellm.acompletion(**kwargs)
            content = response.choices[0].message.content or ""
            return content.strip()
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = (
                "429" in error_str
                or "rate" in error_str
                or "500" in error_str
                or "502" in error_str
                or "503" in error_str
                or "timeout" in error_str
            )
            if is_retryable and attempt < config.max_retries:
                # Exponential backoff: 2s, 4s, 8s, 16s + jitter
                delay = (2 ** (attempt + 1)) + random.uniform(0, 1)
                logger.warning(
                    f"LLM-Aufruf fehlgeschlagen (Versuch {attempt + 1}/{config.max_retries + 1}): "
                    f"{e}. Retry in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
            else:
                raise
        finally:
            throttle.release()

    raise last_error or RuntimeError("LLM-Aufruf fehlgeschlagen nach allen Retries")


async def llm_json_completion(
    config: LLMConfig,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> list[dict]:
    """Send a completion request expecting a JSON array response.

    Extracts JSON from the response even if wrapped in markdown code blocks.
    Returns an empty list if parsing fails.
    """
    raw = await llm_completion(config, system_prompt, user_prompt, temperature, max_tokens)

    # Try to extract JSON array from response
    # Handle markdown code blocks
    if "```" in raw:
        # Extract content between first ``` and last ```
        parts = raw.split("```")
        for part in parts[1:]:
            # Skip the language identifier line (e.g., "json\n")
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("["):
                raw = cleaned
                break

    # Find the JSON array
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        logger.warning(f"Kein JSON-Array in LLM-Antwort gefunden. Antwort: {raw[:200]}...")
        return []

    json_str = raw[start:end + 1]
    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, list):
            return parsed
        return []
    except json.JSONDecodeError as e:
        logger.warning(f"JSON-Parsing fehlgeschlagen: {e}. Rohtext: {json_str[:200]}...")
        return []
