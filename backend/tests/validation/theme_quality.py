"""Theme quality validator — detects generic / noisy theme labels.

A theme is "too generic" if:
- It is a single broad-subject noun (e.g. "Compliance", "Audit", "BCM")
- It does not express a concrete contractual problem
- It resembles old noisy bucket labels from the 4-pass pipeline

Good themes name a specific contractual problem with a risk direction:
  "Einseitige Compliance-Anpassungspflichten ohne Kostengrenze"

Bad themes are just topic buckets:
  "Compliance"
"""

from __future__ import annotations

import re

# Broad subject nouns that are NOT acceptable as standalone theme titles.
# These are the exact "bucket labels" that the old pipeline produced.
GENERIC_BUCKETS = {
    "compliance", "audit", "bcm", "haftung", "exit", "reporting",
    "weisungsrecht", "subunternehmer", "informationssicherheit",
    "datenschutz", "sla", "verfügbarkeit", "vertragsmanagement",
    "leistungsumfang", "personalanforderungen", "geistiges eigentum",
    "incident", "vertraulichkeit", "geheimhaltung", "regulatorik",
    "sicherheit", "it-sicherheit", "risikomanagement", "kündigung",
    "transition", "vertragsstrafe", "monitoring",
}

# Risk-direction words that make a title specific (not generic).
# A good title should contain at least one of these.
RISK_DIRECTION_WORDS = {
    "einseitig", "unbegrenzt", "unklar", "offen", "dynamisch",
    "unverhältnismäßig", "pauschal", "unbeschränkt", "uneingeschränkt",
    "vage", "fehlend", "übermäßig", "ohne", "weitreichend",
    "unbestimmt", "unzureichend", "mangelhaft", "riskant",
    "unausgewogen", "unzumutbar", "unkalkulierbar",
    "verlagerung", "übertragung", "durchreichung", "passthrough",
}


def is_generic_theme(title: str) -> bool:
    """Return True if the theme title is too generic to be useful.

    Detection rules:
    1. Exact match against known generic bucket labels
    2. Title < 3 words
    3. Title is only a category noun + optional article/preposition
    4. No risk-direction word present AND title < 5 words
    """
    if not title:
        return True

    normalized = title.strip().lower().rstrip(".")
    words = normalized.split()

    # Rule 1: Exact match against known buckets
    if normalized in GENERIC_BUCKETS:
        return True

    # Rule 2: Too short
    if len(words) < 3:
        return True

    # Rule 3: Just a noun phrase (article + bucket)
    # e.g. "Die Compliance", "Das Audit", "Allgemeine Haftung"
    _FILLERS = {"die", "der", "das", "des", "dem", "den", "ein", "eine",
                "eines", "einem", "allgemeine", "allgemeiner", "allgemeines",
                "weitere", "weiterer", "weiteres", "sonstige", "sonstiger",
                "diverse", "verschiedene", "generelle", "genereller"}
    content_words = [w for w in words if w not in _FILLERS]
    if len(content_words) <= 1:
        return True
    # All content words are generic bucket labels?
    if all(w in GENERIC_BUCKETS for w in content_words):
        return True

    # Rule 4: < 5 words and no risk-direction word
    if len(words) < 5:
        has_direction = any(rd in normalized for rd in RISK_DIRECTION_WORDS)
        if not has_direction:
            return True

    return False


def check_theme_quality(titles: list[str]) -> ThemeQualityReport:
    """Check a list of theme titles for genericness.

    Returns a structured report with pass/fail and details.
    """
    results = []
    for title in titles:
        generic = is_generic_theme(title)
        results.append(ThemeCheckResult(
            title=title,
            is_generic=generic,
            reason=_explain_generic(title) if generic else "",
        ))

    generic_count = sum(1 for r in results if r.is_generic)
    total = len(results)
    generic_rate = generic_count / total if total > 0 else 0.0

    # Threshold: max 20% generic themes allowed
    passed = generic_rate <= 0.20

    return ThemeQualityReport(
        results=results,
        total_themes=total,
        generic_count=generic_count,
        generic_rate=round(generic_rate, 3),
        passed=passed,
        verdict=_verdict(generic_rate, generic_count),
    )


def _explain_generic(title: str) -> str:
    """Explain why a title was flagged as generic."""
    normalized = title.strip().lower().rstrip(".")
    words = normalized.split()

    if normalized in GENERIC_BUCKETS:
        return f"Exact match against known bucket label: '{normalized}'"
    if len(words) < 3:
        return f"Title too short ({len(words)} words) — likely a bucket label"
    if len(words) < 5 and not any(rd in normalized for rd in RISK_DIRECTION_WORDS):
        return f"Short title ({len(words)} words) without risk-direction word"
    return "All content words are generic bucket labels"


def _verdict(rate: float, count: int) -> str:
    if count == 0:
        return "HEALTHY: No generic themes detected"
    if rate <= 0.10:
        return f"HEALTHY: Only {count} generic theme(s) — acceptable"
    if rate <= 0.20:
        return f"BORDERLINE: {count} generic themes ({rate:.0%}) — at threshold"
    if rate <= 0.40:
        return f"NEEDS_REVIEW: {count} generic themes ({rate:.0%}) — too many bucket labels"
    return f"FAILING: {count} generic themes ({rate:.0%}) — pipeline producing noise"


# --- Data classes ---

from dataclasses import dataclass, field


@dataclass
class ThemeCheckResult:
    title: str
    is_generic: bool
    reason: str = ""


@dataclass
class ThemeQualityReport:
    results: list[ThemeCheckResult]
    total_themes: int
    generic_count: int
    generic_rate: float
    passed: bool
    verdict: str
