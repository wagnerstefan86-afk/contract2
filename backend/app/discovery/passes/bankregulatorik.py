"""Pass 4: Bankregulatorik — banking regulatory risk analysis.

Goal: identify IT-outsourcing risks from a banking regulatory perspective
(KWG, MaRisk, BAIT, DORA). Uses the shared material-risk extraction prompt
with additional regulatory focus. Max 3 findings per segment.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, MATERIAL_RISK_SYSTEM_PROMPT, get_perspective_prompt

logger = logging.getLogger(__name__)

REGULATORY_FOCUS = """

Additional focus — Banking Regulatory perspective (KWG, MaRisk, BAIT, DORA):
You are an IT outsourcing lawyer specialized in banking regulation.
Only report risks that are economically, legally, or operationally relevant
for an IT service provider.

Focus on:
- Unilateral instruction rights
- Regulatory pass-through (obligations that belong to the regulated client)
- Unlimited or unclear liability consequences
- Unclear service scope
- Audit or reporting obligations without limits
- Subcontractor liability
- Exit or data handover obligations
- Incident or BCM obligations

Maximum 3 findings per text segment. Choose only the most material ones.
If the segment contains no material regulatory risk, return NO_FINDING."""

MAX_FINDINGS_PER_SEGMENT = 3


class BankregulatorikPass(DiscoveryPass):
    name = "Bankregulatorik"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
        perspective: str = "provider",
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []
        system_prompt = MATERIAL_RISK_SYSTEM_PROMPT + get_perspective_prompt(perspective) + REGULATORY_FOCUS

        for seg in segments:
            user_prompt = (
                f"Analysiere den folgenden Vertragsabschnitt aus bankregulatorischer Perspektive. "
                f"Maximal 3 wesentliche Risiken. "
                f"Antworte mit NO_FINDING falls kein wesentliches regulatorisches Risiko vorliegt.\n\n"
                f"{seg.fenster_text}"
            )

            items = await llm_json_completion(
                config=config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )

            # Limit to max findings per segment
            findings = self._parse_findings(
                items[:MAX_FINDINGS_PER_SEGMENT] if len(items) > MAX_FINDINGS_PER_SEGMENT else items,
                self.name, [seg.id],
                segment_text=seg.fenster_text,
            )

            if len(items) > MAX_FINDINGS_PER_SEGMENT:
                logger.warning(
                    f"Bankregulatorik-Pass: LLM lieferte {len(items)} Findings, "
                    f"auf {MAX_FINDINGS_PER_SEGMENT} begrenzt"
                )

            all_findings.extend(findings)

        logger.info(f"Bankregulatorik-Pass: {len(all_findings)} Fundstellen insgesamt")
        return all_findings
