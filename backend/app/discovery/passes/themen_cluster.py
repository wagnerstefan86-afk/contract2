"""Topic Clustering Pass — groups raw findings into 5-12 risk topics via LLM.

This pass runs AFTER the 4 detection passes and BEFORE consolidation.
It takes ALL raw findings and clusters them semantically into overarching
risk topics (Risikothemen). Individual findings are preserved as evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import RawFinding

logger = logging.getLogger(__name__)

RISK_LEVEL_MAP = {
    "kritisch": "Kritisch",
    "hoch": "Hoch",
    "mittel": "Mittel",
    "niedrig": "Niedrig",
}

SYSTEM_PROMPT = """Du erhältst eine Liste von Risiko-Fundstellen aus einem IT-Outsourcing-Vertrag.
Viele Fundstellen beschreiben denselben Risikokern.
Fasse diese Fundstellen zu übergeordneten RISIKOTHEMEN zusammen.

Regeln:
1. Mehrere Fundstellen können zum selben Thema gehören.
2. Ein Thema beschreibt den eigentlichen Risikokern.
3. Die einzelnen Fundstellen werden als Belege (Evidence) gesammelt.
4. Themen müssen möglichst präzise sein.

Zielgröße:
Ein Vertrag von 10–20 Seiten sollte typischerweise 5–12 Risikothemen enthalten.

Typische Themen sind z.B.:
- Weisungsrechte
- Audit / Reporting
- Regulatorische Durchreichung
- BCM / Disaster Recovery
- Incidentpflichten
- Subunternehmer
- Exit / Datenherausgabe
- Haftung
- Leistungsumfang

AUSGABEFORMAT:
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat diese Felder:
[
  {
    "topic_title": "kurzer Titel des Risikothemas",
    "category": "Kategorie",
    "risk_level": "Kritisch | Hoch | Mittel | Niedrig",
    "beschreibung": "Beschreibung des Risikos und warum es für den Auftragnehmer relevant ist",
    "evidence": [
      {
        "ursprungstitel": "Titel der ursprünglichen Fundstelle (exakt wie in der Liste)"
      }
    ]
  }
]

WICHTIG:
- Jede Fundstelle aus der Liste muss genau EINEM Thema zugeordnet werden.
- Verwende den exakten Titel (ursprungstitel) aus der Eingabeliste.
- Erzeuge zwischen 5 und 12 Themen."""


@dataclass
class TopicCluster:
    """Result of LLM topic clustering."""
    titel: str
    kategorie: str
    risikostufe: str
    beschreibung: str
    evidence_titles: list[str] = field(default_factory=list)


async def clustere_findings(
    findings: list[RawFinding],
    config: LLMConfig,
) -> list[TopicCluster] | None:
    """Cluster raw findings into 5-12 risk topics using LLM.

    Returns None if clustering fails or produces invalid results.
    """
    if not findings:
        return None

    # Build compact representation for the LLM
    finding_lines = []
    for i, f in enumerate(findings, 1):
        text_preview = f.textstelle[:200].replace("\n", " ")
        if len(f.textstelle) > 200:
            text_preview += "..."
        finding_lines.append(
            f"{i}. [{f.risikostufe}] [{f.kategorie}] {f.kurzbeschreibung}\n"
            f"   Textstelle: \"{text_preview}\""
        )

    findings_text = "\n".join(finding_lines)

    user_prompt = (
        f"Die folgende Liste enthält {len(findings)} Risiko-Fundstellen aus einem IT-Outsourcing-Vertrag.\n"
        f"Fasse sie zu 5–12 übergeordneten Risikothemen zusammen.\n\n"
        f"{findings_text}"
    )

    try:
        items = await llm_json_completion(
            config=config,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=4096,
        )
    except Exception as e:
        logger.error(f"Topic Clustering LLM-Aufruf fehlgeschlagen: {e}")
        return None

    # Parse response
    clusters = _parse_clusters(items)
    if clusters is None:
        return None

    # Validate: 3-15 topics, each with at least one evidence
    if len(clusters) < 3 or len(clusters) > 15:
        logger.warning(
            f"Topic Clustering: {len(clusters)} Themen (erwartet 3-15), übersprungen"
        )
        return None

    empty_clusters = [c for c in clusters if not c.evidence_titles]
    if empty_clusters:
        logger.warning(
            f"Topic Clustering: {len(empty_clusters)} Themen ohne Evidence"
        )

    # Filter out empty clusters
    clusters = [c for c in clusters if c.evidence_titles]

    logger.info(f"Topic Clustering: {len(clusters)} Risikothemen erzeugt")
    return clusters


def _parse_clusters(items: list[dict]) -> list[TopicCluster] | None:
    """Parse LLM JSON output into TopicCluster objects."""
    if not isinstance(items, list):
        logger.error("Topic Clustering: LLM-Antwort ist kein Array")
        return None

    clusters = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            raw_risk = str(item.get("risk_level", "Mittel")).lower()
            evidence = item.get("evidence", [])
            evidence_titles = []
            if isinstance(evidence, list):
                for ev in evidence:
                    if isinstance(ev, dict):
                        title = ev.get("ursprungstitel", "")
                        if title:
                            evidence_titles.append(str(title))

            clusters.append(TopicCluster(
                titel=str(item.get("topic_title", "")),
                kategorie=str(item.get("category", "")),
                risikostufe=RISK_LEVEL_MAP.get(raw_risk, raw_risk.capitalize()),
                beschreibung=str(item.get("beschreibung", "")),
                evidence_titles=evidence_titles,
            ))
        except Exception:
            continue

    return clusters if clusters else None


def resolve_topic_fundstellen(
    clusters: list[TopicCluster],
    fundstellen: list,
) -> list[tuple[TopicCluster, list]]:
    """Match topic evidence titles to persisted Fundstelle objects.

    Uses fuzzy matching on kurzbeschreibung since consolidation may
    have slightly altered the descriptions.
    """
    result = []

    for cluster in clusters:
        matched = []
        for ev_title in cluster.evidence_titles:
            best_match = None
            best_score = 0.0
            for fs in fundstellen:
                score = SequenceMatcher(
                    None,
                    ev_title.lower(),
                    fs.kurzbeschreibung.lower(),
                ).ratio()
                if score > best_score:
                    best_score = score
                    best_match = fs
            if best_match and best_score >= 0.75:
                if best_match not in matched:
                    matched.append(best_match)
            else:
                logger.debug(
                    f"Topic '{cluster.titel}': Evidence '{ev_title[:50]}' "
                    f"nicht zugeordnet (bester Score: {best_score:.2f})"
                )
        result.append((cluster, matched))

    return result
