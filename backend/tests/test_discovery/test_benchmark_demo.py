"""Benchmark / regression guard for the demo contract.

Run manually after a full pipeline run against the seeded demo contract:

    pytest tests/test_discovery/test_benchmark_demo.py -v

The test reads the auswertung endpoint for the *most recent* analysis and
asserts minimum thresholds that should never regress.

Requirements:
  - The backend must be running and reachable at BASE_URL (default localhost:8000)
  - A demo contract must have been analysed (POST /api/demo/vertrag-anlegen, then start analysis)

This is NOT a unit test — it's an integration smoke / regression check.
"""

import os
import httpx
import pytest

BASE_URL = os.getenv("BENCHMARK_BASE_URL", "http://localhost:8000/api")

# ── Minimum thresholds ────────────────────────────────────────────────
# The demo contract has ~13 sections with intentionally problematic clauses.
# A well-functioning pipeline should find at least this many issues.
MIN_FINDINGS_TOTAL = 12

# Categories we expect at least one finding in.
EXPECTED_CATEGORIES = {
    "Haftung",
    "SLA / Verfügbarkeit",
    "Informationssicherheit",
    "Compliance / Regulatorik",
    "Kündigung / Laufzeit",
}

# We expect findings from at least 2 different passes.
MIN_DISTINCT_SOURCES = 2

# ── Helpers ───────────────────────────────────────────────────────────

def _get_latest_analysis() -> dict:
    """Find the most recent analysis by listing all contracts."""
    r = httpx.get(f"{BASE_URL}/vertraege/")
    r.raise_for_status()
    vertraege = r.json()
    assert vertraege, "No contracts found — seed the demo contract first."

    # Find latest analysis across all contracts
    latest = None
    for v in vertraege:
        ar = httpx.get(f"{BASE_URL}/analysen/vertrag/{v['id']}")
        ar.raise_for_status()
        for a in ar.json():
            if a["status"] == "Abgeschlossen":
                if latest is None or a["gestartet_am"] > latest["gestartet_am"]:
                    latest = a
    assert latest, "No completed analysis found — run an analysis first."
    return latest


def _get_auswertung(analyse_id: str) -> dict:
    r = httpx.get(f"{BASE_URL}/analysen/{analyse_id}/auswertung")
    r.raise_for_status()
    return r.json()


# ── Tests ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def auswertung():
    analyse = _get_latest_analysis()
    return _get_auswertung(analyse["id"])


def test_minimum_finding_count(auswertung):
    """Pipeline must produce at least MIN_FINDINGS_TOTAL findings."""
    total = auswertung["fundstellen_gesamt"]
    assert total >= MIN_FINDINGS_TOTAL, (
        f"Only {total} findings — expected at least {MIN_FINDINGS_TOTAL}. "
        f"Recall may have regressed."
    )


def test_expected_category_coverage(auswertung):
    """At least one finding must exist in each expected category."""
    found_cats = set(auswertung["kategorien_final"].keys())
    missing = EXPECTED_CATEGORIES - found_cats
    assert not missing, (
        f"Missing expected categories: {missing}. "
        f"Found categories: {found_cats}"
    )


def test_multi_pass_coverage(auswertung):
    """Findings should originate from multiple passes."""
    sources = set(auswertung["quellen_verteilung_final"].keys())
    assert len(sources) >= MIN_DISTINCT_SOURCES, (
        f"Only {len(sources)} distinct source(s): {sources}. "
        f"Expected at least {MIN_DISTINCT_SOURCES} passes contributing findings."
    )


def test_no_empty_descriptions(auswertung):
    """Every finding must have a non-empty kurzbeschreibung."""
    for f in auswertung["fundstellen_detail"]:
        assert f["kurzbeschreibung"].strip(), (
            f"Finding {f['id']} has empty kurzbeschreibung."
        )


def test_risk_levels_present(auswertung):
    """At least 'Hoch' and one other risk level should be present."""
    levels = set(auswertung["risikostufen_final"].keys())
    assert "Hoch" in levels, (
        f"No 'Hoch' risk findings — the demo contract has clear high-risk clauses. "
        f"Found levels: {levels}"
    )
    assert len(levels) >= 2, (
        f"Only one risk level ({levels}) — expected variety across demo contract."
    )
