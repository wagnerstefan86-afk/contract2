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
EVIDENCE RULE
--------------------------------
scope_text MUST contain the exact original contract wording from the
paragraph or clause that triggered the finding.
Do NOT paraphrase, summarize, or rewrite the clause.
The explanation of the risk must be placed only in the "description" field.

Correct example:
  scope_text: "The contractor shall remain fully liable for the actions of any subcontractors."
  description: "The clause creates unlimited liability for subcontractor actions."

Incorrect example:
  scope_text: "The contractor carries full responsibility for subcontractors."
  (This is a paraphrase — not the original text.)

--------------------------------
QUALITY REQUIREMENTS
--------------------------------
- Only extract risks that a legal or security reviewer would actually discuss.
- Prefer fewer, higher-quality findings.
- Avoid creating multiple findings for variations of the same clause.
- Never invent risks that are not clearly supported by the paragraph.
- A good extraction result contains few but meaningful findings, not many weak signals."""


def _extract_evidence_text(
    llm_scope_text: str,
    segment_text: str,
    trigger_spans: list[str],
) -> str:
    """Extract evidence text that is guaranteed to be original contract wording.

    Priority:
    1. If trigger_spans exist and are found in segment_text, extract the
       smallest substring containing all spans (with context padding).
    2. If llm_scope_text is a verbatim substring of segment_text, use it.
    3. Otherwise fall back to the full segment_text.

    Never returns LLM-generated paraphrased text.
    """
    if not segment_text:
        # No original text available — return whatever we have
        return llm_scope_text

    # Strategy 1: build evidence from trigger_spans found in segment
    valid_spans = [s for s in trigger_spans if s and s in segment_text]
    if valid_spans:
        # Find the smallest window in segment_text that contains all spans
        first_pos = min(segment_text.index(s) for s in valid_spans)
        last_span = max(valid_spans, key=lambda s: segment_text.index(s) + len(s))
        last_pos = segment_text.index(last_span) + len(last_span)

        # Add context padding (up to 100 chars before/after), snapping to
        # sentence boundaries where possible
        ctx_start = max(0, first_pos - 100)
        ctx_end = min(len(segment_text), last_pos + 100)
        # Snap to sentence start
        for boundary in ("\n", ". "):
            bp = segment_text.rfind(boundary, ctx_start, first_pos)
            if bp >= 0:
                ctx_start = bp + len(boundary)
                break
        # Snap to sentence end
        for boundary in ("\n", ". "):
            bp = segment_text.find(boundary, last_pos, ctx_end)
            if bp >= 0:
                ctx_end = bp + len(boundary)
                break

        extracted = segment_text[ctx_start:ctx_end].strip()
        if len(extracted) >= MIN_SCOPE_TEXT_LENGTH:
            return extracted

    # Strategy 2: llm_scope_text is verbatim from original
    if llm_scope_text and llm_scope_text in segment_text:
        if len(llm_scope_text) >= MIN_SCOPE_TEXT_LENGTH:
            return llm_scope_text

    # Strategy 3: fall back to full segment text
    return segment_text


def _format_verhandlungsargumente(value) -> str:
    """Convert verhandlungsargumente from list or string to a formatted string."""
    if isinstance(value, list):
        return "\n".join(f"- {arg}" for arg in value if arg)
    return str(value) if value else ""


# ---------------------------------------------------------------------------
# Analysis perspective definitions
# ---------------------------------------------------------------------------

VALID_PERSPECTIVES = ("provider", "client", "neutral")

PERSPECTIVE_PROMPTS: dict[str, str] = {
    "provider": (
        "\n\n--------------------------------\n"
        "ANALYSIS PERSPECTIVE: SERVICE PROVIDER (Auftragnehmer)\n"
        "--------------------------------\n"
        "You are reviewing this contract on behalf of the IT service provider (Auftragnehmer).\n"
        "Identify clauses that increase operational, legal, or financial risk FOR THE PROVIDER.\n"
        "Focus on: one-sided obligations imposed on the provider, unlimited liability, "
        "scope creep, unilateral client rights, unrealistic SLAs, cost risks, "
        "regulatory pass-through, and exit obligations.\n"
        "Risks that only affect the client are NOT relevant."
    ),
    "client": (
        "\n\n--------------------------------\n"
        "ANALYSIS PERSPECTIVE: CLIENT (Auftraggeber)\n"
        "--------------------------------\n"
        "You are reviewing this contract on behalf of the client (Auftraggeber).\n"
        "Identify clauses that weaken regulatory control, auditability, or resilience "
        "FROM THE CLIENT'S PERSPECTIVE.\n"
        "Focus on: insufficient audit rights, weak reporting obligations, "
        "unclear subcontracting controls, missing liability protections, "
        "inadequate BCM/DR requirements, gaps in data protection safeguards, "
        "and insufficient exit/transition provisions.\n"
        "Risks that only affect the provider are NOT relevant."
    ),
    "neutral": (
        "\n\n--------------------------------\n"
        "ANALYSIS PERSPECTIVE: NEUTRAL / STRUCTURAL\n"
        "--------------------------------\n"
        "You are reviewing this contract from a neutral, structural perspective.\n"
        "Identify clauses that represent structural contract risks INDEPENDENT OF PARTY.\n"
        "Focus on: ambiguous scope definitions, missing escalation procedures, "
        "contradictory clauses, undefined terms, gaps in change management, "
        "unclear governance structures, missing dispute resolution mechanisms, "
        "and provisions that create legal uncertainty for either party.\n"
        "Do not favor either party — assess the contract's structural soundness."
    ),
}


def get_perspective_prompt(perspective: str) -> str:
    """Return the perspective prompt fragment, or empty string for default (provider)."""
    return PERSPECTIVE_PROMPTS.get(perspective, PERSPECTIVE_PROMPTS["provider"])


class DiscoveryPass(ABC):
    """Abstract base for a discovery pass."""

    name: str = "Unbekannter Pass"

    @abstractmethod
    async def run(
        self,
        segments: list[Segment],
        config: LLMConfig,
        full_text: str,
        perspective: str = "provider",
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
                # --- Evidence extraction: always use original contract text ---
                trigger_spans = item.get("trigger_spans")
                if not isinstance(trigger_spans, list):
                    trigger_spans = []
                # Filter to only spans that actually appear in the segment
                if segment_text and trigger_spans:
                    trigger_spans = [s for s in trigger_spans
                                     if isinstance(s, str) and s in segment_text]

                scope_text = _extract_evidence_text(
                    llm_scope_text=str(item.get("scope_text", "")),
                    segment_text=segment_text,
                    trigger_spans=trigger_spans,
                )

                # Map new format fields to RawFinding, with legacy fallback
                textstelle = scope_text or str(item.get("textstelle", ""))
                kategorie = str(item.get("category", "") or item.get("kategorie", "Sonstiges"))
                description = str(item.get("description", ""))
                kurzbeschreibung = str(item.get("kurzbeschreibung", "")) or description
                erklaerung = str(item.get("erklaerung", "")) or description

                raw_severity = str(item.get("severity", "") or item.get("risikostufe", "Niedrig"))
                risikostufe = normalize_severity(raw_severity)

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
