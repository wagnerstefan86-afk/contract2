#!/usr/bin/env python3
"""Evaluation and calibration script for the multi-document case pipeline.

Usage:
    python scripts/evaluate_case_pipeline.py --dir /path/to/contracts
    python scripts/evaluate_case_pipeline.py --dir ./test_contracts --export report.json
    python scripts/evaluate_case_pipeline.py --case-id <existing-uuid>  # analyze existing case

This script:
1. Creates an AnalysisCase and uploads documents (or uses existing case)
2. Runs the pipeline and polls until completion
3. Collects metrics, themes, and debug snapshots
4. Runs quality diagnostics (screening, clustering, editorial, policy, categories)
5. Generates calibration suggestions
6. Prints a full diagnostic report
7. Optionally exports to JSON
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


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EvalReport:
    """Full evaluation report — all diagnostics collected here."""
    case_id: str = ""
    title: str = ""
    status: str = ""
    failure_reason: str | None = None

    # Case overview
    documents: int = 0
    sections_total: int = 0
    sections_screened: int = 0
    sections_analyzed: int = 0
    sections_ignored: int = 0
    sections_context: int = 0
    findings: int = 0
    clusters: int = 0
    themes_consolidated: int = 0
    themes_final: int = 0
    positive_controls: int = 0
    processing_time_seconds: float = 0.0
    llm_calls_total: int = 0

    # Screening diagnostics
    screening_ratio: float = 0.0
    screening_verdict: str = ""

    # Cluster diagnostics
    singleton_clusters: int = 0
    mixed_category_clusters: int = 0
    avg_cluster_size: float = 0.0
    singleton_rate: float = 0.0
    cluster_verdict: str = ""
    cluster_details: list[dict] = field(default_factory=list)

    # Editorial diagnostics
    editorial_reduction_pct: float = 0.0
    editorial_verdict: str = ""

    # Category distribution
    category_distribution: dict[str, int] = field(default_factory=dict)
    category_imbalance: list[str] = field(default_factory=list)

    # Policy summary
    policy_review_sections: int = 0
    policy_positive_controls: int = 0
    policy_out_of_scope: int = 0

    # Final themes detail
    final_themes: list[dict] = field(default_factory=list)

    # Pipeline warnings
    pipeline_warnings: list[str] = field(default_factory=list)

    # Calibration suggestions
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "status": self.status,
            "failure_reason": self.failure_reason,
            "metrics": {
                "documents": self.documents,
                "sections_total": self.sections_total,
                "sections_screened": self.sections_screened,
                "sections_analyzed": self.sections_analyzed,
                "sections_ignored": self.sections_ignored,
                "sections_context": self.sections_context,
                "findings": self.findings,
                "clusters": self.clusters,
                "themes_consolidated": self.themes_consolidated,
                "themes_final": self.themes_final,
                "positive_controls": self.positive_controls,
                "processing_time_seconds": self.processing_time_seconds,
                "llm_calls_total": self.llm_calls_total,
            },
            "diagnostics": {
                "screening": {
                    "ratio": self.screening_ratio,
                    "verdict": self.screening_verdict,
                },
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
                "categories": {
                    "distribution": self.category_distribution,
                    "imbalance_warnings": self.category_imbalance,
                },
                "policy": {
                    "review_sections": self.policy_review_sections,
                    "positive_controls": self.policy_positive_controls,
                    "out_of_scope": self.policy_out_of_scope,
                },
            },
            "themes": self.final_themes,
            "pipeline_warnings": self.pipeline_warnings,
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

    # Create case
    _step("Creating AnalysisCase")
    case = api.post("/cases", {"title": title, "customer_name": "Evaluation"})
    case_id = case["id"]
    print(f"   Case created: {case_id}")

    # Upload documents
    _step(f"Uploading {len(files)} documents")
    for filename in files:
        filepath = os.path.join(doc_dir, filename)
        with open(filepath, "rb") as f:
            doc = api.post(
                f"/cases/{case_id}/documents",
                files={"datei": (filename, f)},
            )
            print(f"   {filename} -> {doc['id'][:8]}...")

    # Start pipeline
    _step("Starting pipeline")
    api.post(f"/cases/{case_id}/analyze")
    print("   Pipeline started.")

    # Poll
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
    report = EvalReport(case_id=case_id)

    # Case detail
    case = api.get(f"/cases/{case_id}")
    report.title = case.get("title", "")
    report.status = case.get("status", "")
    report.failure_reason = case.get("failure_reason")
    report.pipeline_warnings = case.get("pipeline_warnings") or []
    report.documents = case.get("total_documents", 0)

    # Metrics
    try:
        m = api.get(f"/cases/{case_id}/metrics")
        report.sections_total = m.get("sections_total", 0)
        report.sections_screened = m.get("sections_screened", 0)
        report.sections_analyzed = m.get("sections_analyzed", 0)
        report.sections_ignored = m.get("sections_ignored", 0)
        report.sections_context = m.get("sections_context", 0)
        report.findings = m.get("findings_created", 0)
        report.positive_controls = m.get("positive_controls_found", 0)
        report.clusters = m.get("clusters_created", 0)
        report.themes_consolidated = m.get("themes_after_consolidation", 0)
        report.themes_final = m.get("themes_final", 0)
        report.processing_time_seconds = m.get("processing_time_seconds", 0.0)
        report.llm_calls_total = m.get("llm_calls_total", 0)
    except Exception as e:
        print(f"   (metrics unavailable: {e})")

    # Summary (fallback for any missing metrics)
    try:
        s = api.get(f"/cases/{case_id}/summary")
        if report.documents == 0:
            report.documents = s.get("documents", 0)
        if report.sections_total == 0:
            report.sections_total = s.get("sections_total", 0)
        if report.sections_analyzed == 0:
            report.sections_analyzed = s.get("sections_analyzed", 0)
        report.positive_controls = max(report.positive_controls, s.get("positive_controls", 0))
    except Exception:
        pass

    # Themes (all, not just final)
    try:
        themes_all = api.get(f"/cases/{case_id}/themes")
        all_themes = themes_all.get("themes", [])

        for t in all_themes:
            if t.get("final_selected"):
                evidence = t.get("evidence", [])
                # Collect unique document evidence (via kategorie as proxy)
                doc_sources = set()
                for ev in evidence:
                    if ev.get("kategorie"):
                        doc_sources.add(ev["kategorie"])

                report.final_themes.append({
                    "rank": t.get("final_rank"),
                    "title": t.get("canonical_title", "?"),
                    "category": t.get("category", "?"),
                    "severity": t.get("severity", "?"),
                    "evidence_count": len(evidence),
                    "source_finding_count": t.get("source_finding_count", 0),
                    "source_document_count": t.get("source_document_count", 0),
                    "conflict_detected": t.get("conflict_detected", False),
                    "editorial": t.get("final_editorial_json") or {},
                })

            # Category distribution from all themes (Task 5)
            cat = t.get("category", "OTHER")
            finding_count = t.get("source_finding_count", 0)
            report.category_distribution[cat] = report.category_distribution.get(cat, 0) + finding_count

        report.final_themes.sort(key=lambda x: x.get("rank") or 999)
    except Exception as e:
        print(f"   (themes unavailable: {e})")

    # Debug snapshots — cluster diagnostics (Task 3)
    try:
        snapshots = api.get(f"/cases/{case_id}/debug-snapshots")
        for snap in snapshots:
            stage = snap.get("stage", "")
            data = snap.get("data_json") or {}

            if stage == "cluster_output":
                diagnostics = data.get("diagnostics", [])
                report.cluster_details = diagnostics
                for d in diagnostics:
                    if d.get("is_singleton"):
                        report.singleton_clusters += 1
                    if d.get("is_mixed_category"):
                        report.mixed_category_clusters += 1

    except Exception as e:
        print(f"   (debug snapshots unavailable: {e})")

    # Policy routing — from sections API
    try:
        sections = api.get(f"/cases/{case_id}/sections")
        for sec in sections:
            routing = sec.get("routing", "")
            if routing == "REVIEWABLE":
                report.policy_review_sections += 1
            elif routing == "OUT_OF_SCOPE":
                report.policy_out_of_scope += 1
            elif routing == "POSITIVE_CONTROL":
                report.policy_positive_controls += 1
    except Exception as e:
        print(f"   (sections unavailable: {e})")

    return report


# ---------------------------------------------------------------------------
# Diagnostics (Tasks 2-8)
# ---------------------------------------------------------------------------

def run_diagnostics(report: EvalReport) -> None:
    """Run all quality analyses and populate verdicts + suggestions."""

    # Task 2 — Screening quality
    _diagnose_screening(report)

    # Task 3 — Cluster quality
    _diagnose_clustering(report)

    # Task 4 — Editorial quality
    _diagnose_editorial(report)

    # Task 5 — Category distribution
    _diagnose_categories(report)

    # Task 8 — Calibration suggestions
    _generate_suggestions(report)


def _diagnose_screening(report: EvalReport) -> None:
    """Task 2: Screening quality analysis."""
    if report.sections_total == 0:
        report.screening_verdict = "NO_DATA"
        return

    report.screening_ratio = report.sections_analyzed / report.sections_total

    if report.screening_ratio < 0.05:
        report.screening_verdict = "OVER_AGGRESSIVE"
        report.pipeline_warnings.append(
            f"SCREENING_OVER_AGGRESSIVE: Only {report.screening_ratio:.1%} of sections passed screening "
            f"({report.sections_analyzed}/{report.sections_total}). "
            "Risk of missing important clauses."
        )
    elif report.screening_ratio > 0.40:
        report.screening_verdict = "WEAK"
        report.pipeline_warnings.append(
            f"SCREENING_WEAK: {report.screening_ratio:.1%} of sections passed screening "
            f"({report.sections_analyzed}/{report.sections_total}). "
            "Screening provides little reduction — high LLM cost in extraction."
        )
    else:
        report.screening_verdict = "OK"


def _diagnose_clustering(report: EvalReport) -> None:
    """Task 3: Cluster quality analysis from debug snapshots."""
    if report.clusters == 0:
        report.cluster_verdict = "NO_DATA"
        return

    report.singleton_rate = report.singleton_clusters / report.clusters if report.clusters > 0 else 0.0

    if report.cluster_details:
        sizes = [d.get("cluster_size", 1) for d in report.cluster_details]
        report.avg_cluster_size = sum(sizes) / len(sizes) if sizes else 0.0
    elif report.findings > 0 and report.clusters > 0:
        report.avg_cluster_size = report.findings / report.clusters

    verdicts = []
    if report.singleton_rate > 0.40:
        verdicts.append("FRAGMENTED")
        report.pipeline_warnings.append(
            f"CLUSTER_FRAGMENTATION: {report.singleton_rate:.0%} singleton clusters "
            f"({report.singleton_clusters}/{report.clusters}). "
            "Many findings are isolated instead of grouped."
        )
    if report.avg_cluster_size < 2.0:
        verdicts.append("SMALL_CLUSTERS")
        report.pipeline_warnings.append(
            f"CLUSTER_SMALL: Average cluster size {report.avg_cluster_size:.1f}. "
            "Clustering may be too fine-grained."
        )
    if report.mixed_category_clusters > 0:
        verdicts.append(f"MIXED_CATEGORIES({report.mixed_category_clusters})")

    report.cluster_verdict = ", ".join(verdicts) if verdicts else "OK"


def _diagnose_editorial(report: EvalReport) -> None:
    """Task 4: Editorial quality analysis."""
    before = report.themes_consolidated
    after = report.themes_final

    if before == 0:
        report.editorial_verdict = "NO_DATA"
        return

    report.editorial_reduction_pct = (1.0 - after / before) * 100.0 if before > 0 else 0.0

    if report.editorial_reduction_pct < 10.0:
        report.editorial_verdict = "TOO_WEAK"
        report.pipeline_warnings.append(
            f"EDITORIAL_WEAK: Only {report.editorial_reduction_pct:.0f}% reduction "
            f"({before} -> {after}). Editorial pass is not filtering enough."
        )
    elif report.editorial_reduction_pct > 60.0:
        report.editorial_verdict = "TOO_AGGRESSIVE"
        report.pipeline_warnings.append(
            f"EDITORIAL_AGGRESSIVE: {report.editorial_reduction_pct:.0f}% reduction "
            f"({before} -> {after}). Important themes may be lost."
        )
    else:
        report.editorial_verdict = "OK"


def _diagnose_categories(report: EvalReport) -> None:
    """Task 5: Finding category distribution analysis."""
    total = sum(report.category_distribution.values())
    if total == 0:
        return

    for cat, count in sorted(report.category_distribution.items(), key=lambda x: -x[1]):
        pct = count / total
        if pct > 0.50:
            report.category_imbalance.append(
                f"CATEGORY_IMBALANCE: '{cat}' has {pct:.0%} of findings ({count}/{total}). "
                "Possible extraction bias toward this category."
            )


def _generate_suggestions(report: EvalReport) -> None:
    """Task 8: Generate calibration suggestions based on diagnostics."""
    # Screening
    if report.screening_verdict == "OVER_AGGRESSIVE":
        report.suggestions.append(
            "SCREENING: Lower screening aggressiveness. Consider broadening "
            "'risk_candidate' criteria in the screening prompt, or reduce "
            "SCREENING_HIGH_REMOVAL_THRESHOLD in case_steps.py (currently 0.90)."
        )
    elif report.screening_verdict == "WEAK":
        report.suggestions.append(
            "SCREENING: Strengthen screening filter. Add more examples of "
            "'irrelevant' content to the screening prompt, or raise "
            "SCREENING_LOW_REMOVAL_THRESHOLD in case_steps.py (currently 0.30)."
        )

    # Clustering
    if "FRAGMENTED" in report.cluster_verdict:
        report.suggestions.append(
            "CLUSTERING: Reduce cluster fragmentation. Consider instructing the LLM "
            "to merge more aggressively, or lower the target theme count "
            "in CLUSTERING_SYSTEM_PROMPT (currently 5-15)."
        )
    if "SMALL_CLUSTERS" in report.cluster_verdict:
        report.suggestions.append(
            "CLUSTERING: Increase cluster merging. The average cluster size is very low. "
            "Review the clustering prompt to encourage broader grouping."
        )

    # Editorial
    if report.editorial_verdict == "TOO_WEAK":
        report.suggestions.append(
            "EDITORIAL: Strengthen editorial reduction. Decrease the target theme count "
            "in EDITORIAL_SYSTEM_PROMPT, or add stricter selection criteria "
            "(e.g., 'only themes with negotiation leverage')."
        )
    elif report.editorial_verdict == "TOO_AGGRESSIVE":
        report.suggestions.append(
            "EDITORIAL: Relax editorial selection. Increase the max theme count "
            "or broaden the definition of 'negotiation-relevant' in the prompt."
        )

    # Category imbalance
    if report.category_imbalance:
        report.suggestions.append(
            "EXTRACTION: Category imbalance detected. Review the extraction prompt "
            "to ensure balanced category coverage. Check if certain contract sections "
            "dominate the input."
        )

    # General
    if report.findings == 0 and report.sections_analyzed > 0:
        report.suggestions.append(
            "EXTRACTION: Zero findings from analyzed sections. The extraction prompt "
            "may be too restrictive, or the LLM is failing silently."
        )

    if report.themes_final == 0 and report.clusters > 0:
        report.suggestions.append(
            "EDITORIAL: Zero final themes despite existing clusters. The editorial "
            "pass may have rejected everything. Check editorial_output debug snapshot."
        )


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------

def print_report(report: EvalReport) -> None:
    """Print the full diagnostic report to stdout."""

    _sep()
    _header("CASE REPORT")
    _kv("case_id", report.case_id)
    _kv("title", report.title)
    _kv("status", report.status)
    _kv("documents", report.documents)
    _kv("sections_total", report.sections_total)
    _kv("sections_llm_screened", report.sections_screened)
    _kv("sections_analyzed", report.sections_analyzed)
    _kv("findings", report.findings)
    _kv("clusters", report.clusters)
    _kv("themes_consolidated", report.themes_consolidated)
    _kv("themes_final", report.themes_final)
    _kv("positive_controls", report.positive_controls)
    _kv("processing_time", f"{report.processing_time_seconds:.0f}s")
    _kv("llm_calls_total", report.llm_calls_total)

    print()
    _header("SCREENING RATIO")
    if report.sections_total > 0:
        kept_pct = report.sections_analyzed / report.sections_total * 100
        ign_pct = report.sections_ignored / report.sections_total * 100 if report.sections_ignored else 0
        ctx_pct = report.sections_context / report.sections_total * 100 if report.sections_context else 0
        _kv("kept (risk_candidate)", f"{report.sections_analyzed} ({kept_pct:.1f}%)")
        _kv("ignored", f"{report.sections_ignored} ({ign_pct:.1f}%)")
        _kv("context", f"{report.sections_context} ({ctx_pct:.1f}%)")
        _kv("verdict", report.screening_verdict)
    else:
        print("  (no screening data)")

    print()
    _header("CLUSTER DIAGNOSTICS")
    _kv("total_clusters", report.clusters)
    _kv("singleton_clusters", report.singleton_clusters)
    _kv("singleton_rate", f"{report.singleton_rate:.0%}")
    _kv("mixed_category_clusters", report.mixed_category_clusters)
    _kv("avg_cluster_size", f"{report.avg_cluster_size:.1f}")
    _kv("verdict", report.cluster_verdict)

    print()
    _header("EDITORIAL REDUCTION")
    _kv("before_editorial", report.themes_consolidated)
    _kv("after_editorial", report.themes_final)
    _kv("reduction", f"{report.editorial_reduction_pct:.0f}%")
    _kv("verdict", report.editorial_verdict)

    print()
    _header("FINDING CATEGORY DISTRIBUTION")
    total_cat = sum(report.category_distribution.values())
    if total_cat > 0:
        for cat, count in sorted(report.category_distribution.items(), key=lambda x: -x[1]):
            pct = count / total_cat * 100
            bar = "#" * int(pct / 2)
            print(f"  {cat:30s}  {count:4d}  ({pct:5.1f}%)  {bar}")
    else:
        print("  (no category data)")
    if report.category_imbalance:
        print()
        for w in report.category_imbalance:
            print(f"  ! {w}")

    print()
    _header("POLICY ROUTING")
    _kv("review_sections", report.policy_review_sections)
    _kv("positive_controls", report.policy_positive_controls)
    _kv("out_of_scope", report.policy_out_of_scope)

    print()
    _header("FINAL THEMES")
    if report.final_themes:
        for i, t in enumerate(report.final_themes, 1):
            rank = t.get("rank", i)
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
                print(f"     CONFLICT DETECTED")
            if editorial.get("bieterfrage"):
                print(f"     bieterfrage: {editorial['bieterfrage'][:150]}")
            if editorial.get("verhandlungsargumente"):
                args = editorial["verhandlungsargumente"]
                print(f"     argumente: {', '.join(str(a)[:60] for a in args[:3])}")
    else:
        print("  (no final themes)")

    # Pipeline warnings
    if report.pipeline_warnings:
        print()
        _header(f"PIPELINE WARNINGS ({len(report.pipeline_warnings)})")
        for w in report.pipeline_warnings:
            print(f"  ! {w}")

    # Calibration suggestions
    if report.suggestions:
        print()
        _header("CALIBRATION SUGGESTIONS")
        for i, s in enumerate(report.suggestions, 1):
            print(f"  {i}. {s}")
    else:
        print()
        _header("CALIBRATION SUGGESTIONS")
        print("  No issues detected. Pipeline calibration appears healthy.")

    _sep()
    print("Evaluation complete.")


# ---------------------------------------------------------------------------
# JSON export (Task 9)
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

def _step(label: str):
    print(f"\n>> {label}")

def _kv(key: str, value):
    print(f"  {key:30s}: {value}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Evaluate and calibrate the case pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline on contract files:
  python scripts/evaluate_case_pipeline.py --dir ./test_contracts

  # Analyze an existing completed case:
  python scripts/evaluate_case_pipeline.py --case-id abc123-...

  # Run and export JSON report:
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
        parser.error("Either --dir (to create a new case) or --case-id (to analyze existing) is required.")

    api = APIClient(
        args.api_url,
        token=args.token or os.getenv("EVAL_TOKEN", ""),
    )

    # Run or reuse case
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
