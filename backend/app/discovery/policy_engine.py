"""Policy Engine — matches rules against document sections and findings.

Runs BEFORE the expensive LLM extraction to route sections and flag
positive controls, out-of-scope content, and suppressed risks.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy_profile import PolicyProfile, PolicyRule
from app.models.enums import (
    RuleAction, MatchScope, PatternType, SectionRouting,
)

logger = logging.getLogger(__name__)

# Third-country indicators that prevent geo-location suppression
THIRD_COUNTRY_INDICATORS = [
    "drittland", "drittländer", "third country", "third-country",
    "usa", "united states", "indien", "india", "china",
    "offshore", "nearshore",
    "zugriff außerhalb", "zugriff ausserhalb",
    "admin-zugriff", "fernzugriff", "remote access",
    "subunternehmer in", "sub-dienstleister in",
]


@dataclass
class PolicyMatch:
    """Result of a single policy rule matching against text."""
    rule_id: str
    rule_name: str
    rule_type: str
    action: str
    priority: int
    matched_text: str
    conditions: dict | None = None


@dataclass
class SectionScanResult:
    """Complete policy scan result for a document section."""
    routing: SectionRouting = SectionRouting.REVIEWABLE
    routing_reason: str = ""
    matches: list[PolicyMatch] = field(default_factory=list)
    positive_controls: list[PolicyMatch] = field(default_factory=list)
    out_of_scope: bool = False
    out_of_scope_reason: str = ""
    require_review: bool = False


async def load_active_rules(db: AsyncSession, profile_id: str | None = None) -> list[PolicyRule]:
    """Load active policy rules, optionally filtered by profile."""
    query = select(PolicyRule).where(PolicyRule.is_active == True)
    if profile_id:
        query = query.where(PolicyRule.policy_profile_id == profile_id)
    else:
        # Load rules from the active profile
        profile_result = await db.execute(
            select(PolicyProfile).where(PolicyProfile.is_active == True).limit(1)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            return []
        query = query.where(PolicyRule.policy_profile_id == profile.id)

    query = query.order_by(PolicyRule.priority.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


def scan_section(text: str, rules: list[PolicyRule]) -> SectionScanResult:
    """Scan a section text against all policy rules and determine routing.

    Rules are evaluated in priority order (highest first).
    The first REQUIRE_REVIEW match overrides suppression.
    """
    result = SectionScanResult()
    text_lower = text.lower()

    for rule in rules:
        if rule.match_scope != MatchScope.SECTION_TEXT.value:
            continue

        matched = _match_pattern(text, text_lower, rule)
        if not matched:
            continue

        match = PolicyMatch(
            rule_id=str(rule.id),
            rule_name=rule.name,
            rule_type=rule.rule_type,
            action=rule.action,
            priority=rule.priority,
            matched_text=matched,
            conditions=rule.conditions_json,
        )
        result.matches.append(match)

        if rule.action == RuleAction.REQUIRE_REVIEW.value:
            result.require_review = True

        elif rule.action == RuleAction.MARK_POSITIVE_CONTROL.value:
            result.positive_controls.append(match)

        elif rule.action == RuleAction.OUT_OF_SCOPE.value:
            result.out_of_scope = True
            result.out_of_scope_reason = rule.description or rule.name

        elif rule.action == RuleAction.SUPPRESS_RISK.value:
            # Check conditions for geo-location suppression
            if rule.conditions_json and rule.conditions_json.get("no_third_country_indicator"):
                if _has_third_country_indicator(text_lower):
                    logger.debug(
                        f"Rule '{rule.name}': Suppression verhindert — Drittland-Indikator gefunden"
                    )
                    continue  # Don't suppress

    # Determine final routing based on collected matches
    result.routing, result.routing_reason = _determine_routing(result)
    return result


def scan_finding(
    title: str,
    category: str,
    rules: list[PolicyRule],
) -> list[PolicyMatch]:
    """Scan a finding title/category against FINDING_TITLE/FINDING_CATEGORY rules.

    Returns list of matching rules (for post-extraction suppression/enrichment).
    """
    matches = []
    for rule in rules:
        if rule.match_scope == MatchScope.FINDING_TITLE.value:
            matched = _match_pattern(title, title.lower(), rule)
            if matched:
                matches.append(PolicyMatch(
                    rule_id=str(rule.id),
                    rule_name=rule.name,
                    rule_type=rule.rule_type,
                    action=rule.action,
                    priority=rule.priority,
                    matched_text=matched,
                    conditions=rule.conditions_json,
                ))
        elif rule.match_scope == MatchScope.FINDING_CATEGORY.value:
            matched = _match_pattern(category, category.lower(), rule)
            if matched:
                matches.append(PolicyMatch(
                    rule_id=str(rule.id),
                    rule_name=rule.name,
                    rule_type=rule.rule_type,
                    action=rule.action,
                    priority=rule.priority,
                    matched_text=matched,
                    conditions=rule.conditions_json,
                ))
    return matches


def _match_pattern(text: str, text_lower: str, rule: PolicyRule) -> str:
    """Try to match a rule's pattern against text. Returns matched substring or empty string."""
    if rule.pattern_type == PatternType.KEYWORD_SET.value:
        # Pattern is JSON-encoded list of keywords
        try:
            keywords = json.loads(rule.pattern) if rule.pattern.startswith("[") else [rule.pattern]
        except json.JSONDecodeError:
            keywords = [rule.pattern]

        for keyword in keywords:
            kw_lower = keyword.lower()
            idx = text_lower.find(kw_lower)
            if idx >= 0:
                return text[idx:idx + len(keyword)]
        return ""

    elif rule.pattern_type == PatternType.REGEX.value:
        try:
            match = re.search(rule.pattern, text)
            if match:
                return match.group(0)
        except re.error as e:
            logger.warning(f"Regex-Fehler in Rule '{rule.name}': {e}")
        return ""

    elif rule.pattern_type == PatternType.EXACT.value:
        if rule.pattern.lower() in text_lower:
            return rule.pattern
        return ""

    elif rule.pattern_type == PatternType.NORMALIZED_LOOKUP.value:
        if rule.normalized_value and rule.normalized_value.lower() in text_lower:
            return rule.normalized_value
        return ""

    return ""


def _has_third_country_indicator(text_lower: str) -> bool:
    """Check if text contains third-country indicators that prevent geo suppression."""
    return any(indicator in text_lower for indicator in THIRD_COUNTRY_INDICATORS)


def _determine_routing(result: SectionScanResult) -> tuple[SectionRouting, str]:
    """Determine final section routing from collected matches.

    Priority logic:
    1. REQUIRE_REVIEW always wins → REVIEWABLE
    2. OUT_OF_SCOPE → OUT_OF_SCOPE (unless overridden by REQUIRE_REVIEW)
    3. POSITIVE_CONTROL only → POSITIVE_CONTROL
    4. No relevant matches → REVIEWABLE (default)
    """
    if result.require_review:
        return SectionRouting.REVIEWABLE, "REQUIRE_REVIEW-Regel greift — Pflichtprüfung"

    if result.out_of_scope and not result.positive_controls:
        return SectionRouting.OUT_OF_SCOPE, result.out_of_scope_reason

    if result.positive_controls and not result.out_of_scope:
        # Section has positive controls but may also need review for other aspects
        # Only mark as POSITIVE_CONTROL if no other risk-relevant content
        return SectionRouting.POSITIVE_CONTROL, (
            f"Positive Control erkannt: {result.positive_controls[0].matched_text}"
        )

    if result.out_of_scope and result.positive_controls:
        # Both out-of-scope and positive control — treat as context only
        return SectionRouting.CONTEXT_ONLY, (
            "Section enthält sowohl Out-of-Scope als auch Positive Control — nur als Kontext verwenden"
        )

    return SectionRouting.REVIEWABLE, "Keine Policy-Einschränkung — reguläre Prüfung"
