#!/usr/bin/env python3
"""Evaluation and calibration script for the multi-document case pipeline.

Usage:
    python scripts/evaluate_case_pipeline.py --dir /path/to/contracts
    python scripts/evaluate_case_pipeline.py --dir ./test_contracts --export report.json
    python scripts/evaluate_case_pipeline.py --case-id <existing-uuid>

# METRIC GLOSSARY
#
# This script reports metrics at distinct pipeline layers. Each layer operates
# on a SUBSET of the previous layer's output. Metrics from different layers
# are not directly comparable.
#
# VOLUME LAYER
#   sections_total          All sections across all documents after splitting.
#
# POLICY LAYER (deterministic rule engine, no LLM)
#   policy_reviewable       Sections routed to "REVIEWABLE" by policy rules.
#                           Only these proceed to LLM screening.
#   policy_out_of_scope     Sections removed by policy (e.g. privacy/data protection).
#   policy_positive_control Sections containing certifications/standards.
#   policy_context_only     Sections kept for context but not reviewed.
#   policy_no_routing       Sections not yet processed by policy (should be 0).
#
# SCREENING LAYER (LLM classification of REVIEWABLE sections)
#   screening_input         Number of REVIEWABLE sections sent to LLM screening.
#                           Must equal policy_reviewable (or <= if some already screened).
#   screening_risk_candidate  Sections classified as risk-bearing → proceed to extraction.
#   screening_context       Sections classified as contextual → not extracted.
#   screening_ignored       Sections classified as irrelevant → discarded.
#   screening_error         Sections where screening LLM call failed.
#
# EXTRACTION LAYER (LLM finding extraction from risk_candidate sections)
#   sections_extracted      Sections that completed extraction (== screening_risk_candidate).
#   findings_created        Individual risk findings extracted.
#   positive_controls_found Positive assurances (certifications, standards) found.
#
# THEME LAYER
#   clusters_created        Themes after initial clustering.
#   themes_after_consolidation  Themes after merging overlapping clusters.
#   themes_final            Themes selected by editorial as negotiation-relevant.
#
# OUT-OF-SCOPE
#   DATA_PROTECTION findings are separated from the main risk distribution
#   because privacy/data protection is typically handled in a separate review
#   stream and should not influence InfoSec risk calibration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime


try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Install with: pip install requests")
    sys.exit(1)


# Categories treated as out-of-scope for InfoSec risk calibration.
# Findings in these categories are shown separately and excluded from
# the main risk distribution analysis.
OUT_OF_SCOPE_CATEGORIES = {"DATA_PROTECTION"}


# ---------------------------------------------------------------------------
# Verdict levels
# ---------------------------------------------------------------------------

VERDICT_HEALTHY = "HEALTHY"
VERDICT_HEALTHY_WITH_NOTES = "HEALTHY_WITH_NOTES"
VERDICT_NEEDS_REVIEW = "NEEDS_REVIEW"
VERDICT_INCONSISTENT = "INCONSISTENT_METRICS"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EvalReport:
    """Full evaluation report with layered metric semantics."""
    case_id: str = ""
    title: str = ""
    status: str = ""
    failure_reason: str | None = None
    documents: int = 0
    processing_time_seconds: float = 0.0
    llm_calls_total: int = 0

    # Volume
    sections_total: int = 0

    # Policy layer (from section-counts API)
    policy_reviewable: int = 0
    policy_out_of_scope: int = 0
    policy_positive_control: int = 0
    policy_context_only: int = 0
    policy_ignore: int = 0
    policy_no_routing: int = 0

    # Screening layer (from pipeline metrics)
    screening_input: int = 0        # sections sent to LLM screening
    screening_risk_candidate: int = 0
    screening_context: int = 0
    screening_ignored: int = 0
    screening_error: int = 0

    # Extraction layer
    sections_extracted: int = 0     # from extraction metrics
    findings_created: int = 0
    positive_controls_found: int = 0

    # Theme layer
    clusters_created: int = 0
    themes_after_consolidation: int = 0
    themes_final: int = 0

    # Diagnostics
    screening_ratio: float = 0.0
    screening_verdict: str = ""
    singleton_clusters: int = 0
    mixed_category_clusters: int = 0
    avg_cluster_size: float = 0.0
    singleton_rate: float = 0.0
    cluster_verdict: str = ""
    cluster_details: list[dict] = field(default_factory=list)
    editorial_reduction_pct: float = 0.0
    editorial_verdict: str = ""

    # Category distribution — in-scope only
    category_distribution: dict[str, int] = field(default_factory=dict)
    category_imbalance: list[str] = field(default_factory=list)

    # Out-of-scope categories (separated)
    out_of_scope_distribution: dict[str, int] = field(default_factory=dict)

    # Final themes
    final_themes: list[dict] = field(default_factory=list)

    # Warnings, consistency issues, suggestions
    pipeline_warnings: list[str] = field(default_factory=list)
    consistency_issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    # Overall verdict
    final_verdict: str = ""

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "final_verdict": self.final_verdict,
            "volume": {
                "documents": self.documents,
                "sections_total": self.sections_total,
                "processing_time_seconds": self.processing_time_seconds,
                "llm_calls_total": self.llm_calls_total,
            },
            "policy_layer": {
                "reviewable": self.policy_reviewable,
                "out_of_scope": self.policy_out_of_scope,
                "positive_control": self.policy_positive_control,
                "context_only": self.policy_context_only,
                "ignore": self.policy_ignore,
                "no_routing": self.policy_no_routing,
            },
            "screening_layer": {
                "input": self.screening_input,
                "risk_candidate": self.screening_risk_candidate,
                "context": self.screening_context,
                "ignored": self.screening_ignored,
                "error": self.screening_error,
                "ratio": self.screening_ratio,
                "verdict": self.screening_verdict,
            },
            "extraction_layer": {
                "sections_extracted": self.sections_extracted,
                "findings_created": self.findings_created,
                "positive_controls_found": self.positive_controls_found,
            },
            "theme_layer": {
                "clusters_created": self.clusters_created,
                "themes_after_consolidation": self.themes_after_consolidation,
                "themes_final": self.themes_final,
            },
            "diagnostics": {
                "clustering": {
                    "singleton_clusters": self.singleton_clusters,
                    "mixed_category_clusters": self.mixed_category_clusters,
                    "avg_cluster_size": self.avg_cluster_size,
                    "singleton_rate": self.singleton_rate,
                    "verdict": self.cluster_verdict,
                    "details": self.cluster_details,
                },
                "editorial": {
                    "reduction_pct": self.editorial_reduction_pct,
                    "verdict": self.editorial_verdict,
                },
                "categories_in_scope": self.category_distribution,
                "categories_out_of_scope": self.out_of_scope_distribution,
                "category_imbalance": self.category_imbalance,
            },
            "themes": self.final_themes,
            "pipeline_warnings": self.pipeline_warnings,
            "consistency_issues": self.consistency_issues,
            "suggestions": self.suggestions,
            "generated_at": datetime.utcnow().isoformat(),
        }


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------

class APIClient:
    """Thin wrapper around requests for the case API."""

    def __init__(self, base_url: str, token: str = ""):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def get(self, path: str, params: dict | None = None) -> dict | list:
        resp = requests.get(f"{self.base}{path}", headers=self.headers, params=params)
        resp.raise_for_status()
        return resp.json()

    def post(self, path: str, json_body: dict | None = None, files=None) -> dict:
        resp = requests.post(
            f"{self.base}{path}",
            headers=self.headers,
            json=json_body,
            files=files,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------

def create_and_run_case(api: APIClient, doc_dir: str, title: str, timeout: int) -> str:
    """Create case, upload documents, run pipeline, return case_id."""
    files = sorted(
        f for f in os.listdir(doc_dir)
        if f.lower().endswith((".pdf", ".docx", ".doc", ".txt"))
    )
    if not files:
        print(f"ERROR: No documents found in '{doc_dir}'.")
        sys.exit(1)

    print(f"Found {len(files)} document(s) in {doc_dir}")
    _sep()

    _step("Creating AnalysisCase")
    case = api.post("/cases", {"title": title, "customer_name": "Evaluation"})
    case_id = case["id"]
    print(f"   Case created: {case_id}")

    _step(f"Uploading {len(files)} documents")
    for filename in files:
        filepath = os.path.join(doc_dir, filename)
        with open(filepath, "rb") as f:
            doc = api.post(
                f"/cases/{case_id}/documents",
                files={"datei": (filename, f)},
            )
            print(f"   {filename} -> {doc['id'][:8]}...")

    _step("Starting pipeline")
    api.post(f"/cases/{case_id}/analyze")
    print("   Pipeline started.")

    _step("Waiting for completion")
    start = time.time()
    last_status = ""
    while True:
        elapsed = time.time() - start
        if elapsed > timeout:
            print(f"   TIMEOUT after {timeout}s")
            sys.exit(1)

        case = api.get(f"/cases/{case_id}")
        status = case["status"]
        if status != last_status:
            print(f"   [{elapsed:5.0f}s] {status}")
            last_status = status
        if status in ("Completed", "Failed"):
            break
        time.sleep(5)

    print(f"   Finished in {time.time() - start:.1f}s — status: {case['status']}")
    if case.get("failure_reason"):
        print(f"   FAILURE: {case['failure_reason']}")

    return case_id


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect_report(api: APIClient, case_id: str) -> EvalReport:
    """Collect all data from APIs and build the evaluation report."""
    r = EvalReport(case_id=case_id)

    # Case detail
    case = api.get(f"/cases/{case_id}")
    r.title = case.get("title", "")
    r.status = case.get("status", "")
    r.failure_reason = case.get("failure_reason")
    r.pipeline_warnings = list(case.get("pipeline_warnings") or [])
    r.documents = case.get("total_documents", 0)

    # Section counts — the authoritative source for policy vs screening layer
    try:
        sc = api.get(f"/cases/{case_id}/section-counts")
        r.sections_total = sc.get("sections_total", 0)
        pl = sc.get("policy_layer", {})
        r.policy_reviewable = pl.get("reviewable", 0)
        r.policy_out_of_scope = pl.get("out_of_scope", 0)
        r.policy_positive_control = pl.get("positive_control", 0)
        r.policy_context_only = pl.get("context_only", 0)
        r.policy_ignore = pl.get("ignore", 0)
        r.policy_no_routing = pl.get("no_routing", 0)
        sl = sc.get("screening_layer", {})
        r.screening_risk_candidate = sl.get("analyze", 0)
        r.screening_context = sl.get("context", 0)
        r.screening_ignored = sl.get("ignored", 0)
        r.screening_error = sl.get("error", 0)
        # screening_input = all sections that went through screening
        r.screening_input = (
            r.screening_risk_candidate + r.screening_context
            + r.screening_ignored + r.screening_error
        )
    except Exception as e:
        print(f"   (section-counts unavailable: {e}, falling back to metrics)")

    # Pipeline metrics — for extraction/theme layer + timing
    try:
        m = api.get(f"/cases/{case_id}/metrics")
        r.findings_created = m.get("findings_created", 0)
        r.positive_controls_found = m.get("positive_controls_found", 0)
        r.clusters_created = m.get("clusters_created", 0)
        r.themes_after_consolidation = m.get("themes_after_consolidation", 0)
        r.themes_final = m.get("themes_final", 0)
        r.processing_time_seconds = m.get("processing_time_seconds", 0.0)
        r.llm_calls_total = m.get("llm_calls_total", 0)

        # Fallback: if section-counts API was unavailable, use metrics
        # (these are screening-layer counts, NOT total sections)
        if r.sections_total == 0:
            r.screening_input = m.get("sections_total", 0)
            r.screening_risk_candidate = m.get("sections_analyzed", 0)
            r.screening_ignored = m.get("sections_ignored", 0)
            r.screening_context = m.get("sections_context", 0)

        # sections_extracted is the extraction step's input count
        r.sections_extracted = m.get("sections_analyzed", 0)
    except Exception as e:
        print(f"   (metrics unavailable: {e})")

    # Summary — fallback for document count and total sections
    try:
        s = api.get(f"/cases/{case_id}/summary")
        if r.documents == 0:
            r.documents = s.get("documents", 0)
        if r.sections_total == 0:
            r.sections_total = s.get("sections_total", 0)
    except Exception:
        pass

    # Themes — all themes for category distribution + final themes for detail
    try:
        themes_resp = api.get(f"/cases/{case_id}/themes")
        all_themes = themes_resp.get("themes", [])

        for t in all_themes:
            cat = t.get("category", "OTHER")
            finding_count = t.get("source_finding_count", 0)

            # Separate out-of-scope categories
            if cat in OUT_OF_SCOPE_CATEGORIES:
                r.out_of_scope_distribution[cat] = (
                    r.out_of_scope_distribution.get(cat, 0) + finding_count
                )
            else:
                r.category_distribution[cat] = (
                    r.category_distribution.get(cat, 0) + finding_count
                )

            if t.get("final_selected"):
                r.final_themes.append({
                    "rank": t.get("final_rank"),
                    "title": t.get("canonical_title", "?"),
                    "category": cat,
                    "severity": t.get("severity", "?"),
                    "evidence_count": len(t.get("evidence", [])),
                    "source_finding_count": finding_count,
                    "source_document_count": t.get("source_document_count", 0),
                    "conflict_detected": t.get("conflict_detected", False),
                    "editorial": t.get("final_editorial_json") or {},
                })

        r.final_themes.sort(key=lambda x: x.get("rank") or 999)
    except Exception as e:
        print(f"   (themes unavailable: {e})")

    # Debug snapshots — cluster diagnostics
    try:
        snapshots = api.get(f"/cases/{case_id}/debug-snapshots")
        for snap in snapshots:
            if snap.get("stage") == "cluster_output":
                diagnostics = (snap.get("data_json") or {}).get("diagnostics", [])
                r.cluster_details = diagnostics
                for d in diagnostics:
                    if d.get("is_singleton"):
                        r.singleton_clusters += 1
                    if d.get("is_mixed_category"):
                        r.mixed_category_clusters += 1
    except Exception as e:
        print(f"   (debug snapshots unavailable: {e})")

    return r


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def run_diagnostics(report: EvalReport) -> None:
    """Run all quality analyses, consistency checks, and generate suggestions."""
    _check_consistency(report)
    _diagnose_screening(report)
    _diagnose_clustering(report)
    _diagnose_editorial(report)
    _diagnose_categories(report)
    _generate_suggestions(report)
    _compute_final_verdict(report)


def _check_consistency(r: EvalReport) -> None:
    """Task 3: Semantic consistency checks between pipeline layers."""

    # Check 1: screening_input must be <= policy_reviewable
    if r.policy_reviewable > 0 and r.screening_input > r.policy_reviewable:
        r.consistency_issues.append(
            f"screening_input ({r.screening_input}) > policy_reviewable ({r.policy_reviewable}). "
            "More sections were LLM-screened than the policy layer marked reviewable."
        )

    # Check 2: screening sub-counts must sum to screening_input
    screening_sum = (
        r.screening_risk_candidate + r.screening_context
        + r.screening_ignored + r.screening_error
    )
    if r.screening_input > 0 and screening_sum != r.screening_input:
        r.consistency_issues.append(
            f"Screening sub-counts (risk={r.screening_risk_candidate} + context={r.screening_context} "
            f"+ ignored={r.screening_ignored} + error={r.screening_error} = {screening_sum}) "
            f"!= screening_input ({r.screening_input})."
        )

    # Check 3: sections_extracted must be <= screening_risk_candidate
    if r.sections_extracted > 0 and r.sections_extracted > r.screening_risk_candidate:
        r.consistency_issues.append(
            f"sections_extracted ({r.sections_extracted}) > screening_risk_candidate "
            f"({r.screening_risk_candidate}). More sections extracted than were marked as risk candidates."
        )

    # Check 4: policy layer should sum to sections_total
    if r.sections_total > 0:
        policy_sum = (
            r.policy_reviewable + r.policy_out_of_scope + r.policy_positive_control
            + r.policy_context_only + r.policy_ignore + r.policy_no_routing
        )
        if policy_sum > 0 and policy_sum != r.sections_total:
            r.consistency_issues.append(
                f"Policy routing counts sum to {policy_sum} but sections_total is {r.sections_total}. "
                "Some sections may have unexpected routing values."
            )

    # Check 5: themes_final must be <= themes_after_consolidation
    if r.themes_final > r.themes_after_consolidation > 0:
        r.consistency_issues.append(
            f"themes_final ({r.themes_final}) > themes_after_consolidation "
            f"({r.themes_after_consolidation}). Final editorial selected more themes than existed."
        )


def _diagnose_screening(r: EvalReport) -> None:
    """Screening quality: what fraction of LLM-screened sections became risk candidates."""
    if r.screening_input == 0:
        r.screening_verdict = "NO_DATA"
        return

    r.screening_ratio = r.screening_risk_candidate / r.screening_input

    if r.screening_ratio < 0.05:
        r.screening_verdict = VERDICT_NEEDS_REVIEW
        r.pipeline_warnings.append(
            f"SCREENING_OVER_AGGRESSIVE: Only {r.screening_ratio:.1%} of LLM-screened sections "
            f"passed as risk_candidate ({r.screening_risk_candidate}/{r.screening_input}). "
            "Risk of missing important clauses."
        )
    elif r.screening_ratio > 0.40:
        r.screening_verdict = VERDICT_HEALTHY_WITH_NOTES
        r.pipeline_warnings.append(
            f"SCREENING_WEAK: {r.screening_ratio:.1%} of LLM-screened sections passed "
            f"({r.screening_risk_candidate}/{r.screening_input}). "
            "Screening provides little reduction — high LLM cost in extraction."
        )
    else:
        r.screening_verdict = VERDICT_HEALTHY


def _diagnose_clustering(r: EvalReport) -> None:
    """Cluster quality from debug snapshots."""
    if r.clusters_created == 0:
        r.cluster_verdict = "NO_DATA"
        return

    r.singleton_rate = r.singleton_clusters / r.clusters_created

    if r.cluster_details:
        sizes = [d.get("cluster_size", 1) for d in r.cluster_details]
        r.avg_cluster_size = sum(sizes) / len(sizes) if sizes else 0.0
    elif r.findings_created > 0:
        r.avg_cluster_size = r.findings_created / r.clusters_created

    issues = []
    if r.singleton_rate > 0.40:
        issues.append("FRAGMENTED")
        r.pipeline_warnings.append(
            f"CLUSTER_FRAGMENTATION: {r.singleton_rate:.0%} singleton clusters "
            f"({r.singleton_clusters}/{r.clusters_created}). "
            "Many findings are isolated instead of grouped."
        )
    if r.avg_cluster_size < 2.0:
        issues.append("SMALL_CLUSTERS")
        r.pipeline_warnings.append(
            f"CLUSTER_SMALL: Average cluster size {r.avg_cluster_size:.1f}. "
            "Clustering may be too fine-grained."
        )
    if r.mixed_category_clusters > 0:
        issues.append(f"MIXED_CATEGORIES({r.mixed_category_clusters})")

    if any(i in ("FRAGMENTED", "SMALL_CLUSTERS") for i in issues):
        r.cluster_verdict = VERDICT_NEEDS_REVIEW
    elif issues:
        r.cluster_verdict = VERDICT_HEALTHY_WITH_NOTES
    else:
        r.cluster_verdict = VERDICT_HEALTHY


def _diagnose_editorial(r: EvalReport) -> None:
    """Editorial quality: reduction ratio between consolidation and final."""
    before = r.themes_after_consolidation
    after = r.themes_final

    if before == 0:
        r.editorial_verdict = "NO_DATA"
        return

    r.editorial_reduction_pct = (1.0 - after / before) * 100.0

    if r.editorial_reduction_pct < 10.0:
        r.editorial_verdict = VERDICT_NEEDS_REVIEW
        r.pipeline_warnings.append(
            f"EDITORIAL_WEAK: Only {r.editorial_reduction_pct:.0f}% reduction "
            f"({before} -> {after}). Editorial pass is not filtering enough."
        )
    elif r.editorial_reduction_pct > 60.0:
        r.editorial_verdict = VERDICT_NEEDS_REVIEW
        r.pipeline_warnings.append(
            f"EDITORIAL_AGGRESSIVE: {r.editorial_reduction_pct:.0f}% reduction "
            f"({before} -> {after}). Important themes may be lost."
        )
    else:
        r.editorial_verdict = VERDICT_HEALTHY


def _diagnose_categories(r: EvalReport) -> None:
    """Category distribution — in-scope only. Out-of-scope already separated."""
    total = sum(r.category_distribution.values())
    if total == 0:
        return

    for cat, count in sorted(r.category_distribution.items(), key=lambda x: -x[1]):
        pct = count / total
        if pct > 0.50:
            r.category_imbalance.append(
                f"CATEGORY_IMBALANCE: '{cat}' has {pct:.0%} of in-scope findings "
                f"({count}/{total}). Possible extraction bias."
            )


def _generate_suggestions(r: EvalReport) -> None:
    """Generate calibration suggestions based on all diagnostics."""
    if r.screening_verdict == VERDICT_NEEDS_REVIEW and r.screening_ratio < 0.05:
        r.suggestions.append(
            "SCREENING: Lower screening aggressiveness. Broaden 'risk_candidate' criteria "
            "in the screening prompt, or reduce SCREENING_HIGH_REMOVAL_THRESHOLD in case_steps.py."
        )
    elif r.screening_verdict == VERDICT_HEALTHY_WITH_NOTES:
        r.suggestions.append(
            "SCREENING: Strengthen screening filter. Add more examples of 'irrelevant' "
            "content to the screening prompt, or raise SCREENING_LOW_REMOVAL_THRESHOLD."
        )

    if "FRAGMENTED" in r.cluster_verdict or "SMALL_CLUSTERS" in r.cluster_verdict:
        r.suggestions.append(
            "CLUSTERING: Reduce fragmentation. Instruct the LLM to merge more aggressively, "
            "or lower the target theme count in CLUSTERING_SYSTEM_PROMPT."
        )

    if r.editorial_verdict == VERDICT_NEEDS_REVIEW:
        if r.editorial_reduction_pct < 10.0:
            r.suggestions.append(
                "EDITORIAL: Strengthen editorial reduction. Decrease target theme count "
                "or add stricter selection criteria."
            )
        elif r.editorial_reduction_pct > 60.0:
            r.suggestions.append(
                "EDITORIAL: Relax editorial selection. Increase max theme count "
                "or broaden the definition of 'negotiation-relevant'."
            )

    if r.category_imbalance:
        r.suggestions.append(
            "EXTRACTION: Category imbalance detected. Review the extraction prompt "
            "to ensure balanced category coverage."
        )

    if r.findings_created == 0 and r.screening_risk_candidate > 0:
        r.suggestions.append(
            "EXTRACTION: Zero findings from risk_candidate sections. The extraction "
            "prompt may be too restrictive, or LLM calls are failing silently."
        )

    if r.themes_final == 0 and r.clusters_created > 0:
        r.suggestions.append(
            "EDITORIAL: Zero final themes despite existing clusters. Check "
            "editorial_output debug snapshot for rejection reasons."
        )

    if r.out_of_scope_distribution:
        oos_total = sum(r.out_of_scope_distribution.values())
        if oos_total > 0:
            r.suggestions.append(
                f"POLICY: {oos_total} finding(s) in out-of-scope categories "
                f"({', '.join(r.out_of_scope_distribution.keys())}) reached the theme layer. "
                "Consider strengthening policy suppression rules or extraction prompt filtering."
            )

    if r.consistency_issues:
        r.suggestions.append(
            "METRICS: Consistency issues detected (see CONSISTENCY CHECKS section). "
            "Investigate pipeline step ordering and data flow."
        )


def _compute_final_verdict(r: EvalReport) -> None:
    """Task 5: Compute overall verdict based on all diagnostics."""
    if r.consistency_issues:
        r.final_verdict = VERDICT_INCONSISTENT
        return

    # Collect all step verdicts
    verdicts = [r.screening_verdict, r.cluster_verdict, r.editorial_verdict]
    verdicts = [v for v in verdicts if v and v != "NO_DATA"]

    if any(v == VERDICT_NEEDS_REVIEW for v in verdicts):
        r.final_verdict = VERDICT_NEEDS_REVIEW
    elif r.pipeline_warnings or any(v == VERDICT_HEALTHY_WITH_NOTES for v in verdicts):
        r.final_verdict = VERDICT_HEALTHY_WITH_NOTES
    elif not verdicts:
        # No data at all
        r.final_verdict = VERDICT_NEEDS_REVIEW
    else:
        r.final_verdict = VERDICT_HEALTHY


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def print_report(r: EvalReport) -> None:
    """Print the full diagnostic report, grouped by pipeline layer."""

    _sep()
    _header("CASE REPORT")
    _kv("case_id", r.case_id)
    _kv("title", r.title)
    _kv("status", r.status)
    _kv("documents", r.documents)
    _kv("sections_total", r.sections_total)
    _kv("processing_time", f"{r.processing_time_seconds:.0f}s")
    _kv("llm_calls", r.llm_calls_total)

    # --- Policy layer ---
    print()
    _header("POLICY LAYER")
    _note("Deterministic rule engine. Classifies sections before any LLM call.")
    _kv("policy_reviewable", r.policy_reviewable)
    _kv("out_of_scope", r.policy_out_of_scope)
    _kv("positive_control_sections", r.policy_positive_control)
    _kv("context_only", r.policy_context_only)
    _kv("ignore", r.policy_ignore)
    if r.policy_no_routing > 0:
        _kv("no_routing (unexpected)", r.policy_no_routing)
    if r.policy_reviewable == 0 and r.sections_total > 0:
        _note("No sections marked reviewable. Policy may be blocking everything, "
              "or policy scan did not run.")

    # --- Screening layer ---
    print()
    _header("SCREENING LAYER")
    _note("LLM classifies policy-reviewable sections as risk_candidate / context / irrelevant.")
    if r.screening_input > 0:
        _kv("llm_screened", r.screening_input)
        _kv("risk_candidate", f"{r.screening_risk_candidate} ({_pct(r.screening_risk_candidate, r.screening_input)})")
        _kv("context", f"{r.screening_context} ({_pct(r.screening_context, r.screening_input)})")
        _kv("ignored", f"{r.screening_ignored} ({_pct(r.screening_ignored, r.screening_input)})")
        if r.screening_error > 0:
            _kv("error", r.screening_error)
        _kv("verdict", r.screening_verdict)
    else:
        print("  (no screening data)")

    # --- Extraction layer ---
    print()
    _header("EXTRACTION LAYER")
    _note("LLM extracts findings from risk_candidate sections.")
    _kv("sections_extracted", r.sections_extracted)
    _kv("findings_created", r.findings_created)
    _kv("positive_controls_found", r.positive_controls_found)

    # --- Cluster diagnostics ---
    print()
    _header("CLUSTER DIAGNOSTICS")
    _kv("clusters_created", r.clusters_created)
    _kv("singleton_clusters", r.singleton_clusters)
    _kv("singleton_rate", f"{r.singleton_rate:.0%}" if r.clusters_created > 0 else "n/a")
    _kv("mixed_category_clusters", r.mixed_category_clusters)
    _kv("avg_cluster_size", f"{r.avg_cluster_size:.1f}" if r.avg_cluster_size > 0 else "n/a")
    _kv("verdict", r.cluster_verdict)

    # --- Out-of-scope topics ---
    print()
    _header("OUT-OF-SCOPE TOPICS")
    _note("Categories excluded from InfoSec risk calibration (separate review stream).")
    if r.out_of_scope_distribution:
        for cat, count in sorted(r.out_of_scope_distribution.items(), key=lambda x: -x[1]):
            _kv(cat.lower(), f"{count} finding(s) in themes")
        _note("These findings reached the theme layer despite out-of-scope designation. "
              "Consider strengthening policy suppression if this is undesired.")
    elif r.policy_out_of_scope > 0:
        _kv("sections_suppressed_by_policy", r.policy_out_of_scope)
        _note("Policy engine correctly suppressed out-of-scope sections. No findings leaked.")
    else:
        print("  (no out-of-scope data)")

    # --- Editorial reduction ---
    print()
    _header("EDITORIAL REDUCTION")
    _kv("before_editorial", r.themes_after_consolidation)
    _kv("after_editorial", r.themes_final)
    _kv("reduction", f"{r.editorial_reduction_pct:.0f}%" if r.themes_after_consolidation > 0 else "n/a")
    _kv("verdict", r.editorial_verdict)

    # --- Category distribution (in-scope only) ---
    print()
    _header("FINDING CATEGORY DISTRIBUTION (in-scope)")
    total_cat = sum(r.category_distribution.values())
    if total_cat > 0:
        for cat, count in sorted(r.category_distribution.items(), key=lambda x: -x[1]):
            pct = count / total_cat * 100
            bar = "#" * max(1, int(pct / 2))
            print(f"  {cat:30s}  {count:4d}  ({pct:5.1f}%)  {bar}")
        if r.category_imbalance:
            print()
            for w in r.category_imbalance:
                print(f"  ! {w}")
    else:
        print("  (no in-scope category data)")

    # --- Final themes ---
    print()
    _header("FINAL THEMES")
    if r.final_themes:
        for t in r.final_themes:
            rank = t.get("rank", "?")
            title = t.get("title", "?")
            severity = t.get("severity", "?")
            evidence = t.get("evidence_count", 0)
            docs = t.get("source_document_count", 0)
            category = t.get("category", "?")
            editorial = t.get("editorial", {})

            print(f"\n  {rank}. {title}")
            print(f"     severity: {severity}")
            print(f"     category: {category}")
            print(f"     evidence: {evidence}")
            print(f"     documents: {docs}")
            if t.get("conflict_detected"):
                print("     CONFLICT DETECTED")
            if editorial.get("bieterfrage"):
                print(f"     bieterfrage: {editorial['bieterfrage'][:150]}")
            if editorial.get("verhandlungsargumente"):
                args_list = editorial["verhandlungsargumente"]
                print(f"     argumente: {', '.join(str(a)[:60] for a in args_list[:3])}")
    else:
        print("  (no final themes)")

    # --- Consistency checks ---
    if r.consistency_issues:
        print()
        _header(f"CONSISTENCY CHECKS ({len(r.consistency_issues)} issue(s))")
        for issue in r.consistency_issues:
            print(f"  !! {issue}")

    # --- Pipeline warnings ---
    if r.pipeline_warnings:
        print()
        _header(f"PIPELINE WARNINGS ({len(r.pipeline_warnings)})")
        for w in r.pipeline_warnings:
            print(f"  ! {w}")

    # --- Calibration suggestions ---
    print()
    _header("CALIBRATION SUGGESTIONS")
    if r.suggestions:
        for i, s in enumerate(r.suggestions, 1):
            print(f"  {i}. {s}")
    else:
        print("  Pipeline calibration appears healthy for this case.")

    # --- Final verdict ---
    print()
    _header("FINAL VERDICT")
    verdict_desc = {
        VERDICT_HEALTHY: "All metrics consistent, all step verdicts healthy.",
        VERDICT_HEALTHY_WITH_NOTES: "Metrics consistent, but minor warnings or notes present.",
        VERDICT_NEEDS_REVIEW: "One or more pipeline steps need calibration review.",
        VERDICT_INCONSISTENT: "Metric consistency checks failed. Investigate data flow before calibrating.",
    }
    print(f"  {r.final_verdict}")
    if r.final_verdict in verdict_desc:
        print(f"  {verdict_desc[r.final_verdict]}")

    _sep()


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_report(report: EvalReport, path: str) -> None:
    """Export the full report as JSON."""
    data = report.to_dict()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    print(f"Report exported to: {path}")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _sep():
    print("=" * 64)

def _header(title: str):
    print(title)
    print("-" * len(title))

def _note(text: str):
    print(f"  ({text})")

def _step(label: str):
    print(f"\n>> {label}")

def _kv(key: str, value):
    print(f"  {key:30s}: {value}")

def _pct(part: int, whole: int) -> str:
    if whole == 0:
        return "n/a"
    return f"{part / whole * 100:.1f}%"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate and calibrate the case pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/evaluate_case_pipeline.py --dir ./test_contracts
  python scripts/evaluate_case_pipeline.py --case-id abc123-...
  python scripts/evaluate_case_pipeline.py --dir ./contracts --export report.json
""",
    )
    parser.add_argument("--dir", default=None, help="Directory with PDF/DOCX files to upload")
    parser.add_argument("--case-id", default=None, help="Analyze existing case (skip upload/run)")
    parser.add_argument("--api-url", default="http://localhost:8000/api", help="API base URL")
    parser.add_argument("--token", default=None, help="Bearer token (or set EVAL_TOKEN env var)")
    parser.add_argument("--title", default="Evaluation Case", help="Case title for new cases")
    parser.add_argument("--timeout", type=int, default=600, help="Max wait time in seconds")
    parser.add_argument("--export", default=None, metavar="FILE", help="Export report as JSON")
    args = parser.parse_args()

    if not args.dir and not args.case_id:
        parser.error("Either --dir or --case-id is required.")

    api = APIClient(
        args.api_url,
        token=args.token or os.getenv("EVAL_TOKEN", ""),
    )

    if args.case_id:
        case_id = args.case_id
        print(f"Analyzing existing case: {case_id}")
    else:
        case_id = create_and_run_case(api, args.dir, args.title, args.timeout)

    print()
    _step("Collecting evaluation data")
    report = collect_report(api, case_id)

    _step("Running diagnostics")
    run_diagnostics(report)

    print()
    print_report(report)

    if args.export:
        print()
        export_report(report, args.export)


if __name__ == "__main__":
    main()
