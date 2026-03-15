"""Base interface for discovery passes — material-risk-only extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.discovery.chunking import Segment
from app.discovery.llm_client import LLMConfig


@dataclass
class RawFinding:
    """A single raw finding from a discovery pass, before consolidation."""
    textstelle: str          # Exact quoted text from the contract
    kategorie: str           # Category label
    kurzbeschreibung: str    # Short description / title
    erklaerung: str          # Detailed explanation
    empfehlung: str          # Recommendation for the Auftragnehmer
    risikostufe: str         # Kritisch / Hoch / Mittel / Niedrig / Hinweis
    segment_ids: list[str] = field(default_factory=list)
    quelle_pass: str = ""    # Which pass found this
    # Structured recommendation fields (populated by LLM when available)
    risiko_detail: str = ""          # Specific risk: what, for whom, consequence
    alternativformulierung: str = "" # Suggested alternative contract wording
    bieterfrage: str = ""            # Question to raise during bid/negotiation
    verhandlungsargumente: str = ""  # Arguments for negotiation
    # Paragraph-level evidence fields
    scope_type: str = ""             # "paragraph" or empty
    scope_text: str = ""             # Full paragraph text
    trigger_spans: list[str] = field(default_factory=list)  # Key phrases
    evidence_heading_path: str = ""  # Section heading breadcrumb


# ---------------------------------------------------------------------------
# Severity normalization
# ---------------------------------------------------------------------------

SEVERITY_MAP = {
    "critical": "Kritisch",
    "high": "Hoch",
    "medium": "Mittel",
    "low": "Niedrig",
    # Pass-through for German labels
    "kritisch": "Kritisch",
    "hoch": "Hoch",
    "mittel": "Mittel",
    "niedrig": "Niedrig",
    "hinweis": "Hinweis",
}


def normalize_severity(raw: str) -> str:
    """Normalize an LLM severity label to the internal Risikostufe value."""
    return SEVERITY_MAP.get(raw.strip().lower(), "Niedrig") if raw else "Niedrig"


# Minimum chars for scope_text to be considered valid paragraph-level evidence
MIN_SCOPE_TEXT_LENGTH = 80


# ---------------------------------------------------------------------------
# Shared material-risk extraction prompt
# ---------------------------------------------------------------------------

MATERIAL_RISK_SYSTEM_PROMPT = """You are a contract risk extraction system for IT service provider contract reviews.
Your task is NOT to list every potentially problematic sentence.
Your task is to extract only MATERIAL contractual risks that would realistically be raised during a professional contract review.

Important principle:
Most paragraphs do NOT contain a standalone contractual risk.
Only produce a finding when the paragraph contains a clear contractual risk that would require clarification, negotiation, or mitigation.

--------------------------------
RISK DETECTION RULES
--------------------------------
Create a finding ONLY if at least one of the following conditions is true:
1. The contract creates a one-sided obligation or right
   (e.g. unilateral instruction rights, unilateral changes, unilateral termination).
2. Liability or responsibility is unclear, unlimited, or transferred broadly.
3. The scope of services is vague, open-ended, or allows uncontrolled expansion.
4. Compliance, security, regulatory, or reporting obligations are imposed without clear limits.
5. Audit or control rights create operational or legal risk.
6. Subcontracting or delegation creates unclear responsibility or liability.
7. An obligation exists without defined limits, criteria, or boundaries.

If none of these conditions apply, return: { "result": "NO_FINDING" }

--------------------------------
ANTI-NOISE RULES
--------------------------------
DO NOT create a finding when:
- The text only describes normal contractual structure.
- The clause is neutral or balanced.
- The clause merely references compliance or standards without imposing unclear obligations.
- The risk only exists when taken out of context.

--------------------------------
CONTEXT RULE
--------------------------------
A finding must always be based on the full paragraph or clause context.
Never generate findings based on isolated sentences or fragments.

--------------------------------
DEDUPLICATION RULE
--------------------------------
Each paragraph may produce at most one finding.
If multiple potential risks appear in the paragraph,
choose the single most relevant contractual risk.

--------------------------------
OUTPUT FORMAT
--------------------------------
Return ONLY a JSON array (no markdown, no explanation).
Each element is either a risk finding or a NO_FINDING marker:

[
  {
    "scope_type": "paragraph",
    "scope_text": "full paragraph text from the document",
    "trigger_spans": ["short trigger phrase 1", "optional trigger phrase 2"],
    "category": "CATEGORY",
    "severity": "low|medium|high|critical",
    "description": "short explanation of the contractual risk (2-3 sentences)"
  }
]

If no paragraphs contain material risks, return: [{"result": "NO_FINDING"}]

Categories: Weisungsrecht, Audit, Haftung, Reporting, Compliance, SLA, Subunternehmer, Informationssicherheit, Datenschutz, Verfügbarkeit & Betrieb, Vertragsmanagement, Leistungsumfang & Abgrenzung, Personalanforderungen, Geistiges Eigentum, Implizite Pflichten, BCM, Incident, Exit

--------------------------------
QUALITY REQUIREMENTS
--------------------------------
- Only extract risks that a legal or security reviewer would actually discuss.
- Prefer fewer, higher-quality findings.
- Avoid creating multiple findings for variations of the same clause.
- Never invent risks that are not clearly supported by the paragraph.
- A good extraction result contains few but meaningful findings, not many weak signals."""


def _format_verhandlungsargumente(value) -> str:
    """Convert verhandlungsargumente from list or string to a formatted string."""
    if isinstance(value, list):
        return "\n".join(f"- {arg}" for arg in value if arg)
    return str(value) if value else ""


class DiscoveryPass(ABC):
    """Abstract base for a discovery pass."""

    name: str = "Unbekannter Pass"

    @abstractmethod
    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
    ) -> list[RawFinding]:
        """Run this pass and return raw findings."""
        ...

    def _parse_findings(self, items: list[dict], pass_name: str,
                        segment_ids: list[str],
                        segment_text: str = "") -> list[RawFinding]:
        """Parse LLM JSON output into RawFinding objects.

        Handles both new material-risk format and legacy format.
        Skips NO_FINDING entries. Normalizes severity.
        Falls back to segment_text if scope_text is too short.
        """
        findings = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Skip NO_FINDING markers
            if item.get("result") == "NO_FINDING":
                continue
            try:
                # Determine scope_text with quality guardrail
                scope_text = str(item.get("scope_text", ""))
                if scope_text and len(scope_text) < MIN_SCOPE_TEXT_LENGTH and segment_text:
                    scope_text = segment_text

                # Map new format fields to RawFinding, with legacy fallback
                textstelle = scope_text or str(item.get("textstelle", ""))
                kategorie = str(item.get("category", "") or item.get("kategorie", "Sonstiges"))
                description = str(item.get("description", ""))
                kurzbeschreibung = str(item.get("kurzbeschreibung", "")) or description
                erklaerung = str(item.get("erklaerung", "")) or description

                raw_severity = str(item.get("severity", "") or item.get("risikostufe", "Niedrig"))
                risikostufe = normalize_severity(raw_severity)

                trigger_spans = item.get("trigger_spans")
                if not isinstance(trigger_spans, list):
                    trigger_spans = []

                findings.append(RawFinding(
                    textstelle=textstelle[:2000],
                    kategorie=kategorie,
                    kurzbeschreibung=kurzbeschreibung,
                    erklaerung=erklaerung,
                    empfehlung=str(item.get("empfehlung", "")),
                    risikostufe=risikostufe,
                    segment_ids=segment_ids,
                    quelle_pass=pass_name,
                    risiko_detail=str(item.get("risiko_detail", "")),
                    alternativformulierung=str(item.get("alternativformulierung", "")),
                    bieterfrage=str(item.get("bieterfrage", "")),
                    verhandlungsargumente=_format_verhandlungsargumente(item.get("verhandlungsargumente", "")),
                    scope_type=str(item.get("scope_type", "")),
                    scope_text=scope_text,
                    trigger_spans=trigger_spans,
                    evidence_heading_path=str(item.get("evidence_heading_path", "")),
                ))
            except Exception:
                continue
        return findings
