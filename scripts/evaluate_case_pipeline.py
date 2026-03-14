#!/usr/bin/env python3
"""Evaluation script for the multi-document case pipeline.

Usage:
    python scripts/evaluate_case_pipeline.py [--dir /path/to/pdfs] [--api-url http://localhost:8000]

This script:
1. Creates an AnalysisCase
2. Uploads documents from a directory
3. Triggers the pipeline
4. Polls until completed
5. Prints metrics and final themes
"""

import argparse
import os
import sys
import time

import requests


def main():
    parser = argparse.ArgumentParser(description="Evaluate case pipeline")
    parser.add_argument("--dir", default="./test_contracts", help="Directory with PDF/DOCX files to upload")
    parser.add_argument("--api-url", default="http://localhost:8000/api", help="API base URL")
    parser.add_argument("--token", default=None, help="Bearer token for auth (or set EVAL_TOKEN env var)")
    parser.add_argument("--title", default="Evaluation Case", help="Case title")
    parser.add_argument("--timeout", type=int, default=600, help="Max wait time in seconds")
    args = parser.parse_args()

    api = args.api_url.rstrip("/")
    token = args.token or os.getenv("EVAL_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    doc_dir = args.dir
    if not os.path.isdir(doc_dir):
        print(f"ERROR: Directory '{doc_dir}' does not exist.")
        print("Create it and add PDF/DOCX files, or specify --dir.")
        sys.exit(1)

    files = [
        f for f in os.listdir(doc_dir)
        if f.lower().endswith((".pdf", ".docx", ".doc", ".txt"))
    ]
    if not files:
        print(f"ERROR: No PDF/DOCX/TXT files found in '{doc_dir}'.")
        sys.exit(1)

    print(f"Found {len(files)} document(s) in {doc_dir}")
    print("=" * 60)

    # 1. Create case
    print("1. Creating AnalysisCase...")
    resp = requests.post(
        f"{api}/cases",
        json={"title": args.title, "customer_name": "Evaluation"},
        headers=headers,
    )
    resp.raise_for_status()
    case = resp.json()
    case_id = case["id"]
    print(f"   Case created: {case_id}")

    # 2. Upload documents
    print(f"2. Uploading {len(files)} documents...")
    for filename in sorted(files):
        filepath = os.path.join(doc_dir, filename)
        with open(filepath, "rb") as f:
            resp = requests.post(
                f"{api}/cases/{case_id}/documents",
                files={"datei": (filename, f)},
                headers=headers,
            )
            resp.raise_for_status()
            doc = resp.json()
            print(f"   Uploaded: {filename} (id={doc['id'][:8]}...)")

    # 3. Start pipeline
    print("3. Starting pipeline...")
    resp = requests.post(f"{api}/cases/{case_id}/analyze", headers=headers)
    resp.raise_for_status()
    print("   Pipeline started.")

    # 4. Poll until completed
    print("4. Waiting for pipeline to complete...")
    start_time = time.time()
    last_status = ""
    while True:
        elapsed = time.time() - start_time
        if elapsed > args.timeout:
            print(f"   TIMEOUT after {args.timeout}s")
            sys.exit(1)

        resp = requests.get(f"{api}/cases/{case_id}", headers=headers)
        resp.raise_for_status()
        case = resp.json()
        status = case["status"]

        if status != last_status:
            print(f"   Status: {status} ({elapsed:.0f}s)")
            last_status = status

        if status in ("Completed", "Failed"):
            break

        time.sleep(5)

    elapsed = time.time() - start_time
    print(f"   Pipeline finished in {elapsed:.1f}s with status: {case['status']}")
    print()

    if case.get("failure_reason"):
        print(f"   FAILURE: {case['failure_reason']}")

    # 5. Print metrics
    print("=" * 60)
    print("PIPELINE METRICS")
    print("=" * 60)

    try:
        resp = requests.get(f"{api}/cases/{case_id}/metrics", headers=headers)
        resp.raise_for_status()
        metrics = resp.json()
        for key, value in metrics.items():
            if key != "case_id":
                print(f"  {key:35s}: {value}")
    except Exception as e:
        print(f"  (metrics not available: {e})")

    print()

    # 5b. Print summary
    print("=" * 60)
    print("CASE SUMMARY")
    print("=" * 60)

    try:
        resp = requests.get(f"{api}/cases/{case_id}/summary", headers=headers)
        resp.raise_for_status()
        summary = resp.json()
        print(f"  Documents:              {summary.get('documents', 0)}")
        print(f"  Sections total:         {summary.get('sections_total', 0)}")
        print(f"  Sections analyzed:      {summary.get('sections_analyzed', 0)}")
        print(f"  Findings:               {summary.get('findings', 0)}")
        print(f"  Themes:                 {summary.get('themes', 0)}")
        print(f"  Themes (final):         {summary.get('themes_final', 0)}")
        print(f"  Positive controls:      {summary.get('positive_controls', 0)}")
        print(f"  Processing time (s):    {summary.get('processing_time_seconds', 'n/a')}")
    except Exception as e:
        print(f"  (summary not available: {e})")

    print()

    # 5c. Pipeline warnings
    warnings = case.get("pipeline_warnings") or []
    if warnings:
        print("=" * 60)
        print(f"PIPELINE WARNINGS ({len(warnings)})")
        print("=" * 60)
        for w in warnings:
            print(f"  ⚠ {w}")
        print()

    # 6. Print final themes
    print("=" * 60)
    print("FINAL THEMES")
    print("=" * 60)

    try:
        resp = requests.get(
            f"{api}/cases/{case_id}/themes",
            params={"final_only": "true"},
            headers=headers,
        )
        resp.raise_for_status()
        themes_data = resp.json()

        for theme in themes_data.get("themes", []):
            rank = theme.get("final_rank", "?")
            title = theme.get("canonical_title", "Unbekannt")
            severity = theme.get("severity", "?")
            category = theme.get("category", "?")
            editorial = theme.get("final_editorial_json") or {}

            print(f"\n  #{rank} [{severity}] {title}")
            print(f"      Category: {category}")
            if editorial.get("editorial_summary"):
                print(f"      Summary: {editorial['editorial_summary'][:200]}")
            if editorial.get("bieterfrage"):
                print(f"      Bieterfrage: {editorial['bieterfrage'][:200]}")

            evidence = theme.get("evidence", [])
            if evidence:
                print(f"      Evidence ({len(evidence)}):")
                for ev in evidence[:3]:
                    role = ev.get("evidence_role", "?")
                    desc = ev.get("kurzbeschreibung", "?")
                    print(f"        [{role}] {desc[:100]}")

    except Exception as e:
        print(f"  (themes not available: {e})")

    print()
    print("=" * 60)
    print("Evaluation complete.")


if __name__ == "__main__":
    main()
