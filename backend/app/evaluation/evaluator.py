"""Lightweight expected-findings evaluator.

Compares actual pipeline findings against the curated expectation set using
pragmatic keyword/category/text matching — no ML, no embeddings, just
practical string overlap.

Matching logic per expected theme:
  1. Collect all actual findings whose category overlaps with expected categories.
  2. For each candidate, compute a keyword hit score against the expected keywords.
  3. Also check title/description similarity against the finding's kurzbeschreibung,
     erklaerung, and textstelle.
  4. Classify the best match:
       - "gefunden"           if keyword score ≥ 0.4 OR title similarity ≥ 0.5
       - "teilweise gefunden" if keyword score ≥ 0.2 OR title similarity ≥ 0.3
       - "nicht gefunden"     otherwise

Risk level check:
  If a match is found but its risk level is below min_risiko, a note is added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.evaluation.erwartungen_demo import ErwarteteFundstelle, DEMO_ERWARTUNGEN

# Risk level ordering (higher = more severe)
RISIKO_RANG = {"Hinweis": 0, "Niedrig": 1, "Mittel": 2, "Hoch": 3}


@dataclass
class MatchErgebnis:
    """Result of matching one expected finding against actual findings."""
    erwartung: ErwarteteFundstelle
    status: str  # "gefunden" | "teilweise gefunden" | "nicht gefunden"
    beste_fundstelle_id: str | None = None
    beste_fundstelle_kurz: str | None = None
    keyword_score: float = 0.0
    titel_score: float = 0.0
    risiko_ok: bool = True
    risiko_hinweis: str = ""
    begruendung: str = ""


@dataclass
class EvaluationErgebnis:
    """Full evaluation result."""
    matches: list[MatchErgebnis] = field(default_factory=list)
    extra_fundstellen: list[dict] = field(default_factory=list)

    @property
    def gefunden(self) -> int:
        return sum(1 for m in self.matches if m.status == "gefunden")

    @property
    def teilweise(self) -> int:
        return sum(1 for m in self.matches if m.status == "teilweise gefunden")

    @property
    def nicht_gefunden(self) -> int:
        return sum(1 for m in self.matches if m.status == "nicht gefunden")

    @property
    def recall_quote(self) -> float:
        total = len(self.matches)
        if total == 0:
            return 0.0
        # "gefunden" = 1.0, "teilweise" = 0.5, "nicht gefunden" = 0.0
        score = self.gefunden + 0.5 * self.teilweise
        return round(score / total, 3)

    def to_dict(self) -> dict:
        """Serializable summary for API / JSON output."""
        return {
            "zusammenfassung": {
                "erwartete_themen": len(self.matches),
                "gefunden": self.gefunden,
                "teilweise_gefunden": self.teilweise,
                "nicht_gefunden": self.nicht_gefunden,
                "recall_quote": self.recall_quote,
                "extra_fundstellen": len(self.extra_fundstellen),
            },
            "themen": [
                {
                    "id": m.erwartung.id,
                    "titel": m.erwartung.titel,
                    "status": m.status,
                    "keyword_score": round(m.keyword_score, 3),
                    "titel_score": round(m.titel_score, 3),
                    "beste_fundstelle_id": m.beste_fundstelle_id,
                    "beste_fundstelle_kurz": m.beste_fundstelle_kurz,
                    "risiko_ok": m.risiko_ok,
                    "risiko_hinweis": m.risiko_hinweis,
                    "begruendung": m.begruendung,
                }
                for m in self.matches
            ],
            "extra_fundstellen": self.extra_fundstellen,
        }

    def drucke_bericht(self) -> str:
        """Human-readable German evaluation report."""
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append("  ERWARTUNGSPRÜFUNG — Demo-Vertrag")
        lines.append("=" * 72)
        lines.append("")

        # Summary
        total = len(self.matches)
        lines.append(f"Erwartete Themen:    {total}")
        lines.append(f"Gefunden:            {self.gefunden}")
        lines.append(f"Teilweise gefunden:  {self.teilweise}")
        lines.append(f"Nicht gefunden:      {self.nicht_gefunden}")
        lines.append(f"Recall-Quote:        {self.recall_quote:.1%}")
        lines.append(f"Extra Fundstellen:   {len(self.extra_fundstellen)}")
        lines.append("")

        # Per-theme table
        lines.append("-" * 72)
        lines.append(f"{'ID':<22} {'Status':<22} {'Titel'}")
        lines.append("-" * 72)
        for m in self.matches:
            status_marker = {
                "gefunden": "[OK]",
                "teilweise gefunden": "[~~]",
                "nicht gefunden": "[!!]",
            }.get(m.status, "[??]")
            lines.append(f"{m.erwartung.id:<22} {status_marker + ' ' + m.status:<22} {m.erwartung.titel}")
            if m.begruendung:
                lines.append(f"{'':>22}   → {m.begruendung}")
            if m.risiko_hinweis:
                lines.append(f"{'':>22}   ⚠ {m.risiko_hinweis}")
        lines.append("")

        # Missed themes
        missed = [m for m in self.matches if m.status == "nicht gefunden"]
        if missed:
            lines.append("-" * 72)
            lines.append("NICHT GEFUNDENE THEMEN:")
            lines.append("-" * 72)
            for m in missed:
                lines.append(f"  {m.erwartung.id}: {m.erwartung.titel}")
                lines.append(f"    Beschreibung: {m.erwartung.beschreibung[:120]}...")
                lines.append(f"    Schlüsselwörter: {', '.join(m.erwartung.schluesselwoerter[:6])}")
                lines.append("")

        # Extra findings
        if self.extra_fundstellen:
            lines.append("-" * 72)
            lines.append(f"EXTRA FUNDSTELLEN (nicht in Erwartungen, {len(self.extra_fundstellen)} Stück):")
            lines.append("-" * 72)
            for ef in self.extra_fundstellen:
                lines.append(f"  [{ef.get('risikostufe', '?')}] {ef.get('kurzbeschreibung', '?')}")
                lines.append(f"    Kategorie: {ef.get('kategorie', '?')} | Quelle: {ef.get('quelle_pass', '?')}")
            lines.append("")

        lines.append("=" * 72)
        return "\n".join(lines)


def evaluiere(
    fundstellen: list[dict],
    erwartungen: list[ErwarteteFundstelle] | None = None,
) -> EvaluationErgebnis:
    """Run the expected-findings evaluation.

    Args:
        fundstellen: list of finding dicts (as returned by the auswertung endpoint's
                     fundstellen_detail or the Fundstelle API).
                     Each dict should have at least: id, kurzbeschreibung, kategorie,
                     risikostufe, textstelle (or erklaerung), quelle_pass.
        erwartungen: optional override; defaults to DEMO_ERWARTUNGEN.

    Returns:
        EvaluationErgebnis with per-theme match results and unmatched extras.
    """
    if erwartungen is None:
        erwartungen = DEMO_ERWARTUNGEN

    ergebnis = EvaluationErgebnis()
    matched_fundstellen_ids: set[str] = set()

    for erw in erwartungen:
        best = _finde_besten_match(erw, fundstellen)
        ergebnis.matches.append(best)
        if best.beste_fundstelle_id:
            matched_fundstellen_ids.add(best.beste_fundstelle_id)

    # Collect unmatched extra findings
    for f in fundstellen:
        fid = str(f.get("id", ""))
        if fid not in matched_fundstellen_ids:
            ergebnis.extra_fundstellen.append({
                "id": fid,
                "kurzbeschreibung": f.get("kurzbeschreibung", ""),
                "kategorie": f.get("kategorie", ""),
                "risikostufe": f.get("risikostufe", ""),
                "quelle_pass": f.get("quelle_pass", ""),
            })

    return ergebnis


def _finde_besten_match(
    erw: ErwarteteFundstelle,
    fundstellen: list[dict],
) -> MatchErgebnis:
    """Find the best matching actual finding for one expected theme."""

    best_match = MatchErgebnis(erwartung=erw, status="nicht gefunden")
    best_combined = 0.0

    for f in fundstellen:
        # Category filter: at least one overlap (normalized)
        f_kat = _norm(f.get("kategorie", ""))
        kat_match = any(_norm(k) in f_kat or f_kat in _norm(k) for k in erw.kategorien)

        # Build the text corpus from all available fields
        corpus = " ".join([
            f.get("kurzbeschreibung", ""),
            f.get("erklaerung", "") or "",
            f.get("textstelle", "") or "",
            f.get("empfehlung", "") or "",
        ]).lower()

        # Keyword hit score
        kw_score = _keyword_score(erw.schluesselwoerter, corpus)

        # Title similarity
        titel_score = max(
            _similarity(erw.titel, f.get("kurzbeschreibung", "")),
            _similarity(erw.beschreibung[:80], f.get("kurzbeschreibung", "")),
        )

        # Combined score — category match gives a bonus
        combined = kw_score * 0.7 + titel_score * 0.3
        if kat_match:
            combined += 0.1  # Bonus for matching category

        if combined > best_combined:
            best_combined = combined

            # Determine status
            if kw_score >= 0.4 or titel_score >= 0.5 or (kat_match and kw_score >= 0.3):
                status = "gefunden"
            elif kw_score >= 0.2 or titel_score >= 0.3 or (kat_match and kw_score >= 0.15):
                status = "teilweise gefunden"
            else:
                status = "nicht gefunden"

            # Risk level check
            risiko_ok = True
            risiko_hinweis = ""
            f_risiko = f.get("risikostufe", "Hinweis")
            min_rang = RISIKO_RANG.get(erw.min_risiko, 0)
            actual_rang = RISIKO_RANG.get(f_risiko, 0)
            if status != "nicht gefunden" and actual_rang < min_rang:
                risiko_ok = False
                risiko_hinweis = (
                    f"Risikostufe '{f_risiko}' unter Erwartung '{erw.min_risiko}'"
                )

            # Build explanation
            parts = []
            if kw_score > 0:
                parts.append(f"KW={kw_score:.2f}")
            if titel_score > 0:
                parts.append(f"Titel={titel_score:.2f}")
            if kat_match:
                parts.append("Kat=✓")
            begruendung = f"Match: {f.get('kurzbeschreibung', '?')[:60]} ({', '.join(parts)})"

            best_match = MatchErgebnis(
                erwartung=erw,
                status=status,
                beste_fundstelle_id=str(f.get("id", "")),
                beste_fundstelle_kurz=f.get("kurzbeschreibung", ""),
                keyword_score=kw_score,
                titel_score=titel_score,
                risiko_ok=risiko_ok,
                risiko_hinweis=risiko_hinweis,
                begruendung=begruendung if status != "nicht gefunden" else "",
            )

    return best_match


def _keyword_score(keywords: list[str], corpus: str) -> float:
    """Fraction of expected keywords found in the corpus text."""
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw.lower() in corpus)
    return hits / len(keywords)


def _similarity(a: str, b: str) -> float:
    """SequenceMatcher ratio between two strings (lowercased)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _norm(s: str) -> str:
    """Normalize a string for loose comparison: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", s.lower().strip())
