"""LLM client for security assessment."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent / "prompts" / "assessment.txt"


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
) -> dict:
    """Build the structured payload sent to the LLM."""
    return {
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


async def get_assessment(payload: dict) -> dict | None:
    """Send analysis payload to LLM and get structured assessment."""
    if not settings.openai_api_key:
        logger.error("OpenAI API key not configured")
        return None

    template = _load_prompt_template()
    user_content = f"{template}\n\n---\nAnalyse-Daten (JSON):\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"

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
                    "messages": [
                        {
                            "role": "system",
                            "content": "Du bist ein IT-Sicherheitsanalyst. Antworte ausschließlich mit validem JSON.",
                        },
                        {"role": "user", "content": user_content},
                    ],
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
