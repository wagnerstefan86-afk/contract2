"""Thematic grouping of findings for reviewer-friendly presentation.

Groups similar/related findings into higher-level review clusters
without discarding any evidence. Pure post-processing — no DB changes.

MVP approach: keyword-family buckets + category + title similarity.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thematic keyword families — findings matching the same family get grouped
# ---------------------------------------------------------------------------
THEMEN_FAMILIEN: dict[str, list[str]] = {
    "Weisungsrechte & einseitige Anpassungen": [
        "weisung", "anpassung", "einseitig", "änderung", "modifikation",
        "vorbehalt", "ermessen", "unverzüglich", "umsetzung", "direktionsrecht",
    ],
    "Audit, Reporting & Nachweise": [
        "audit", "prüf", "bericht", "nachweis", "report", "sonderbericht",
        "berichtspflicht", "dokumentation", "zertifik", "testat",
        "offenlegung", "einsicht", "zugang",
    ],
    "Regulatorische Durchreichung & Compliance": [
        "regulat", "compliance", "aufsicht", "bafin", "eba", "dora",
        "mait", "bait", "kait", "vait", "durchreich", "auslagerung",
        "dsgvo", "datenschutz", "verordnung", "richtlinie",
        "marisk", "kwg", "bankregulat",
    ],
    "Incident & Meldefristen": [
        "incident", "vorfall", "melde", "frist", "benachrichtig",
        "eskalation", "störung", "sicherheitsvorfall", "breach",
        "unverzüglich", "meldepflicht",
    ],
    "BCM, Disaster Recovery & Verfügbarkeit": [
        "bcm", "disaster", "recovery", "rto", "rpo", "verfügbar",
        "ausfallsicher", "redundan", "notfall", "wiederanlauf",
        "wiederherstellung", "resilienz", "sla", "service level",
    ],
    "Policies, Standards & Stand der Technik": [
        "iso ", "iso-", "stand der technik", "policy", "policies",
        "richtlinie", "standard", "best practice", "rahmenwerk",
        "sicherheitskonzept", "it-sicherheit",
    ],
    "Subunternehmer & Drittdienstleister": [
        "subunternehm", "unterauftrag", "drittdienstleister", "weiterverlager",
        "lieferkette", "supply chain", "sub-dienstleister", "nachunternehm",
    ],
    "Eigentum, Exit & Datenherausgabe": [
        "eigentum", "exit", "herausgabe", "transition", "kündigung",
        "rückgabe", "datenportab", "migration", "beendigung", "löschung",
    ],
    "Haftung & Gewährleistung": [
        "haftung", "gewährleist", "schadenersatz", "freistellung",
        "haftungsbeschränk", "haftungsbegrenz", "versicherung",
        "indemnity", "liability", "schadloshaltung",
    ],
    "Vertraulichkeit & Geheimhaltung": [
        "vertraulich", "geheimhalt", "verschwiegenheit", "nda",
        "non-disclosure", "geheimnis",
    ],
    "Leistungsumfang & Abgrenzung": [
        "leistungsumfang", "leistungsbeschreib", "scope", "abgrenz",
        "change request", "änderungsanforder", "mehrleistung",
    ],
    "Personalanforderungen": [
        "personal", "qualifikation", "schlüsselperson", "key person",
        "fachkund", "schulung", "zuverlässigkeit",
    ],
    "Geistiges Eigentum & Lizenzen": [
        "geistiges eigentum", "intellectual property", "lizenz",
        "nutzungsrecht", "urheberrecht", "patent", "ip-recht",
    ],
}


@dataclass
class GruppiertesFinding:
    """A thematic group of related findings."""
    gruppe_id: str
    titel: str
    kategorie: str
    risikostufe: str  # highest among members
    zusammenfassung: str
    anzahl: int
    fundstellen_ids: list[str] = field(default_factory=list)
    fundstellen: list[dict] = field(default_factory=list)
    themen_familie: str | None = None

    def to_dict(self) -> dict:
        return {
            "gruppe_id": self.gruppe_id,
            "titel": self.titel,
            "kategorie": self.kategorie,
            "risikostufe": self.risikostufe,
            "zusammenfassung": self.zusammenfassung,
            "anzahl": self.anzahl,
            "fundstellen_ids": self.fundstellen_ids,
            "fundstellen": self.fundstellen,
            "themen_familie": self.themen_familie,
        }


# ---------------------------------------------------------------------------
# Risk-level ordering for escalation
# ---------------------------------------------------------------------------
_RISK_ORDER = {"Hoch": 3, "Mittel": 2, "Niedrig": 1, "Hinweis": 0}


def _max_risk(a: str, b: str) -> str:
    return a if _RISK_ORDER.get(a, 0) >= _RISK_ORDER.get(b, 0) else b


def _finding_text_blob(f: dict) -> str:
    """Build a searchable text blob from a finding dict."""
    parts = [
        f.get("kurzbeschreibung", ""),
        f.get("erklaerung", "") or "",
        f.get("textstelle", ""),
        f.get("kategorie", ""),
    ]
    return " ".join(parts).lower()


def _match_themen_familie(text_blob: str) -> str | None:
    """Return the best-matching thematic family for a text blob, or None."""
    best_family = None
    best_score = 0
    for family_name, keywords in THEMEN_FAMILIEN.items():
        score = sum(1 for kw in keywords if kw in text_blob)
        if score > best_score:
            best_score = score
            best_family = family_name
    # Require at least 2 keyword hits for a match
    if best_score >= 2:
        return best_family
    # Fallback: 1 hit is enough for very specific families
    if best_score == 1:
        return best_family
    return None


def _title_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def gruppiere_fundstellen(fundstellen: list[dict]) -> dict:
    """Group a flat list of finding dicts into thematic clusters.

    Args:
        fundstellen: list of finding dicts (as returned by FundstelleResponse)

    Returns:
        dict with:
          - gruppen: list of group dicts
          - debug: grouping statistics
    """
    if not fundstellen:
        return {"gruppen": [], "debug": {"vorher": 0, "nachher": 0, "gruppen_details": []}}

    # Step 1: assign each finding a thematic family
    finding_families: list[tuple[dict, str | None]] = []
    for f in fundstellen:
        blob = _finding_text_blob(f)
        family = _match_themen_familie(blob)
        finding_families.append((f, family))

    # Step 2: bucket by (category, thematic_family)
    buckets: dict[str, list[dict]] = {}
    bucket_families: dict[str, str | None] = {}

    for f, family in finding_families:
        if family:
            # Use the thematic family as the primary grouping key
            key = family
        else:
            # Fallback: group by category alone
            key = f"kategorie:{f.get('kategorie', 'Sonstiges')}"
        buckets.setdefault(key, []).append(f)
        bucket_families[key] = family

    # Step 3: within each bucket, sub-cluster by title similarity
    # to avoid grouping unrelated items that happen to share a category
    final_groups: list[GruppiertesFinding] = []
    group_counter = 0

    for bucket_key, members in buckets.items():
        family = bucket_families.get(bucket_key)

        # Sub-cluster within bucket by title similarity
        sub_clusters: list[list[dict]] = []
        for m in members:
            placed = False
            for cluster in sub_clusters:
                # Compare against first member of cluster (representative)
                sim = _title_similarity(
                    m.get("kurzbeschreibung", ""),
                    cluster[0].get("kurzbeschreibung", ""),
                )
                # Also check if they share the same thematic family
                if family is not None:
                    # Within a thematic family, be more aggressive about merging
                    if sim >= 0.25:
                        cluster.append(m)
                        placed = True
                        break
                else:
                    # No family match — require higher similarity
                    if sim >= 0.5:
                        cluster.append(m)
                        placed = True
                        break
            if not placed:
                sub_clusters.append([m])

        # Now merge very small sub-clusters (≤2 items) back if they share the family
        if family and len(sub_clusters) > 1:
            merged_clusters: list[list[dict]] = []
            small: list[dict] = []
            for sc in sub_clusters:
                if len(sc) <= 2:
                    small.extend(sc)
                else:
                    merged_clusters.append(sc)
            if small:
                if merged_clusters:
                    # Add small items to the largest cluster
                    largest = max(merged_clusters, key=len)
                    largest.extend(small)
                else:
                    merged_clusters.append(small)
            sub_clusters = merged_clusters

        for cluster in sub_clusters:
            group_counter += 1
            # Pick the highest-risk finding as representative
            cluster.sort(key=lambda x: _RISK_ORDER.get(x.get("risikostufe", ""), 0), reverse=True)
            representative = cluster[0]

            # Determine group-level risk (highest)
            group_risk = representative.get("risikostufe", "Hinweis")
            for m in cluster[1:]:
                group_risk = _max_risk(group_risk, m.get("risikostufe", "Hinweis"))

            # Determine group-level category (most common)
            cat_counts: dict[str, int] = {}
            for m in cluster:
                cat = m.get("kategorie", "Sonstiges")
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            group_cat = max(cat_counts, key=cat_counts.get)  # type: ignore[arg-type]

            # Build title
            if family:
                titel = family
            elif len(cluster) == 1:
                titel = representative.get("kurzbeschreibung", "Fundstelle")
            else:
                titel = representative.get("kurzbeschreibung", "Fundstelle")

            # Build summary
            if len(cluster) == 1:
                zusammenfassung = representative.get("erklaerung", "") or representative.get("kurzbeschreibung", "")
            else:
                # List unique short descriptions as sub-aspects
                descriptions = []
                seen = set()
                for m in cluster:
                    desc = m.get("kurzbeschreibung", "")
                    if desc and desc not in seen:
                        seen.add(desc)
                        descriptions.append(desc)
                zusammenfassung = f"{len(cluster)} Einzelfundstellen zu diesem Thema: " + "; ".join(descriptions[:8])
                if len(descriptions) > 8:
                    zusammenfassung += f" … und {len(descriptions) - 8} weitere"

            gruppe = GruppiertesFinding(
                gruppe_id=f"grp-{group_counter}",
                titel=titel,
                kategorie=group_cat,
                risikostufe=group_risk,
                zusammenfassung=zusammenfassung,
                anzahl=len(cluster),
                fundstellen_ids=[m["id"] for m in cluster if "id" in m],
                fundstellen=cluster,
                themen_familie=family,
            )
            final_groups.append(gruppe)

    # Sort groups: by risk (desc), then by member count (desc)
    final_groups.sort(
        key=lambda g: (_RISK_ORDER.get(g.risikostufe, 0), g.anzahl),
        reverse=True,
    )

    # Debug info
    debug = {
        "vorher": len(fundstellen),
        "nachher": len(final_groups),
        "reduktion_prozent": round((1 - len(final_groups) / max(len(fundstellen), 1)) * 100, 1),
        "gruppen_details": [
            {
                "gruppe_id": g.gruppe_id,
                "titel": g.titel,
                "anzahl_fundstellen": g.anzahl,
                "themen_familie": g.themen_familie,
                "risikostufe": g.risikostufe,
                "fundstellen_ids": g.fundstellen_ids,
            }
            for g in final_groups
        ],
    }

    logger.info(
        f"Gruppierung: {len(fundstellen)} Fundstellen -> {len(final_groups)} Gruppen "
        f"({debug['reduktion_prozent']}% Reduktion)"
    )

    return {
        "gruppen": [g.to_dict() for g in final_groups],
        "debug": debug,
    }
