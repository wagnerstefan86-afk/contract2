"""LLM client abstraction using litellm.

Reads provider/model/key from the Einstellung table at call time.
Falls back to environment variables if DB settings are missing.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

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
    """
    model = _build_model_string(config)

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

    logger.info(f"LLM-Aufruf: model={model}, temp={temperature}, tokens={max_tokens}")

    response = await litellm.acompletion(**kwargs)
    content = response.choices[0].message.content or ""
    return content.strip()


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
