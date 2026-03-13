"""Expected-findings evaluation and miss-analysis for the demo contract.

Run after a complete pipeline execution against the seeded demo contract:

    pytest tests/test_discovery/test_erwartungspruefung.py -v -s

Requirements:
  - Backend running at BASE_URL (default http://localhost:8000/api)
  - Demo contract seeded and analysis completed

This prints a full German evaluation report + miss-analysis and asserts minimum recall.
"""

import os

import httpx
import pytest

from app.evaluation.evaluator import evaluiere
from app.evaluation.miss_analyse import analysiere_misses
from app.evaluation.erwartungen_demo import DEMO_ERWARTUNGEN

BASE_URL = os.getenv("BENCHMARK_BASE_URL", "http://localhost:8000/api")

# Minimum recall quote (gefunden=1.0, teilweise=0.5, nicht_gefunden=0.0)
# With 19 expected themes, 0.65 means roughly 12-13 fully found.
MIN_RECALL_QUOTE = 0.65

# Maximum allowed "nicht gefunden" themes
MAX_NICHT_GEFUNDEN = 5


# ── Helpers ───────────────────────────────────────────────────────────

def _get_latest_completed_analysis() -> dict:
    r = httpx.get(f"{BASE_URL}/vertraege/")
    r.raise_for_status()
    vertraege = r.json()
    assert vertraege, "Keine Verträge gefunden — bitte Demo-Vertrag anlegen."

    latest = None
    for v in vertraege:
        ar = httpx.get(f"{BASE_URL}/analysen/vertrag/{v['id']}")
        ar.raise_for_status()
        for a in ar.json():
            if a["status"] == "Abgeschlossen":
                if latest is None or a["gestartet_am"] > latest["gestartet_am"]:
                    latest = a
    assert latest, "Keine abgeschlossene Analyse gefunden — bitte Analyse durchführen."
    return latest


def _get_auswertung(analyse_id: str) -> dict:
    r = httpx.get(f"{BASE_URL}/analysen/{analyse_id}/auswertung")
    r.raise_for_status()
    return r.json()


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def analyse_data():
    """Load analysis data: findings + raw candidates."""
    analyse = _get_latest_completed_analysis()
    auswertung = _get_auswertung(analyse["id"])
    fundstellen = auswertung["fundstellen_detail"]

    # Extract raw candidates from pipeline_auswertung if available
    pipeline = auswertung.get("pipeline_auswertung") or {}
    roh_kandidaten = pipeline.get("roh_kandidaten")

    return {
        "analyse": analyse,
        "fundstellen": fundstellen,
        "roh_kandidaten": roh_kandidaten,
    }


@pytest.fixture(scope="module")
def evaluation(analyse_data):
    return evaluiere(analyse_data["fundstellen"])


@pytest.fixture(scope="module")
def miss_analysis(evaluation, analyse_data):
    return analysiere_misses(evaluation, analyse_data["roh_kandidaten"])


# ── Evaluation Tests ──────────────────────────────────────────────────

def test_print_full_report(evaluation):
    """Print the full evaluation report (always passes, for inspection)."""
    print()
    print(evaluation.drucke_bericht())


def test_minimum_recall_quote(evaluation):
    """Recall quote must meet minimum threshold."""
    assert evaluation.recall_quote >= MIN_RECALL_QUOTE, (
        f"Recall-Quote {evaluation.recall_quote:.1%} liegt unter "
        f"Minimum {MIN_RECALL_QUOTE:.1%}. "
        f"Gefunden: {evaluation.gefunden}, "
        f"Teilweise: {evaluation.teilweise}, "
        f"Nicht gefunden: {evaluation.nicht_gefunden}"
    )


def test_max_missed_themes(evaluation):
    """At most MAX_NICHT_GEFUNDEN themes may be completely missed."""
    missed = [m for m in evaluation.matches if m.status == "nicht gefunden"]
    missed_titles = [m.erwartung.titel for m in missed]
    assert len(missed) <= MAX_NICHT_GEFUNDEN, (
        f"{len(missed)} Themen nicht gefunden (max {MAX_NICHT_GEFUNDEN}): "
        f"{missed_titles}"
    )


def test_critical_themes_found(evaluation):
    """Certain high-impact themes must be at least teilweise gefunden."""
    critical_ids = {
        "E03_VERFUEGBARKEIT_9995",
        "E04_VERTRAGSSTRAFE_KUMULATIV",
        "E10_REGULATORIK_BLANKO",
        "E11_AUDIT_UEBERDEHNT",
        "E12_HAFTUNG_UNBESCHRAENKT",
        "E18_IP_UEBERTRAGUNG",
    }
    for m in evaluation.matches:
        if m.erwartung.id in critical_ids:
            assert m.status != "nicht gefunden", (
                f"Kritisches Thema '{m.erwartung.titel}' ({m.erwartung.id}) "
                f"wurde nicht gefunden — das deutet auf einen schweren Recall-Fehler hin."
            )


# ── Miss-Analysis Tests ──────────────────────────────────────────────

def test_print_miss_analysis(miss_analysis):
    """Print the full miss-analysis report (always passes, for inspection)."""
    print()
    print(miss_analysis.drucke_bericht())


def test_miss_analysis_has_entries(miss_analysis, evaluation):
    """Miss analysis should have an entry for every non-gefunden theme."""
    expected_count = evaluation.teilweise + evaluation.nicht_gefunden
    assert len(miss_analysis.eintraege) == expected_count, (
        f"Miss-Analyse hat {len(miss_analysis.eintraege)} Einträge, "
        f"erwartet {expected_count} (teilweise + nicht gefunden)"
    )


def test_all_entries_have_cause(miss_analysis):
    """Every miss-analysis entry must have a classified root cause."""
    valid_causes = {
        "NICHT_ENTDECKT",
        "NUR_SCHWACH_ENTDECKT",
        "IN_KONSOLIDIERUNG_VERLOREN",
        "ZU_UNSPEZIFISCH_FORMULIERT",
        "KATEGORIE_UNPASSEND",
        "PASS_PROMPT_SCHWACH",
    }
    for e in miss_analysis.eintraege:
        assert e.ursache in valid_causes, (
            f"Unbekannte Ursache '{e.ursache}' für {e.erwartung_id}"
        )
        assert e.empfehlung, (
            f"Fehlende Empfehlung für {e.erwartung_id}"
        )
