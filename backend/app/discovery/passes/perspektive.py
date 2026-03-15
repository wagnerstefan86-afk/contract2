"""Pass 2: Perspektivische Vertiefung — domain-specific expert lenses.

Runs multiple sub-passes, each with a specialized perspective that
may catch material risks the broad pass missed. Uses the shared
material-risk extraction prompt with domain-specific additions.
"""

from __future__ import annotations

import logging

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import DiscoveryPass, RawFinding, MATERIAL_RISK_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Each perspective: (name, additional focus instructions)
PERSPEKTIVEN = [
    (
        "Informationssicherheit",
        """Additional focus — Information Security perspective:
- Encryption requirements that are hard to fulfill or unspecified
- Incident response obligations with unrealistic deadlines (< 24h)
- Security certification requirements (ISO 27001, SOC2, C5)
- Data deletion obligations and proof-of-deletion requirements
- Penetration testing or security audits the contractor must tolerate
- Data residency, network separation requirements
- Obligations to comply with client security standards (that can change!)
- "State of the art" formulations in security requirements""",
    ),
    (
        "BCM / Betrieb / Resilienz",
        """Additional focus — Business Continuity & Operations perspective:
- SLA obligations with high availability requirements (99.9%+ is problematic)
- Unrealistic RTO/RPO targets
- BCM/DR plan obligations and regular testing requirements
- Cumulative penalties or service credits
- Capacity guarantees and scaling obligations
- Obligations when subcontractors fail
- Geo-redundancy or redundant system requirements
- Maintenance window restrictions
- One-sided priority classifications by the client""",
    ),
    (
        "Compliance / Regulatorik",
        """Additional focus — Regulatory Compliance perspective:
- Regulatory pass-through: obligations that belong to the client but are imposed on the contractor
- GDPR obligations exceeding standard scope
- Industry-specific regulations (BAIT, VAIT, DORA, NIS2, KRITIS) — contractor is often NOT a regulated entity!
- Blanket instruction rights that can change
- Obligation to adapt to changing regulations at OWN COST
- Blanket compliance obligations ("all requirements applicable to the client")
- References to regulatory circulars that can change""",
    ),
    (
        "Audit / Reporting / Nachweise",
        """Additional focus — Audit & Reporting perspective:
- Client audit rights (on-site, remote, unannounced)
- Third-party audit rights (auditors, regulators)
- Unrestricted access rights to documents, systems, premises
- Reporting obligations with high frequency or unspecified scope
- Reports whose format and detail are unilaterally defined by the client
- Obligation to bear audit costs
- KPI reporting with one-sided measurement methods
- Documentation retention obligations""",
    ),
    (
        "Haftung / Zusicherung / Überdehnung",
        """Additional focus — Liability & Warranty perspective:
- Missing or unreasonably high liability caps
- Unlimited liability (almost always problematic)
- Indemnification obligations favoring the client
- Warranties exceeding standard scope
- Cumulative or non-deductible penalties
- Guarantees that are hard to keep ("defect-free", "state of the art")
- Liability for third parties or subcontractors as own fault
- Insurance requirements with high coverage amounts (10M+)
- One-sided liability exclusions favoring the client
- IP transfer at contract end or automatic upon creation""",
    ),
]


class PerspektivePass(DiscoveryPass):
    name = "Perspektivische Vertiefung"

    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        all_findings: list[RawFinding] = []

        for perspektive_name, focus_instructions in PERSPEKTIVEN:
            logger.info(f"Perspektive-Pass: {perspektive_name}")
            system = MATERIAL_RISK_SYSTEM_PROMPT + f"\n\n{focus_instructions}"

            for seg in segments:
                user_prompt = (
                    f"Analyze the following contract section from the '{perspektive_name}' perspective. "
                    f"Extract only MATERIAL contractual risks. "
                    f"Return NO_FINDING if no material risk exists.\n\n"
                    f"{seg.fenster_text}"
                )

                items = await llm_json_completion(
                    config=config,
                    system_prompt=system,
                    user_prompt=user_prompt,
                    temperature=0.2,
                    max_tokens=4096,
                )

                pass_label = f"{self.name} ({perspektive_name})"
                findings = self._parse_findings(items, pass_label, [seg.id],
                                                segment_text=seg.fenster_text)
                all_findings.extend(findings)

            logger.info(
                f"Perspektive-Pass '{perspektive_name}': "
                f"{sum(1 for f in all_findings if perspektive_name in f.quelle_pass)} Fundstellen"
            )

        return all_findings
