"""Topic Clustering Pass — groups raw findings into 5-12 risk topics via LLM.

This pass runs AFTER the 4 detection passes and BEFORE consolidation.
It takes ALL raw findings and clusters them semantically into overarching
risk topics (Risikothemen). Individual findings are preserved as evidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.discovery.llm_client import LLMConfig, llm_json_completion
from app.discovery.passes.base import RawFinding, is_generic_title, enrich_generic_title, normalize_user_facing_text

logger = logging.getLogger(__name__)

RISK_LEVEL_MAP = {
    "kritisch": "Kritisch",
    "hoch": "Hoch",
    "mittel": "Mittel",
    "niedrig": "Niedrig",
}

RISK_LEVEL_ORDER = {"Kritisch": 4, "Hoch": 3, "Mittel": 2, "Niedrig": 1, "Hinweis": 0}

SYSTEM_PROMPT = """Du erhältst eine Liste von Risiko-Fundstellen aus einem IT-Outsourcing-Vertrag.
Viele Fundstellen beschreiben denselben Risikokern.
Fasse diese Fundstellen zu übergeordneten RISIKOTHEMEN zusammen.

SPRACH-REGEL (ZWINGEND):
Alle Ausgaben MÜSSEN vollständig auf Deutsch sein. Kein Englisch in Titeln, Beschreibungen oder Feldern.

REGELN:
1. Mehrere Fundstellen können zum selben Thema gehören.
2. Ein Thema beschreibt den eigentlichen Risikokern, nicht einzelne Klauseln.
3. Die einzelnen Fundstellen werden als Belege (Evidence) gesammelt.
4. JEDE Fundstelle muss genau EINEM Thema zugeordnet werden.

ZIELGRÖSSE:
Erzeuge zwischen 5 und 12 Risikothemen. Weniger ist besser als zu viele.
Lieber ein breites Thema mit 8 Evidence als zwei enge Themen mit je 2 Evidence.

TITEL-REGELN (KRITISCH — GENAU BEFOLGEN):
- Titel müssen verhandlungstauglich und spezifisch sein: 5–12 Wörter.
- Der Titel muss das konkrete vertragliche Problem benennen, nicht die Kategorie.
- Er muss den Risikocharakter (einseitig / unbegrenzt / unklar / offen) enthalten.
- Er soll ohne Öffnen der Evidence verständlich sein.

VERBOTENE Titelformen:
- Ein-Wort-Titel: "Haftung", "Compliance", "Audit", "Exit"
- Reine Kategorienamen: "Informationssicherheit", "Subunternehmer", "Weisungsrecht"
- Vage Phrasen: "Verschiedene Risiken", "Problematische Klauseln"
- Englische Begriffe (außer Fachbegriffe wie SLA, BCM, DORA): "Compliance Risks", "Scope Issues"

GUTE Titelbeispiele:
- "Weitreichendes Weisungsrecht ohne belastbare Zumutbarkeitsgrenzen"
- "Unbegrenzte Haftungsdurchreichung für Subunternehmer"
- "Dynamische regulatorische Anpassungspflichten ohne Kostenregelung"
- "Unklar abgegrenzter Leistungsumfang mit einseitigem Erweiterungsrecht"
- "Uneingeschränkte Audit-Zugangsrechte ohne Vorankündigungspflicht"
- "Fehlende Haftungsdeckelung bei Datenschutzverstößen"

SCHLECHTE Titelbeispiele (NICHT verwenden):
- "Haftung" → zu generisch
- "Compliance" → sagt nichts über das Risiko
- "Audit" → beschreibt nur die Kategorie
- "Weisungsrecht" → fehlt Risikorichtung

BESCHREIBUNGSQUALITÄT:
Die Beschreibung muss 2-3 Sätze enthalten, die klar benennen:
1. Was bewirkt die Vertragsklausel konkret?
2. Welches wirtschaftliche, rechtliche oder operative Risiko entsteht?
3. Warum ist dies in einer Verhandlung relevant?
Keine vagen Formulierungen wie "könnte problematisch sein" oder "sollte geprüft werden".

ANTI-PATTERNS (VERMEIDE):
- Themen mit nur 1 Evidence — ordne diese einem verwandten Thema zu.
- Mehrere Themen zum gleichen Risikokern (z.B. "Haftung" und "Haftungsbegrenzung" → zusammenfassen).
- Generische oder abstrakte Titel (siehe VERBOTENE Titelformen).

AUSGABEFORMAT:
Antworte AUSSCHLIESSLICH mit einem JSON-Array. Jedes Element hat diese Felder:
[
  {
    "topic_title": "Verhandlungstauglicher Titel (5-12 Wörter, spezifisch, deutsch)",
    "category": "Kategorie",
    "risk_level": "Kritisch | Hoch | Mittel | Niedrig",
    "beschreibung": "2-3 Sätze: Klauselwirkung → konkretes Risiko → Verhandlungsrelevanz.",
    "evidence": [
      {
        "ursprungstitel": "Titel der ursprünglichen Fundstelle (exakt wie in der Liste)"
      }
    ]
  }
]

WICHTIG:
- Verwende den exakten Titel (ursprungstitel) aus der Eingabeliste.
- Jede Fundstelle muss genau EINEM Thema zugeordnet werden.
- Erzeuge zwischen 5 und 12 Themen. Maximal 12.
- Alle Texte in den Feldern topic_title, beschreibung und category MÜSSEN deutsch sein."""


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

    # Validate: at least 3 topics
    if len(clusters) < 3:
        logger.warning(
            f"Topic Clustering: nur {len(clusters)} Themen, übersprungen"
        )
        return None

    # Filter out empty clusters
    clusters = [c for c in clusters if c.evidence_titles]

    # --- Post-LLM refinement pipeline ---
    clusters = _refine_clusters(clusters)

    logger.info(f"Topic Clustering: {len(clusters)} Risikothemen nach Refinement")
    return clusters


def _refine_clusters(clusters: list[TopicCluster]) -> list[TopicCluster]:
    """Post-LLM quality refinement pipeline.

    Steps:
    1. Normalize titles (reject short/generic labels)
    2. Merge similar topics (title + category similarity)
    3. Reassign single-evidence topics to best-matching larger topic
    4. Deduplicate evidence across topics
    5. Force-merge smallest topics if count > 12
    """
    if len(clusters) <= 1:
        return clusters

    # Step 1: Normalize titles
    clusters = _normalize_titles(clusters)

    # Step 2: Merge similar topics
    clusters = _merge_similar_topics(clusters)

    # Step 3: Reassign single-evidence topics
    clusters = _reassign_singles(clusters)

    # Step 4: Deduplicate evidence across topics
    clusters = _deduplicate_evidence(clusters)

    # Step 5: Enforce target count (max 12)
    clusters = _enforce_target_count(clusters, max_count=12)

    # Final cleanup: remove any now-empty clusters
    clusters = [c for c in clusters if c.evidence_titles]

    return clusters


def _normalize_titles(clusters: list[TopicCluster]) -> list[TopicCluster]:
    """Ensure titles are descriptive, not short generic labels.

    Uses the shared is_generic_title / enrich_generic_title helpers
    to catch over-generic titles and improve them from beschreibung context.
    """
    for cluster in clusters:
        titel = cluster.titel.strip().rstrip(".")

        # Apply the shared generic-title enrichment
        titel = enrich_generic_title(titel, cluster.kategorie, cluster.beschreibung)

        # Normalize user-facing text (strip English boilerplate etc.)
        titel = normalize_user_facing_text(titel)

        # Cap at 100 chars
        if len(titel) > 100:
            titel = titel[:97] + "..."

        cluster.titel = titel

        # Also normalize beschreibung
        cluster.beschreibung = normalize_user_facing_text(cluster.beschreibung)

    return clusters


def _merge_similar_topics(
    clusters: list[TopicCluster],
    titel_schwelle: float = 0.55,
    kategorie_schwelle: float = 0.7,
) -> list[TopicCluster]:
    """Merge topics that have similar titles AND similar/same categories.

    Uses a greedy approach: iterate pairs, merge the most similar first.
    """
    merged = True
    while merged:
        merged = False
        best_pair = None
        best_score = 0.0

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                a, b = clusters[i], clusters[j]

                # Title similarity
                titel_score = SequenceMatcher(
                    None, _normalize_for_compare(a.titel), _normalize_for_compare(b.titel)
                ).ratio()

                # Category similarity
                kat_score = SequenceMatcher(
                    None, a.kategorie.lower(), b.kategorie.lower()
                ).ratio()

                # Evidence keyword overlap (check if evidence titles share keywords)
                evidence_overlap = _evidence_keyword_overlap(a.evidence_titles, b.evidence_titles)

                # Combined merge score: title is primary, category and evidence boost
                combined = titel_score * 0.5 + kat_score * 0.25 + evidence_overlap * 0.25

                # Merge if title similarity is high enough AND combined score passes
                if titel_score >= titel_schwelle and combined > best_score and combined >= 0.45:
                    best_score = combined
                    best_pair = (i, j)

                # Also merge if categories are very similar and titles share key terms
                if kat_score >= kategorie_schwelle and titel_score >= 0.4 and combined > best_score:
                    best_score = combined
                    best_pair = (i, j)

        if best_pair:
            i, j = best_pair
            _merge_into(clusters[i], clusters[j])
            logger.debug(
                f"Topic Merge: '{clusters[j].titel}' → '{clusters[i].titel}' "
                f"(score={best_score:.2f})"
            )
            clusters.pop(j)
            merged = True

    return clusters


def _reassign_singles(clusters: list[TopicCluster]) -> list[TopicCluster]:
    """Reassign single-evidence topics to the best-matching larger topic."""
    changed = True
    while changed:
        changed = False
        singles = [(i, c) for i, c in enumerate(clusters) if len(c.evidence_titles) == 1]
        multi = [(i, c) for i, c in enumerate(clusters) if len(c.evidence_titles) > 1]

        if not multi:
            break

        for si, single in singles:
            best_target = None
            best_score = 0.0

            for mi, target in multi:
                # Compare title similarity
                score = SequenceMatcher(
                    None,
                    _normalize_for_compare(single.titel),
                    _normalize_for_compare(target.titel),
                ).ratio()
                # Boost if same category
                if single.kategorie.lower() == target.kategorie.lower():
                    score += 0.15
                # Check evidence keyword overlap
                score += _evidence_keyword_overlap(single.evidence_titles, target.evidence_titles) * 0.1

                if score > best_score:
                    best_score = score
                    best_target = mi

            # Reassign if reasonably similar (threshold 0.35 — fairly permissive
            # since we prefer fewer topics over preserving tiny ones)
            if best_target is not None and best_score >= 0.35:
                target_cluster = clusters[best_target]
                target_cluster.evidence_titles.extend(single.evidence_titles)
                # Merge beschreibung
                if single.beschreibung:
                    target_cluster.beschreibung += f" {single.beschreibung}"
                # Upgrade risk if single was higher
                if _risk_order(single.risikostufe) > _risk_order(target_cluster.risikostufe):
                    target_cluster.risikostufe = single.risikostufe

                logger.debug(
                    f"Single reassign: '{single.titel}' → '{target_cluster.titel}' "
                    f"(score={best_score:.2f})"
                )
                clusters[si] = None  # type: ignore[assignment]
                changed = True

        clusters = [c for c in clusters if c is not None]

    return clusters


def _deduplicate_evidence(clusters: list[TopicCluster]) -> list[TopicCluster]:
    """Remove duplicate evidence across topics.

    If an evidence title appears in multiple topics, keep it only in the
    topic with the highest risk level (or the one with more evidence).
    """
    # Build map: evidence_title -> list of (cluster_index, position)
    evidence_map: dict[str, list[tuple[int, int]]] = {}
    for ci, cluster in enumerate(clusters):
        for ei, ev_title in enumerate(cluster.evidence_titles):
            key = ev_title.lower().strip()
            evidence_map.setdefault(key, []).append((ci, ei))

    # Find duplicates and decide which cluster keeps each evidence
    to_remove: set[tuple[int, int]] = set()  # (cluster_idx, evidence_idx)

    for key, locations in evidence_map.items():
        if len(locations) <= 1:
            continue

        # Keep in the cluster with highest risk, then most evidence
        def cluster_priority(loc: tuple[int, int]) -> tuple[int, int]:
            ci = loc[0]
            return (_risk_order(clusters[ci].risikostufe), len(clusters[ci].evidence_titles))

        locations_sorted = sorted(locations, key=cluster_priority, reverse=True)
        # Keep first (highest priority), remove rest
        for loc in locations_sorted[1:]:
            to_remove.add(loc)
            logger.debug(
                f"Evidence dedup: '{key[:50]}' entfernt aus '{clusters[loc[0]].titel}'"
            )

    # Remove in reverse order to preserve indices
    for ci, ei in sorted(to_remove, reverse=True):
        if ei < len(clusters[ci].evidence_titles):
            clusters[ci].evidence_titles.pop(ei)

    return clusters


def _enforce_target_count(
    clusters: list[TopicCluster],
    max_count: int = 12,
) -> list[TopicCluster]:
    """Force-merge the smallest/most similar topics until count <= max_count."""
    while len(clusters) > max_count:
        # Find the pair with highest similarity
        best_pair = None
        best_score = -1.0

        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                score = SequenceMatcher(
                    None,
                    _normalize_for_compare(clusters[i].titel),
                    _normalize_for_compare(clusters[j].titel),
                ).ratio()
                # Heavily prefer merging small topics
                size_penalty = min(len(clusters[i].evidence_titles), len(clusters[j].evidence_titles))
                adjusted = score + (1.0 / max(size_penalty, 1)) * 0.3

                if adjusted > best_score:
                    best_score = adjusted
                    best_pair = (i, j)

        if best_pair is None:
            break

        i, j = best_pair
        _merge_into(clusters[i], clusters[j])
        logger.debug(
            f"Force merge (>{max_count}): '{clusters[j].titel}' → '{clusters[i].titel}'"
        )
        clusters.pop(j)

    return clusters


# --- Helpers ---

def _merge_into(target: TopicCluster, source: TopicCluster) -> None:
    """Merge source topic into target. Modifies target in-place."""
    target.evidence_titles.extend(source.evidence_titles)

    # Keep the longer/more descriptive title
    if len(source.titel) > len(target.titel):
        target.titel = source.titel

    # Keep higher risk level
    if _risk_order(source.risikostufe) > _risk_order(target.risikostufe):
        target.risikostufe = source.risikostufe

    # Merge descriptions
    if source.beschreibung and source.beschreibung not in target.beschreibung:
        target.beschreibung = f"{target.beschreibung} {source.beschreibung}"


def _risk_order(level: str) -> int:
    """Numeric risk ordering for comparisons."""
    return RISK_LEVEL_ORDER.get(level, 0)


def _normalize_for_compare(text: str) -> str:
    """Normalize text for similarity comparison: lowercase, strip articles/filler."""
    text = text.lower().strip()
    # Remove common German filler words for better similarity matching
    fillers = [
        "der", "die", "das", "des", "dem", "den",
        "ein", "eine", "eines", "einem", "einen",
        "und", "oder", "bzw", "sowie",
        "für", "bei", "mit", "von", "zum", "zur",
        "im", "am", "an", "in", "auf",
        "nicht", "keine", "kein",
    ]
    words = text.split()
    words = [w for w in words if w not in fillers]
    return " ".join(words)


def _evidence_keyword_overlap(titles_a: list[str], titles_b: list[str]) -> float:
    """Compute keyword overlap between two sets of evidence titles.

    Returns a score between 0.0 and 1.0.
    """
    def extract_keywords(titles: list[str]) -> set[str]:
        keywords = set()
        for title in titles:
            # Extract significant words (> 3 chars)
            words = re.findall(r"[a-zäöüß]{4,}", title.lower())
            keywords.update(words)
        return keywords

    kw_a = extract_keywords(titles_a)
    kw_b = extract_keywords(titles_b)

    if not kw_a or not kw_b:
        return 0.0

    intersection = kw_a & kw_b
    union = kw_a | kw_b
    return len(intersection) / len(union) if union else 0.0


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

    Each Fundstelle is assigned to at most one topic (the best match)
    to prevent duplicate assignments.
    """
    # First pass: find best topic for each fundstelle
    fs_best_topic: dict[int, tuple[int, float]] = {}  # fs_index -> (cluster_index, score)

    for ci, cluster in enumerate(clusters):
        for ev_title in cluster.evidence_titles:
            best_fi = None
            best_score = 0.0
            for fi, fs in enumerate(fundstellen):
                score = SequenceMatcher(
                    None,
                    ev_title.lower(),
                    fs.kurzbeschreibung.lower(),
                ).ratio()
                if score > best_score:
                    best_score = score
                    best_fi = fi

            if best_fi is not None and best_score >= 0.75:
                existing = fs_best_topic.get(best_fi)
                if existing is None:
                    fs_best_topic[best_fi] = (ci, best_score)
                elif best_score > existing[1]:
                    # This topic has a better match — reassign
                    fs_best_topic[best_fi] = (ci, best_score)
            elif best_fi is not None:
                logger.debug(
                    f"Topic '{cluster.titel}': Evidence '{ev_title[:50]}' "
                    f"nicht zugeordnet (bester Score: {best_score:.2f})"
                )

    # Build result: group fundstellen by cluster
    cluster_fundstellen: dict[int, list] = {i: [] for i in range(len(clusters))}
    for fi, (ci, _score) in fs_best_topic.items():
        cluster_fundstellen[ci].append(fundstellen[fi])

    result = []
    for ci, cluster in enumerate(clusters):
        result.append((cluster, cluster_fundstellen.get(ci, [])))

    return result


def berechne_clustering_metriken(
    resolved: list[tuple[TopicCluster, list]],
    anzahl_einzelfindings: int,
) -> dict:
    """Compute quality metrics for the clustering result.

    Returns a dict suitable for storage in auswertung["clustering_metriken"].
    """
    anzahl_themen = len(resolved)
    evidence_counts = [len(fs_list) for _, fs_list in resolved]
    total_evidence = sum(evidence_counts)

    # Fundstellen that appear in more than one topic
    seen_ids: dict[str, int] = {}
    for _, fs_list in resolved:
        for fs in fs_list:
            fs_id = str(fs.id)
            seen_ids[fs_id] = seen_ids.get(fs_id, 0) + 1
    mehrfach_zugeordnet = sum(1 for count in seen_ids.values() if count > 1)

    themen_ohne_evidence = sum(1 for c in evidence_counts if c == 0)
    themen_mit_1 = sum(1 for c in evidence_counts if c == 1)
    durchschnitt = round(total_evidence / anzahl_themen, 1) if anzahl_themen else 0

    return {
        "anzahl_einzelfindings": anzahl_einzelfindings,
        "anzahl_risikothemen": anzahl_themen,
        "durchschnittliche_fundstellen_pro_thema": durchschnitt,
        "anzahl_themen_ohne_evidence": themen_ohne_evidence,
        "anzahl_evidence_mehrfach_zugeordnet": mehrfach_zugeordnet,
        "anzahl_themen_mit_nur_1_fundstelle": themen_mit_1,
    }


def berechne_titel_aehnlichkeit(
    themen_titel: list[str],
    schwellenwert: float = 0.6,
) -> list[dict]:
    """Find pairs of topic titles that are suspiciously similar.

    Returns a list of dicts with keys: thema_a, thema_b, aehnlichkeit.
    """
    aehnliche = []
    for i in range(len(themen_titel)):
        for j in range(i + 1, len(themen_titel)):
            score = SequenceMatcher(
                None,
                themen_titel[i].lower(),
                themen_titel[j].lower(),
            ).ratio()
            if score >= schwellenwert:
                aehnliche.append({
                    "thema_a": themen_titel[i],
                    "thema_b": themen_titel[j],
                    "aehnlichkeit": round(score, 2),
                })
    return aehnliche
