"""Final Editorial Pass — reduces clustered risk topics to negotiation-relevant core themes.

This pass runs AFTER topic clustering and consolidation. It takes the existing
RisikoThemen (with their linked Fundstellen) and reduces them to a small set of
truly negotiation-relevant core themes, each with max 3 evidence references.

Target output:
- Short contracts (≤5 pages / ≤15k chars): 5–8 final themes
- Normal contracts: 8–15 final themes
- Per theme: 1 primary + up to 2 secondary evidence references
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.discovery.llm_client import LLMConfig, llm_json_completion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Target theme counts based on contract length
# ---------------------------------------------------------------------------

def _ziel_themen_anzahl(text_laenge: int, anzahl_cluster: int) -> tuple[int, int]:
    """Return (min, max) target theme count based on contract length."""
    if text_laenge <= 15_000:  # ~3-5 pages
        return (3, 8)
    elif text_laenge <= 40_000:  # ~5-15 pages
        return (5, 12)
    else:
        return (8, 15)


# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Du bist ein erfahrener Vertragsexperte für IT-Outsourcing.
Du erhältst eine Liste von Risikothemen aus einer Vertragsanalyse, jeweils mit zugeordneten Fundstellen.
Deine Aufgabe: Reduziere auf die WIRKLICH verhandlungsrelevanten Kernthemen.

SELEKTIONSREGEL — Ein Thema bleibt NUR erhalten, wenn mindestens EINE dieser Fragen mit JA beantwortet wird:
1. Begründet es ein eigenständiges wirtschaftliches, regulatorisches, operatives oder haftungsbezogenes Risiko?
2. Würde man dafür eine eigene Verhandlungsklausel, Bieterfrage oder Management-Entscheidung formulieren?
3. Würde das Weglassen die Managementbewertung des Vertrags inhaltlich verändern?

Was NICHT als eigenes Thema durchgehen darf:
- Bloße Umformulierung desselben Risikos
- Bloße Wiederholung desselben Standards
- Bloße Begleitpflicht ohne separaten Verhandlungskern
- Reine Untervarianten eines Hauptthemas
- Sprachliche Dubletten
- Allgemeines "könnte problematisch sein"
- Rein deklarative Aussagen ohne Verhandlungsrelevanz

EVIDENZ-REDUKTION:
- Pro Thema: genau 1 Primärfundstelle (die stärkste, belastbarste)
- Optional bis zu 2 Sekundärfundstellen (nur wenn sie den Risikokern wirklich zusätzlich stützen)
- NICHT: 7, 10 oder 15 Evidenzen pro Thema

TITEL-REGELN:
- Präzise fachliche Titel, die den Verhandlungskern treffen
- Keine generischen Kurzlabels
- Keine falsche Wertung wie "unzureichend" wenn "überdehnt / einseitig / unklar / unbegrenzt" gemeint ist

AUSGABEFORMAT — Antworte AUSSCHLIESSLICH mit einem JSON-Objekt:
{
  "finale_themen": [
    {
      "quell_thema_index": 0,
      "titel": "Präziser fachlicher Titel (mind. 5 Wörter)",
      "kategorie": "Kategorie",
      "risikostufe": "Hoch | Mittel | Niedrig",
      "kurzbeschreibung": "Worin besteht das Risiko konkret? Warum ist es für den Auftragnehmer problematisch?",
      "warum_verhandlungsrelevant": "Warum erfordert dies eine eigene Verhandlungsklausel?",
      "primaerfundstelle_index": 0,
      "sekundaerfundstelle_indices": [1, 2],
      "alternativformulierung": "Konkrete alternative Vertragsformulierung",
      "bieterfrage": "Konkrete Bieterfrage zur Klärung",
      "verhandlungsargumente": ["Argument 1", "Argument 2", "Argument 3"]
    }
  ],
  "verworfene_themen": [
    {
      "quell_thema_index": 1,
      "grund": "Kurze Begründung warum kein eigenständiger Risikokern"
    }
  ]
}

WICHTIG:
- quell_thema_index = Index des Themas in der Eingabeliste (0-basiert)
- primaerfundstelle_index = Index der Fundstelle innerhalb der Fundstellen-Liste dieses Themas
- sekundaerfundstelle_indices = Indices weiterer Fundstellen dieses Themas (max. 2)
- Jedes Eingabe-Thema muss entweder in finale_themen oder verworfene_themen erscheinen
- KEIN Thema darf in beiden Listen gleichzeitig sein"""


@dataclass
class FinalesThema:
    """Result of the final editorial pass for one selected theme."""
    quell_thema_index: int
    titel: str
    kategorie: str
    risikostufe: str
    kurzbeschreibung: str
    warum_verhandlungsrelevant: str
    primaerfundstelle_index: int
    sekundaerfundstelle_indices: list[int] = field(default_factory=list)
    alternativformulierung: str = ""
    bieterfrage: str = ""
    verhandlungsargumente: list[str] = field(default_factory=list)


@dataclass
class VerworfenesThema:
    """A topic rejected by the final editorial pass."""
    quell_thema_index: int
    grund: str


@dataclass
class EditorialErgebnis:
    """Complete result of the final editorial pass."""
    finale_themen: list[FinalesThema]
    verworfene_themen: list[VerworfenesThema]


async def final_editorial_pass(
    themen_daten: list[dict],
    text_laenge: int,
    config: LLMConfig,
) -> EditorialErgebnis | None:
    """Run the final editorial reduction pass via LLM.

    Args:
        themen_daten: List of dicts, each with keys:
            - titel, kategorie, risikostufe, beschreibung
            - fundstellen: list of {kurzbeschreibung, textstelle, risikostufe}
        text_laenge: Total contract text length in characters
        config: LLM configuration

    Returns:
        EditorialErgebnis or None if LLM call fails.
    """
    if not themen_daten:
        return None

    ziel_min, ziel_max = _ziel_themen_anzahl(text_laenge, len(themen_daten))

    # Build compact representation for LLM
    themen_lines = []
    for i, t in enumerate(themen_daten):
        fundstellen_text = []
        for fi, f in enumerate(t.get("fundstellen", [])):
            text_preview = f.get("textstelle", "")[:150].replace("\n", " ")
            fundstellen_text.append(
                f"    F{fi}: [{f.get('risikostufe', '?')}] {f.get('kurzbeschreibung', '?')}\n"
                f"        Textstelle: \"{text_preview}...\""
            )

        fs_block = "\n".join(fundstellen_text) if fundstellen_text else "    (keine Fundstellen)"
        themen_lines.append(
            f"THEMA {i}: [{t.get('risikostufe', '?')}] [{t.get('kategorie', '?')}] {t.get('titel', '?')}\n"
            f"  Beschreibung: {t.get('beschreibung', '')[:200]}\n"
            f"  Fundstellen ({len(t.get('fundstellen', []))}):\n{fs_block}"
        )

    themen_text = "\n\n".join(themen_lines)

    user_prompt = (
        f"Der Vertrag hat ca. {text_laenge} Zeichen ({text_laenge // 3000 + 1} Seiten).\n"
        f"Es gibt aktuell {len(themen_daten)} Risikothemen aus dem Topic Clustering.\n"
        f"Reduziere auf {ziel_min}–{ziel_max} wirklich verhandlungsrelevante Kernthemen.\n\n"
        f"{themen_text}"
    )

    try:
        # We need JSON object, not array — use llm_completion and parse manually
        from app.discovery.llm_client import llm_completion
        import json

        raw = await llm_completion(
            config=config,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=4096,
        )

        # Extract JSON object from response
        parsed = _extract_json_object(raw)
        if parsed is None:
            logger.error("Final Editorial Pass: Kein gültiges JSON-Objekt in LLM-Antwort")
            return None

        return _parse_ergebnis(parsed, len(themen_daten))

    except Exception as e:
        logger.error(f"Final Editorial Pass LLM-Aufruf fehlgeschlagen: {e}")
        return None


def _extract_json_object(raw: str) -> dict | None:
    """Extract a JSON object from LLM response text."""
    import json

    # Handle markdown code blocks
    if "```" in raw:
        parts = raw.split("```")
        for part in parts[1:]:
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{"):
                raw = cleaned
                break

    # Find the JSON object
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        return None

    json_str = raw[start:end + 1]
    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            return parsed
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"Final Editorial JSON-Parsing fehlgeschlagen: {e}")
        return None


def _parse_ergebnis(data: dict, anzahl_themen: int) -> EditorialErgebnis | None:
    """Parse LLM JSON output into EditorialErgebnis."""
    finale = []
    for item in data.get("finale_themen", []):
        if not isinstance(item, dict):
            continue
        try:
            sek_indices = item.get("sekundaerfundstelle_indices", [])
            if not isinstance(sek_indices, list):
                sek_indices = []
            # Limit to max 2 secondary evidence
            sek_indices = [int(x) for x in sek_indices[:2]]

            verhandlungsargs = item.get("verhandlungsargumente", [])
            if not isinstance(verhandlungsargs, list):
                verhandlungsargs = [str(verhandlungsargs)] if verhandlungsargs else []

            finale.append(FinalesThema(
                quell_thema_index=int(item.get("quell_thema_index", 0)),
                titel=str(item.get("titel", "")),
                kategorie=str(item.get("kategorie", "")),
                risikostufe=str(item.get("risikostufe", "Mittel")),
                kurzbeschreibung=str(item.get("kurzbeschreibung", "")),
                warum_verhandlungsrelevant=str(item.get("warum_verhandlungsrelevant", "")),
                primaerfundstelle_index=int(item.get("primaerfundstelle_index", 0)),
                sekundaerfundstelle_indices=sek_indices,
                alternativformulierung=str(item.get("alternativformulierung", "")),
                bieterfrage=str(item.get("bieterfrage", "")),
                verhandlungsargumente=[str(a) for a in verhandlungsargs],
            ))
        except (ValueError, TypeError):
            continue

    verworfene = []
    for item in data.get("verworfene_themen", []):
        if not isinstance(item, dict):
            continue
        try:
            verworfene.append(VerworfenesThema(
                quell_thema_index=int(item.get("quell_thema_index", 0)),
                grund=str(item.get("grund", "Kein Grund angegeben")),
            ))
        except (ValueError, TypeError):
            continue

    if not finale:
        logger.warning("Final Editorial Pass: Keine finalen Themen vom LLM erhalten")
        return None

    return EditorialErgebnis(
        finale_themen=finale,
        verworfene_themen=verworfene,
    )
