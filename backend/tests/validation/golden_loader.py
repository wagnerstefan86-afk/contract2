"""Load and validate golden testset cases from JSON fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "contract_validation_cases"


@dataclass(frozen=True)
class GoldenCase:
    """One validation case from the golden testset."""
    case_id: str
    short_name: str
    case_type: str  # "single_clause" | "mini_contract"
    clause_text: str
    expected_problematic: bool
    expected_problem_types: list[str] = field(default_factory=list)
    expected_trigger_domains: list[str] = field(default_factory=list)
    expected_severity_min: Optional[str] = None
    expected_theme_keywords: list[str] = field(default_factory=list)
    forbidden_theme_keywords: list[str] = field(default_factory=list)
    notes: str = ""


def load_golden_cases(filename: str = "golden_clauses.json") -> list[GoldenCase]:
    """Load all golden cases from the given JSON file."""
    path = FIXTURES_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cases = []
    for entry in raw:
        cases.append(GoldenCase(
            case_id=entry["case_id"],
            short_name=entry["short_name"],
            case_type=entry.get("case_type", "single_clause"),
            clause_text=entry["clause_text"],
            expected_problematic=entry["expected_problematic"],
            expected_problem_types=entry.get("expected_problem_types", []),
            expected_trigger_domains=entry.get("expected_trigger_domains", []),
            expected_severity_min=entry.get("expected_severity_min"),
            expected_theme_keywords=entry.get("expected_theme_keywords", []),
            forbidden_theme_keywords=entry.get("forbidden_theme_keywords", []),
            notes=entry.get("notes", ""),
        ))
    return cases


def positive_cases(cases: list[GoldenCase] | None = None) -> list[GoldenCase]:
    """Return only positive (must-detect) cases."""
    if cases is None:
        cases = load_golden_cases()
    return [c for c in cases if c.expected_problematic]


def negative_cases(cases: list[GoldenCase] | None = None) -> list[GoldenCase]:
    """Return only negative (must-drop) cases."""
    if cases is None:
        cases = load_golden_cases()
    return [c for c in cases if not c.expected_problematic]
