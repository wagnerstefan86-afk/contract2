"""Pass 1: Breite Ersterfassung — broad initial scan.

Goal: scan every segment for material contractual risks from the
Auftragnehmer perspective. Uses the shared material-risk extraction prompt.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, MATERIAL_RISK_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

PASS_CONTEXT = """

Additional context for this pass:
You are reviewing an IT outsourcing contract from the perspective of the contractor (Auftragnehmer / IT service provider).
Focus areas for this broad initial scan:
- Deadlines and response times (unrealistically short?)
- Penalty clauses (disproportionate?)
- Liability provisions (missing caps? unlimited?)
- Warranties and representations (overly broad?)
- One-sided obligations or restrictions
- Unilateral rights of the client (termination, changes, instructions)
- References to external documents or standards (uncontrollable?)
- Missing provisions (what is not regulated can be dangerous)
- Auto-renewal and long lock-in periods
- Transition obligations at contract end"""

SYSTEM_PROMPT = MATERIAL_RISK_SYSTEM_PROMPT + PASS_CONTEXT


class BreitPass(DiscoveryPass):
    name = "Breite Ersterfassung"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []

        for seg in segments:
            logger.info(f"Breit-Pass: Segment {seg.id}")
            user_prompt = (
                f"Analyze the following contract section. "
                f"Extract only MATERIAL contractual risks for the contractor. "
                f"Return NO_FINDING if no material risk exists.\n\n"
                f"{seg.fenster_text}"
            )

            items = await llm_json_completion(
                config=config,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
            )

            findings = self._parse_findings(items, self.name, [seg.id],
                                            segment_text=seg.fenster_text)
            logger.info(f"Breit-Pass: {len(findings)} Fundstellen in {seg.id}")
            all_findings.extend(findings)

        return all_findings
