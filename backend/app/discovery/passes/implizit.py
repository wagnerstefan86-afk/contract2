"""Pass 3: Implizite Pflichten — hidden obligations scan.

Goal: find obligations NOT explicitly stated but implied through vague
language, catch-all clauses, definitions, external references, or
combinations of clauses. Uses the shared material-risk extraction prompt
with additional focus on implicit risks.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, MATERIAL_RISK_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

IMPLICIT_FOCUS = """

Additional focus — Implicit & Hidden Obligations:
Look specifically for obligations NOT explicitly listed but implied through:

1. VAGUE FORMULATIONS that silently expand scope:
   - "reasonable measures", "best efforts", "to the best of knowledge"
   - "market-standard", "state of the art"
   - "all", "any and all required"

2. DEFINITIONS that smuggle in obligations:
   - Broad definitions of "Service" or "Deliverable"
   - "including but not limited to..."
   - Definitions referencing external documents

3. CATCH-ALL CLAUSES:
   - "any other services required to achieve the contract purpose"
   - "all related activities"

4. EXTERNAL REFERENCES:
   - References to standards (ISO, BSI, NIST) with extensive obligations
   - References to client policies "in their current version" (blank reference!)
   - References to appendices that are not fully specified

5. COMBINATION EFFECTS:
   - Clauses harmless alone but together creating overreach
   - General cooperation obligations + specific SLAs = implicit 24/7 availability
   - Broad scope + fixed price = cost risk from scope creep

6. MISSING PROVISIONS:
   - No liability cap defined
   - No change management procedure
   - No cost allocation for regulatory changes

Only create findings for actual material risks. Not every vague formulation is automatically a risk."""

SYSTEM_PROMPT = MATERIAL_RISK_SYSTEM_PROMPT + IMPLICIT_FOCUS


class ImplizitPass(DiscoveryPass):
    name = "Implizite Pflichten"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []

        # Send full text if it fits, otherwise process larger segment windows
        MAX_CHARS = 12000  # roughly ~3k tokens

        if len(full_text) <= MAX_CHARS:
            logger.info("Implizit-Pass: Gesamttext wird analysiert")
            items = await llm_json_completion(
                config=config,
                system_prompt=SYSTEM_PROMPT,
                user_prompt=(
                    "Analyze the following contract for IMPLICIT and HIDDEN obligations "
                    "for the contractor. Only identify material risks. "
                    "Look for missing provisions, open references, and combination effects. "
                    "Return NO_FINDING if no material risk exists.\n\n"
                    f"{full_text}"
                ),
                temperature=0.4,
                max_tokens=4096,
            )
            findings = self._parse_findings(items, self.name, ["full-text"],
                                            segment_text=full_text[:2000])
            all_findings.extend(findings)
        else:
            logger.info(f"Implizit-Pass: Text zu lang ({len(full_text)} Zeichen), segmentweise Analyse")
            for seg in segments:
                items = await llm_json_completion(
                    config=config,
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=(
                        "Analyze the following contract section for IMPLICIT and HIDDEN "
                        "obligations for the contractor. Only material risks. "
                        "Return NO_FINDING if no material risk exists.\n\n"
                        f"{seg.fenster_text}"
                    ),
                    temperature=0.4,
                    max_tokens=4096,
                )
                findings = self._parse_findings(items, self.name, [seg.id],
                                                segment_text=seg.fenster_text)
                all_findings.extend(findings)

        logger.info(f"Implizit-Pass: {len(all_findings)} Fundstellen insgesamt")
        return all_findings
