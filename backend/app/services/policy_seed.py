"""Seed loader for policy profiles and rules from YAML.

Loads the initial policy seed on startup if no active profile exists.
Idempotent: skips if a profile with the same name + version already exists.
"""

import json
import logging
import os
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy_profile import PolicyProfile, PolicyRule

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).parent.parent / "data" / "policy_seed.yaml"


async def seed_policy_profile(db: AsyncSession, seed_path: str | Path | None = None) -> PolicyProfile | None:
    """Load policy seed from YAML and persist if not already present.

    Returns the active PolicyProfile or None if seeding was skipped.
    """
    path = Path(seed_path) if seed_path else SEED_PATH
    if not path.exists():
        logger.warning(f"Policy-Seed-Datei nicht gefunden: {path}")
        return None

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "policy_profile" not in data:
        logger.warning("Policy-Seed-Datei enthält kein gültiges policy_profile")
        return None

    profile_data = data["policy_profile"]
    rules_data = data.get("rules", [])

    name = profile_data["name"]
    version = profile_data["version"]

    # Check if profile already exists
    result = await db.execute(
        select(PolicyProfile).where(
            PolicyProfile.name == name,
            PolicyProfile.version == version,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        logger.info(f"Policy-Profil '{name}' v{version} bereits vorhanden, Seed übersprungen")
        return existing

    # Create profile
    profile = PolicyProfile(
        name=name,
        version=version,
        description=profile_data.get("description"),
        is_active=True,
    )
    db.add(profile)
    await db.flush()

    # Create rules
    for rule_data in rules_data:
        # pattern can be a list (KEYWORD_SET) or string (REGEX/EXACT)
        pattern = rule_data.get("pattern", "")
        if isinstance(pattern, list):
            pattern_str = json.dumps(pattern, ensure_ascii=False)
        else:
            pattern_str = str(pattern)

        rule = PolicyRule(
            policy_profile_id=profile.id,
            name=rule_data["name"],
            description=rule_data.get("description"),
            rule_type=rule_data["rule_type"],
            match_scope=rule_data["match_scope"],
            pattern_type=rule_data["pattern_type"],
            pattern=pattern_str,
            action=rule_data["action"],
            priority=rule_data.get("priority", 0),
            is_active=True,
            conditions_json=rule_data.get("conditions_json"),
        )
        db.add(rule)

    await db.commit()
    logger.info(f"Policy-Profil '{name}' v{version} mit {len(rules_data)} Regeln angelegt")
    return profile
