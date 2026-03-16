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

MATERIAL_RISK_SYSTEM_PROMPT = """Du bist ein Vertragsrisikoanalyse-System für die Prüfung von IT-Outsourcing-Verträgen.
Deine Aufgabe ist NICHT, jeden potenziell problematischen Satz aufzulisten.
Deine Aufgabe ist es, ausschließlich WESENTLICHE vertragliche Risiken zu extrahieren, die in einer professionellen Vertragsprüfung tatsächlich thematisiert würden.

Grundprinzip:
Die meisten Absätze enthalten KEIN eigenständiges vertragliches Risiko.
Erzeuge nur dann einen Fund, wenn der Absatz ein klares vertragliches Risiko enthält, das Klärung, Verhandlung oder Absicherung erfordert.

--------------------------------
SPRACH-REGEL (ZWINGEND)
--------------------------------
Alle Ausgaben MÜSSEN auf Deutsch verfasst sein.
Niemals Deutsch und Englisch mischen.
scope_text enthält den exakten Originaltext aus dem Vertragsdokument — nur dieses Feld darf
in der Originalsprache des Dokuments bleiben (auch wenn Englisch).
Alle anderen Felder (description, category) MÜSSEN auf Deutsch sein.

--------------------------------
RISIKOERKENNUNGSREGELN
--------------------------------
Erzeuge einen Fund NUR, wenn mindestens eine der folgenden Bedingungen zutrifft:
1. Der Vertrag schafft eine einseitige Pflicht oder ein einseitiges Recht
   (z.B. einseitiges Weisungsrecht, einseitige Änderungsrechte, einseitige Kündigung).
2. Haftung oder Verantwortung ist unklar, unbegrenzt oder wird pauschal übertragen.
3. Der Leistungsumfang ist vage, offen oder erlaubt eine unkontrollierte Ausweitung.
4. Compliance-, Sicherheits-, regulatorische oder Reportingpflichten werden ohne klare Grenzen auferlegt.
5. Audit- oder Kontrollrechte schaffen operatives oder rechtliches Risiko.
6. Unterauftragsvergabe oder Delegation schafft unklare Verantwortung oder Haftung.
7. Eine Verpflichtung besteht ohne definierte Grenzen, Kriterien oder Schranken.

Trifft keine dieser Bedingungen zu, antworte: { "result": "NO_FINDING" }

--------------------------------
ANTI-NOISE-REGELN
--------------------------------
Erzeuge KEINEN Fund wenn:
- Der Text nur die normale Vertragsstruktur beschreibt.
- Die Klausel neutral oder ausgewogen ist.
- Die Klausel nur auf Compliance oder Standards verweist, ohne unklare Pflichten aufzuerlegen.
- Das Risiko nur aus dem Kontext gerissen existiert.

--------------------------------
KONTEXTREGEL
--------------------------------
Ein Fund muss immer auf dem vollständigen Absatz- oder Klauselkontext basieren.
Niemals Funde auf isolierten Sätzen oder Fragmenten erzeugen.

--------------------------------
DEDUPLIZIERUNGSREGEL
--------------------------------
Jeder Absatz darf höchstens einen Fund erzeugen.
Erscheinen mehrere potenzielle Risiken im Absatz,
wähle das einzelne relevanteste vertragliche Risiko.

--------------------------------
AUSGABEFORMAT
--------------------------------
Antworte AUSSCHLIESSLICH mit einem JSON-Array (kein Markdown, keine Erklärung).
Jedes Element ist entweder ein Risikofund oder ein NO_FINDING-Marker:

[
  {
    "scope_type": "paragraph",
    "scope_text": "Exakter Originaltext des betroffenen Absatzes aus dem Dokument",
    "trigger_spans": ["kurze Schlüsselphrase 1", "optionale Schlüsselphrase 2"],
    "category": "KATEGORIE",
    "severity": "low|medium|high|critical",
    "description": "Präzise Erklärung des vertraglichen Risikos auf Deutsch (2-3 Sätze). Beschreibe: (1) was die Klausel bewirkt, (2) welches konkrete Risiko daraus entsteht, (3) warum dies verhandlungsrelevant ist."
  }
]

Falls keine Absätze wesentliche Risiken enthalten: [{"result": "NO_FINDING"}]

Kategorien: Weisungsrecht, Audit, Haftung, Reporting, Compliance, SLA, Subunternehmer, Informationssicherheit, Datenschutz, Verfügbarkeit & Betrieb, Vertragsmanagement, Leistungsumfang & Abgrenzung, Personalanforderungen, Geistiges Eigentum, Implizite Pflichten, BCM, Incident, Exit

--------------------------------
EVIDENZREGEL
--------------------------------
scope_text MUSS den exakten Originalwortlaut aus dem Vertragsdokument enthalten,
also den Absatz oder die Klausel, die den Fund ausgelöst hat.
NICHT umformulieren, zusammenfassen oder umschreiben.
Die Risikoerklärung gehört ausschließlich in das Feld "description".

Korrektes Beispiel:
  scope_text: "Der Auftragnehmer haftet unbeschränkt für das Handeln seiner Subunternehmer."
  description: "Die Klausel begründet eine unbegrenzte Haftung für Subunternehmerhandlungen ohne Deckelung oder Rückgriffsmöglichkeit."

Falsches Beispiel:
  scope_text: "Der AN trägt die volle Verantwortung für Subunternehmer."
  (Dies ist eine Umformulierung — nicht der Originaltext.)

--------------------------------
QUALITÄTSANFORDERUNGEN
--------------------------------
- Nur Risiken extrahieren, die ein Rechts- oder Sicherheitsprüfer tatsächlich besprechen würde.
- Weniger, qualitativ hochwertige Funde sind besser als viele schwache Signale.
- Keine mehrfachen Funde für Varianten derselben Klausel erzeugen.
- Niemals Risiken erfinden, die nicht klar durch den Absatz gestützt werden.
- Ein gutes Extraktionsergebnis enthält wenige, aber aussagekräftige Funde.

--------------------------------
BESCHREIBUNGSQUALITÄT
--------------------------------
Beschreibungen (description) sollen verhandlungstauglich formuliert sein:
- Nicht: "Dies könnte zu Problemen führen."
- Besser: "Die Klausel erlaubt dem Auftraggeber faktisch unbegrenzte Leistungserweiterungen. Ohne klare Abgrenzung kann der Leistungsumfang einseitig verändert werden, was zu unkontrollierbaren Kosten- und Ressourcenrisiken führt."
- Struktur: Klauselwirkung → konkretes Risiko → Verhandlungsrelevanz."""


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


# ---------------------------------------------------------------------------
# Post-processing: lightweight text normalization for user-facing output
# ---------------------------------------------------------------------------

# Single-word or pure-category titles that must be rejected/enriched
_GENERIC_TITLES = {
    "haftung", "compliance", "audit", "exit", "reporting", "weisungsrecht",
    "subunternehmer", "informationssicherheit", "datenschutz", "sla",
    "verfügbarkeit", "vertragsmanagement", "leistungsumfang",
    "personalanforderungen", "geistiges eigentum", "bcm", "incident",
    "vertraulichkeit", "geheimhaltung", "regulatorik",
}


def normalize_user_facing_text(text: str) -> str:
    """Lightweight normalization for user-facing generated text.

    - Trims whitespace
    - Removes leftover English boilerplate phrases
    - Normalizes German punctuation/casing
    """
    if not text:
        return text

    text = text.strip()

    # Remove common English boilerplate that LLMs sometimes inject
    _EN_BOILERPLATE = [
        "This clause ", "This creates ", "This could ", "This should ",
        "The clause ", "The contractor ", "Note: ", "Important: ",
        "Here is ", "Based on ", "In summary, ",
    ]
    for phrase in _EN_BOILERPLATE:
        if text.startswith(phrase):
            # Only strip if the rest is German (heuristic: contains common German words)
            rest = text[len(phrase):]
            if any(w in rest.lower() for w in ["der", "die", "das", "und", "oder", "für", "ist"]):
                text = rest.strip()
                # Capitalize first letter
                if text:
                    text = text[0].upper() + text[1:]
                break

    return text


def is_generic_title(title: str) -> bool:
    """Check if a title is too generic to be useful as a theme title."""
    normalized = title.strip().lower().rstrip(".")
    # Exact match against known generic terms
    if normalized in _GENERIC_TITLES:
        return True
    # Too short (< 3 words)
    words = normalized.split()
    if len(words) < 3:
        return True
    return False


def enrich_generic_title(title: str, kategorie: str, beschreibung: str) -> str:
    """Attempt to enrich a generic title using available context.

    Returns the original title if it's already specific enough.
    """
    if not is_generic_title(title):
        return title

    # Try to extract a better title from the first sentence of beschreibung
    if beschreibung and len(beschreibung) > 20:
        first_sentence = beschreibung.split(".")[0].strip()
        # Must be reasonably short for a title
        if 20 < len(first_sentence) <= 100 and len(first_sentence.split()) >= 4:
            return first_sentence

    # Fallback: combine title + category for minimal enrichment
    if kategorie and kategorie.lower() != title.strip().lower():
        return f"{title.strip()} — {kategorie}"

    return title


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
