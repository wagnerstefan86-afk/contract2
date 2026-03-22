"""Pipeline calibration metrics — interpretive health checks.

Reads raw pipeline metrics (from auswertung or validation run) and produces
human-readable calibration verdicts. Not just raw numbers — each metric
has a healthy range and an interpretive verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CalibrationMetric:
    """One metric with value + interpretive verdict."""
    name: str
    value: float
    unit: str
    verdict: str  # HEALTHY | BORDERLINE | NEEDS_REVIEW | FAILING
    explanation: str


@dataclass
class CalibrationReport:
    """Full calibration report for one pipeline run."""
    metrics: list[CalibrationMetric] = field(default_factory=list)
    overall_verdict: str = "UNKNOWN"
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "overall_verdict": self.overall_verdict,
            "summary": self.summary,
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "unit": m.unit,
                    "verdict": m.verdict,
                    "explanation": m.explanation,
                }
                for m in self.metrics
            ],
        }


def build_calibration_report(
    total_clauses_read: int,
    clauses_flagged_problematic: int,
    clauses_dropped_non_problematic: int,
    deep_checks_run_total: int,
    problems_after_dedup: int,
    themes_before_editorial: int,
    themes_after_editorial: int,
    counts_by_problem_type: dict[str, int] | None = None,
    counts_by_trigger_domain: dict[str, int] | None = None,
    generic_theme_count: int = 0,
    total_themes: int = 0,
) -> CalibrationReport:
    """Build an interpretive calibration report from pipeline metrics."""

    metrics: list[CalibrationMetric] = []
    counts_by_problem_type = counts_by_problem_type or {}
    counts_by_trigger_domain = counts_by_trigger_domain or {}

    # --- 1. Problematic rate ---
    if total_clauses_read > 0:
        problematic_rate = clauses_flagged_problematic / total_clauses_read
    else:
        problematic_rate = 0.0

    if problematic_rate < 0.05:
        verdict = "NEEDS_REVIEW"
        expl = (
            f"Only {problematic_rate:.0%} of clauses flagged. "
            "Pipeline might be too conservative — check recall on known problem clauses."
        )
    elif problematic_rate < 0.15:
        verdict = "HEALTHY"
        expl = f"{problematic_rate:.0%} flagged — within expected range for IT outsourcing contracts."
    elif problematic_rate < 0.40:
        verdict = "HEALTHY"
        expl = f"{problematic_rate:.0%} flagged — normal for complex regulatory contracts."
    elif problematic_rate < 0.60:
        verdict = "BORDERLINE"
        expl = (
            f"{problematic_rate:.0%} flagged — suspiciously high. "
            "Check if anti-noise rules are being applied."
        )
    else:
        verdict = "FAILING"
        expl = (
            f"{problematic_rate:.0%} flagged — too many clauses flagged. "
            "Pipeline is likely generating noise rather than filtering."
        )

    metrics.append(CalibrationMetric(
        name="problematic_rate",
        value=round(problematic_rate, 3),
        unit="ratio",
        verdict=verdict,
        explanation=expl,
    ))

    # --- 2. Deep-check escalation rate ---
    if clauses_flagged_problematic > 0:
        escalation_rate = deep_checks_run_total / clauses_flagged_problematic
    else:
        escalation_rate = 0.0

    if escalation_rate < 0.3:
        verdict = "NEEDS_REVIEW"
        expl = (
            f"Low escalation rate ({escalation_rate:.1f} checks/clause). "
            "Deep checks might not be triggered — check trigger_domains."
        )
    elif escalation_rate <= 2.0:
        verdict = "HEALTHY"
        expl = f"{escalation_rate:.1f} deep checks per flagged clause — normal."
    elif escalation_rate <= 4.0:
        verdict = "BORDERLINE"
        expl = (
            f"{escalation_rate:.1f} deep checks per clause — moderately high. "
            "Some clauses might trigger too many domains."
        )
    else:
        verdict = "FAILING"
        expl = (
            f"{escalation_rate:.1f} deep checks per clause — too high. "
            "Every clause is escalating to many domains — routing too broad."
        )

    metrics.append(CalibrationMetric(
        name="deep_check_escalation_rate",
        value=round(escalation_rate, 2),
        unit="checks/clause",
        verdict=verdict,
        explanation=expl,
    ))

    # --- 3. Dedup compression rate ---
    if clauses_flagged_problematic > 0:
        dedup_rate = problems_after_dedup / clauses_flagged_problematic
    else:
        dedup_rate = 1.0

    if dedup_rate < 0.3:
        verdict = "NEEDS_REVIEW"
        expl = (
            f"Heavy dedup compression ({dedup_rate:.0%} surviving). "
            "Many findings are duplicates — check if risk_screen is producing too-similar outputs."
        )
    elif dedup_rate <= 0.9:
        verdict = "HEALTHY"
        expl = f"{dedup_rate:.0%} surviving dedup — normal overlap reduction."
    else:
        verdict = "HEALTHY"
        expl = f"{dedup_rate:.0%} surviving dedup — minimal overlap (good for diverse contracts)."

    metrics.append(CalibrationMetric(
        name="dedup_survival_rate",
        value=round(dedup_rate, 3),
        unit="ratio",
        verdict=verdict,
        explanation=expl,
    ))

    # --- 4. Editorial reduction ---
    if themes_before_editorial > 0:
        editorial_rate = themes_after_editorial / themes_before_editorial
    else:
        editorial_rate = 0.0

    if editorial_rate < 0.3:
        verdict = "NEEDS_REVIEW"
        expl = (
            f"Editorial discarded {1 - editorial_rate:.0%} of themes. "
            "Clustering may be producing too many weak themes."
        )
    elif editorial_rate <= 0.8:
        verdict = "HEALTHY"
        expl = f"Editorial kept {editorial_rate:.0%} — healthy reduction."
    else:
        verdict = "BORDERLINE"
        expl = (
            f"Editorial kept {editorial_rate:.0%} — almost no reduction. "
            "Check if editorial pass is applying quality filters."
        )

    metrics.append(CalibrationMetric(
        name="editorial_retention_rate",
        value=round(editorial_rate, 3),
        unit="ratio",
        verdict=verdict,
        explanation=expl,
    ))

    # --- 5. Problem type diversity ---
    unique_types = len(counts_by_problem_type)
    if unique_types < 3:
        verdict = "NEEDS_REVIEW"
        expl = f"Only {unique_types} distinct problem types — pipeline may be too narrow."
    elif unique_types <= 10:
        verdict = "HEALTHY"
        expl = f"{unique_types} distinct problem types — good diversity."
    else:
        verdict = "HEALTHY"
        expl = f"{unique_types} distinct problem types — broad coverage."

    metrics.append(CalibrationMetric(
        name="problem_type_diversity",
        value=float(unique_types),
        unit="count",
        verdict=verdict,
        explanation=expl,
    ))

    # --- 6. Trigger domain diversity ---
    unique_domains = len(counts_by_trigger_domain)
    if unique_domains < 2:
        verdict = "NEEDS_REVIEW"
        expl = f"Only {unique_domains} trigger domain(s) — deep checks might be too narrow."
    elif unique_domains <= 7:
        verdict = "HEALTHY"
        expl = f"{unique_domains} trigger domains — good routing diversity."
    else:
        verdict = "HEALTHY"
        expl = f"{unique_domains} trigger domains — broad deep-check routing."

    metrics.append(CalibrationMetric(
        name="trigger_domain_diversity",
        value=float(unique_domains),
        unit="count",
        verdict=verdict,
        explanation=expl,
    ))

    # --- 7. Generic theme rate ---
    if total_themes > 0:
        generic_rate = generic_theme_count / total_themes
    else:
        generic_rate = 0.0

    if generic_rate == 0.0:
        verdict = "HEALTHY"
        expl = "No generic themes — all titles are problem-specific."
    elif generic_rate <= 0.20:
        verdict = "BORDERLINE"
        expl = f"{generic_theme_count}/{total_themes} generic themes — at acceptable threshold."
    else:
        verdict = "FAILING"
        expl = (
            f"{generic_theme_count}/{total_themes} generic themes ({generic_rate:.0%}). "
            "Pipeline is still producing bucket-label noise."
        )

    metrics.append(CalibrationMetric(
        name="generic_theme_rate",
        value=round(generic_rate, 3),
        unit="ratio",
        verdict=verdict,
        explanation=expl,
    ))

    # --- Overall verdict ---
    verdicts = [m.verdict for m in metrics]
    if "FAILING" in verdicts:
        overall = "FAILING"
        summary = "Pipeline has critical calibration issues that need fixing."
    elif verdicts.count("NEEDS_REVIEW") >= 2:
        overall = "NEEDS_REVIEW"
        summary = "Multiple metrics outside healthy range — investigate."
    elif "NEEDS_REVIEW" in verdicts:
        overall = "BORDERLINE"
        summary = "Mostly healthy with one metric needing attention."
    elif "BORDERLINE" in verdicts:
        overall = "HEALTHY_WITH_NOTES"
        summary = "Pipeline operating well — minor calibration notes."
    else:
        overall = "HEALTHY"
        summary = "All metrics within expected ranges."

    return CalibrationReport(
        metrics=metrics,
        overall_verdict=overall,
        summary=summary,
    )
