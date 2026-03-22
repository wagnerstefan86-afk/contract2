"""LLM client for security assessment with retry and fallback."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "assessment.txt"

VALID_CLASSIFICATIONS = {"phishing", "advertising", "legitimate", "suspicious", "unknown"}
VALID_ACTIONS = {"delete", "open_ticket", "verify_via_known_channel", "allow", "manual_review"}


def _load_prompt_template() -> str:
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def build_analysis_payload(
    sender: str,
    reply_to: str,
    return_path: str,
    subject: str,
    date: str,
    authentication_results: str,
    body_text_snippet: str,
    header_findings: list[dict],
    link_analyses: list[dict],
    attachment_metadata: list[dict],
    pre_scores: dict | None = None,
) -> dict:
    """Build the structured payload sent to the LLM."""
    payload = {
        "email_metadata": {
            "from": sender,
            "reply_to": reply_to,
            "return_path": return_path,
            "subject": subject,
            "date": date,
            "authentication_results": authentication_results,
        },
        "body_text_snippet": body_text_snippet[:2000] if body_text_snippet else "",
        "header_findings": header_findings,
        "link_analyses": link_analyses,
        "attachment_metadata": attachment_metadata,
    }
    if pre_scores:
        payload["deterministic_pre_scores"] = pre_scores
    return payload


def _validate_assessment(data: dict) -> dict | None:
    """Validate LLM output structure and values. Returns cleaned dict or None."""
    required = {"classification", "risk_score", "confidence", "recommended_action", "rationale", "evidence", "analyst_summary"}
    if not all(k in data for k in required):
        logger.warning("LLM output missing keys: %s", required - set(data.keys()))
        return None

    if data["classification"] not in VALID_CLASSIFICATIONS:
        logger.warning("Invalid classification: %s", data["classification"])
        return None

    if data["recommended_action"] not in VALID_ACTIONS:
        logger.warning("Invalid recommended_action: %s", data["recommended_action"])
        return None

    try:
        data["risk_score"] = max(0, min(100, int(data["risk_score"])))
        data["confidence"] = max(0, min(100, int(data["confidence"])))
    except (ValueError, TypeError):
        return None

    if not isinstance(data.get("evidence"), list):
        data["evidence"] = []

    return data


async def _call_llm(messages: list[dict]) -> dict | None:
    """Make a single LLM API call. Returns parsed JSON or None."""
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "messages": messages,
                    "temperature": 0.1,
                    "response_format": {"type": "json_object"},
                },
            )

            if resp.status_code != 200:
                logger.error("LLM request failed (%s): %s", resp.status_code, resp.text[:300])
                return None

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)

    except json.JSONDecodeError as e:
        logger.error("LLM returned invalid JSON: %s", e)
        return None
    except Exception as e:
        logger.error("LLM request error: %s", e)
        return None


async def get_assessment(payload: dict) -> tuple[dict | None, str]:
    """Send analysis payload to LLM with retry on malformed output.

    Returns (assessment_dict, source) where source is "llm" or None if failed.
    """
    if not settings.openai_api_key:
        logger.error("OpenAI API key not configured")
        return None, "none"

    template = _load_prompt_template()
    user_content = f"{template}\n\n---\nAnalyse-Daten (JSON):\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"

    messages = [
        {
            "role": "system",
            "content": "Du bist ein IT-Sicherheitsanalyst. Antworte ausschließlich mit validem JSON.",
        },
        {"role": "user", "content": user_content},
    ]

    # First attempt
    raw = await _call_llm(messages)
    if raw:
        validated = _validate_assessment(raw)
        if validated:
            return validated, "llm"

    # Retry with repair prompt
    logger.info("LLM first attempt failed or invalid, retrying with repair prompt")
    repair_messages = messages + [
        {
            "role": "assistant",
            "content": json.dumps(raw) if raw else '{"error": "no response"}',
        },
        {
            "role": "user",
            "content": (
                "Deine vorherige Antwort war ungültig. Antworte erneut mit exakt diesem JSON-Format:\n"
                '{"classification": "...", "risk_score": 0-100, "confidence": 0-100, '
                '"recommended_action": "...", "rationale": "...", "evidence": [...], "analyst_summary": "..."}\n'
                "Erlaubte classification: phishing, advertising, legitimate, suspicious, unknown\n"
                "Erlaubte recommended_action: delete, open_ticket, verify_via_known_channel, allow, manual_review"
            ),
        },
    ]

    raw = await _call_llm(repair_messages)
    if raw:
        validated = _validate_assessment(raw)
        if validated:
            return validated, "llm"

    logger.warning("LLM retry also failed, will use deterministic fallback")
    return None, "none"
