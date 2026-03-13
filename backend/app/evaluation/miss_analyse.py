"""Miss-analysis: diagnose WHY expected themes were missed or only partially found.

For each expected theme with status "nicht gefunden" or "teilweise gefunden",
inspects the raw pass output (pre-consolidation) to classify the root cause.

Root cause categories:
  NICHT_ENTDECKT            — no raw candidate in any pass matched this theme
  NUR_SCHWACH_ENTDECKT      — raw candidates exist but with very low match quality
  IN_KONSOLIDIERUNG_VERLOREN — a good raw candidate existed but was merged/dropped
  ZU_UNSPEZIFISCH_FORMULIERT — final finding exists but description is too generic to match
  KATEGORIE_UNPASSEND       — finding exists but was assigned an unexpected category
  PASS_PROMPT_SCHWACH       — theme falls into a pass's domain but that pass produced nothing
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.evaluation.erwartungen_demo import ErwarteteFundstelle
from app.evaluation.evaluator import (
    MatchErgebnis,
    EvaluationErgebnis,
    _keyword_score,
    _similarity,
    _norm,
)


# Which passes are expected to cover which theme categories
PASS_KATEGORIE_ZUORDNUNG: dict[str, list[str]] = {
    "Pass 1: Breite Ersterfassung": [
        # Pass 1 should catch everything broadly
        "Haftung & Gewährleistung", "Verfügbarkeit & Betrieb",
        "SLA / Verfügbarkeit", "Vertragsmanagement",
        "Leistungsumfang & Abgrenzung", "Informationssicherheit",
        "Compliance & Regulatorik", "Audit & Berichtswesen",
        "Personalanforderungen", "Geistiges Eigentum",
        "Kündigung / Laufzeit",
    ],
    "Pass 2: Informationssicherheit": [
        "Informationssicherheit",
    ],
    "Pass 2: BCM / Betrieb / Resilienz": [
        "Verfügbarkeit & Betrieb", "SLA / Verfügbarkeit",
    ],
    "Pass 2: Compliance / Regulatorik": [
        "Compliance & Regulatorik",
    ],
    "Pass 2: Audit / Reporting / Nachweise": [
        "Audit & Berichtswesen",
    ],
    "Pass 2: Haftung / Zusicherung / Überdehnung": [
        "Haftung & Gewährleistung", "Geistiges Eigentum",
    ],
    "Pass 3: Implizite Pflichten": [
        "Implizite Pflichten", "Vertragsmanagement",
        "Leistungsumfang & Abgrenzung",
    ],
}


@dataclass
class RohKandidatMatch:
    """Best raw candidate match for one expected theme."""
    pass_name: str = ""
    kurzbeschreibung: str = ""
    kategorie: str = ""
    keyword_score: float = 0.0
    titel_score: float = 0.0
    combined: float = 0.0


@dataclass
class MissAnalyseEintrag:
    """Root cause analysis for one missed/partial theme."""
    erwartung_id: str
    erwartung_titel: str
    aktueller_status: str  # "nicht gefunden" | "teilweise gefunden"
    # Final match info (from evaluator)
    beste_finale_kurz: str = ""
    beste_finale_kw: float = 0.0
    beste_finale_titel: float = 0.0
    # Raw candidate analysis
    bester_roh_kandidat: RohKandidatMatch | None = None
    roh_kandidat_besser: bool = False  # raw was better than final
    # Root cause
    ursache: str = "NICHT_ENTDECKT"
    ursache_detail: str = ""
    empfehlung: str = ""
    relevante_passes: list[str] = field(default_factory=list)


@dataclass
class MissAnalyseErgebnis:
    """Full miss-analysis result."""
    eintraege: list[MissAnalyseEintrag] = field(default_factory=list)
    roh_kandidaten_verfuegbar: bool = False

    def to_dict(self) -> dict:
        return {
            "roh_kandidaten_verfuegbar": self.roh_kandidaten_verfuegbar,
            "anzahl_analysiert": len(self.eintraege),
            "ursachen_verteilung": _count_causes(self.eintraege),
            "eintraege": [
                {
                    "erwartung_id": e.erwartung_id,
                    "erwartung_titel": e.erwartung_titel,
                    "aktueller_status": e.aktueller_status,
                    "beste_finale_kurz": e.beste_finale_kurz,
                    "beste_finale_kw": round(e.beste_finale_kw, 3),
                    "beste_finale_titel": round(e.beste_finale_titel, 3),
                    "bester_roh_kandidat": {
                        "pass_name": e.bester_roh_kandidat.pass_name,
                        "kurzbeschreibung": e.bester_roh_kandidat.kurzbeschreibung,
                        "kategorie": e.bester_roh_kandidat.kategorie,
                        "keyword_score": round(e.bester_roh_kandidat.keyword_score, 3),
                        "titel_score": round(e.bester_roh_kandidat.titel_score, 3),
                    } if e.bester_roh_kandidat else None,
                    "roh_kandidat_besser": e.roh_kandidat_besser,
                    "ursache": e.ursache,
                    "ursache_detail": e.ursache_detail,
                    "empfehlung": e.empfehlung,
                    "relevante_passes": e.relevante_passes,
                }
                for e in self.eintraege
            ],
        }

    def drucke_bericht(self) -> str:
        lines: list[str] = []
        lines.append("=" * 78)
        lines.append("  MISS-ANALYSE — Warum wurden Themen nicht gefunden?")
        lines.append("=" * 78)
        lines.append("")

        if not self.roh_kandidaten_verfuegbar:
            lines.append("HINWEIS: Keine Rohkandidaten-Daten in der Auswertung vorhanden.")
            lines.append("Die Miss-Analyse basiert nur auf den finalen Fundstellen.")
            lines.append("Für volle Diagnose: Analyse erneut durchführen (Roh-Daten")
            lines.append("werden ab jetzt in der Auswertung gespeichert).")
            lines.append("")

        # Cause distribution
        causes = _count_causes(self.eintraege)
        lines.append(f"Analysierte Themen: {len(self.eintraege)}")
        for cause, count in sorted(causes.items(), key=lambda x: -x[1]):
            lines.append(f"  {cause}: {count}")
        lines.append("")

        # Per-entry detail
        lines.append("-" * 78)
        for e in self.eintraege:
            status_icon = "[!!]" if e.aktueller_status == "nicht gefunden" else "[~~]"
            lines.append(f"{status_icon} {e.erwartung_id}: {e.erwartung_titel}")
            lines.append(f"    Status: {e.aktueller_status}")
            lines.append(f"    Ursache: {e.ursache}")
            lines.append(f"    Detail: {e.ursache_detail}")

            if e.beste_finale_kurz:
                lines.append(
                    f"    Bester finaler Match: \"{e.beste_finale_kurz[:70]}\" "
                    f"(KW={e.beste_finale_kw:.2f}, T={e.beste_finale_titel:.2f})"
                )

            if e.bester_roh_kandidat:
                rk = e.bester_roh_kandidat
                lines.append(
                    f"    Bester Roh-Kandidat: \"{rk.kurzbeschreibung[:70]}\" "
                    f"(KW={rk.keyword_score:.2f}, T={rk.titel_score:.2f}) "
                    f"aus [{rk.pass_name}]"
                )
                if e.roh_kandidat_besser:
                    lines.append(
                        f"    >>> Roh-Kandidat war BESSER als finales Ergebnis — "
                        f"Konsolidierung hat wahrscheinlich Information verloren"
                    )

            lines.append(f"    Empfehlung: {e.empfehlung}")
            if e.relevante_passes:
                lines.append(f"    Relevante Passes: {', '.join(e.relevante_passes)}")
            lines.append("")

        lines.append("=" * 78)
        return "\n".join(lines)


def analysiere_misses(
    eval_ergebnis: EvaluationErgebnis,
    roh_kandidaten: dict[str, list[dict]] | None = None,
) -> MissAnalyseErgebnis:
    """Analyze why expected themes were missed or only partially found.

    Args:
        eval_ergebnis: result from evaluiere()
        roh_kandidaten: raw findings per pass from auswertung["roh_kandidaten"],
                        keyed by pass name. Can be None if not available.

    Returns:
        MissAnalyseErgebnis with per-theme root cause analysis.
    """
    result = MissAnalyseErgebnis(
        roh_kandidaten_verfuegbar=roh_kandidaten is not None and len(roh_kandidaten) > 0,
    )

    # Flatten all raw candidates for searching
    all_raw: list[dict] = []
    if roh_kandidaten:
        for pass_name, candidates in roh_kandidaten.items():
            for c in candidates:
                c_copy = dict(c)
                c_copy["_pass_name"] = pass_name
                all_raw.append(c_copy)

    for match in eval_ergebnis.matches:
        if match.status == "gefunden":
            continue

        eintrag = _analysiere_einzeln(match, all_raw, roh_kandidaten)
        result.eintraege.append(eintrag)

    return result


def _analysiere_einzeln(
    match: MatchErgebnis,
    all_raw: list[dict],
    roh_kandidaten: dict[str, list[dict]] | None,
) -> MissAnalyseEintrag:
    """Analyze one missed/partial theme."""
    erw = match.erwartung

    eintrag = MissAnalyseEintrag(
        erwartung_id=erw.id,
        erwartung_titel=erw.titel,
        aktueller_status=match.status,
        beste_finale_kurz=match.beste_fundstelle_kurz or "",
        beste_finale_kw=match.keyword_score,
        beste_finale_titel=match.titel_score,
        relevante_passes=_finde_relevante_passes(erw),
    )

    # Find best raw candidate match
    best_raw = _finde_besten_roh_match(erw, all_raw)
    if best_raw and best_raw.combined > 0.05:
        eintrag.bester_roh_kandidat = best_raw

        # Was the raw candidate better than the final match?
        final_combined = match.keyword_score * 0.7 + match.titel_score * 0.3
        eintrag.roh_kandidat_besser = best_raw.combined > final_combined + 0.05

    # Classify root cause
    _klassifiziere_ursache(eintrag, match, roh_kandidaten)

    return eintrag


def _finde_besten_roh_match(
    erw: ErwarteteFundstelle,
    all_raw: list[dict],
) -> RohKandidatMatch | None:
    """Find the best matching raw candidate across all passes."""
    if not all_raw:
        return None

    best = RohKandidatMatch()
    best_combined = 0.0

    for r in all_raw:
        corpus = " ".join([
            r.get("kurzbeschreibung", ""),
            r.get("erklaerung", "") or "",
            r.get("textstelle", "") or "",
            r.get("empfehlung", "") or "",
        ]).lower()

        kw = _keyword_score(erw.schluesselwoerter, corpus)
        ts = max(
            _similarity(erw.titel, r.get("kurzbeschreibung", "")),
            _similarity(erw.beschreibung[:80], r.get("kurzbeschreibung", "")),
        )
        combined = kw * 0.7 + ts * 0.3

        if combined > best_combined:
            best_combined = combined
            best = RohKandidatMatch(
                pass_name=r.get("_pass_name", r.get("quelle_pass", "")),
                kurzbeschreibung=r.get("kurzbeschreibung", ""),
                kategorie=r.get("kategorie", ""),
                keyword_score=kw,
                titel_score=ts,
                combined=combined,
            )

    return best if best_combined > 0 else None


def _finde_relevante_passes(erw: ErwarteteFundstelle) -> list[str]:
    """Determine which passes SHOULD have found this theme based on category."""
    relevant = []
    erw_cats_norm = {_norm(k) for k in erw.kategorien}

    for pass_name, pass_cats in PASS_KATEGORIE_ZUORDNUNG.items():
        pass_cats_norm = {_norm(c) for c in pass_cats}
        if erw_cats_norm & pass_cats_norm:
            relevant.append(pass_name)

    # Pass 1 should always be relevant (broad scan)
    if "Pass 1: Breite Ersterfassung" not in relevant:
        relevant.insert(0, "Pass 1: Breite Ersterfassung")

    return relevant


def _klassifiziere_ursache(
    eintrag: MissAnalyseEintrag,
    match: MatchErgebnis,
    roh_kandidaten: dict[str, list[dict]] | None,
) -> None:
    """Classify the root cause and set recommendation."""
    erw = match.erwartung
    roh = eintrag.bester_roh_kandidat
    has_raw_data = roh_kandidaten is not None and len(roh_kandidaten) > 0

    # Case 1: Good raw candidate that's better than final → consolidation loss
    if roh and eintrag.roh_kandidat_besser and roh.combined >= 0.3:
        eintrag.ursache = "IN_KONSOLIDIERUNG_VERLOREN"
        eintrag.ursache_detail = (
            f"Roh-Kandidat \"{roh.kurzbeschreibung[:50]}\" aus [{roh.pass_name}] "
            f"hatte besseren Match (KW={roh.keyword_score:.2f}) als das finale Ergebnis — "
            f"wurde vermutlich bei der Konsolidierung in einen anderen Fund zusammengeführt "
            f"oder verworfen."
        )
        eintrag.empfehlung = (
            "Konsolidierungsschwelle prüfen (similarity_threshold). "
            "Ggf. werden thematisch verschiedene Funde fälschlich zusammengelegt."
        )
        return

    # Case 2: Final match exists but with wrong/unexpected category
    if match.status == "teilweise gefunden" and match.beste_fundstelle_kurz:
        final_kw = match.keyword_score
        final_ts = match.titel_score

        # Check if keywords match well but category doesn't
        if final_kw >= 0.2:
            # Finding was found but maybe category doesn't align
            f_kat = _norm(match.beste_fundstelle_kurz)  # not ideal but we don't have category here
            # We can only check via the keyword/title scores
            if final_ts < 0.3 and final_kw >= 0.25:
                eintrag.ursache = "ZU_UNSPEZIFISCH_FORMULIERT"
                eintrag.ursache_detail = (
                    f"Finaler Fund \"{match.beste_fundstelle_kurz[:50]}\" enthält Schlüsselwörter "
                    f"(KW={final_kw:.2f}), aber Kurzbeschreibung ist zu generisch "
                    f"(Titel-Ähnlichkeit nur {final_ts:.2f})."
                )
                eintrag.empfehlung = (
                    "Prompt anpassen: LLM soll spezifischere Kurzbeschreibungen liefern, "
                    "die das konkrete Risiko benennen (nicht nur 'problematische Klausel')."
                )
                return

    # Case 3: Raw candidate exists but weak → prompt issue
    if roh and roh.combined >= 0.15 and roh.combined < 0.3:
        eintrag.ursache = "NUR_SCHWACH_ENTDECKT"
        eintrag.ursache_detail = (
            f"Roh-Kandidat \"{roh.kurzbeschreibung[:50]}\" aus [{roh.pass_name}] "
            f"ist nur schwach relevant (KW={roh.keyword_score:.2f}, T={roh.titel_score:.2f}). "
            f"Das Thema wurde vermutlich nicht gezielt genug angesprochen."
        )
        # Find the most relevant pass for this theme
        relevant_domain_pass = _finde_domain_pass(erw)
        if relevant_domain_pass:
            eintrag.empfehlung = (
                f"Prompt in Pass '{relevant_domain_pass}' schärfen: "
                f"Schlüsselwörter {erw.schluesselwoerter[:4]} explizit als Prüfpunkte aufnehmen."
            )
        else:
            eintrag.empfehlung = (
                "Prompts aller relevanten Passes schärfen. "
                f"Explizite Prüfpunkte für: {', '.join(erw.schluesselwoerter[:4])}"
            )
        return

    # Case 4: Check if the expected theme's domain pass produced zero candidates
    if has_raw_data and roh_kandidaten:
        relevant_passes = eintrag.relevante_passes
        empty_relevant = [
            p for p in relevant_passes
            if p in roh_kandidaten and len(roh_kandidaten[p]) == 0
        ]
        missing_relevant = [
            p for p in relevant_passes
            if p not in roh_kandidaten
        ]

        if empty_relevant:
            eintrag.ursache = "PASS_PROMPT_SCHWACH"
            eintrag.ursache_detail = (
                f"Relevante(r) Pass(es) {empty_relevant} hat/haben KEINE Kandidaten "
                f"produziert, obwohl das Thema in deren Domäne fällt."
            )
            eintrag.empfehlung = (
                f"Prompt in {empty_relevant[0]} überarbeiten: "
                f"Thema '{erw.titel}' als expliziten Prüfpunkt aufnehmen."
            )
            return

    # Case 5: No raw data or truly not discovered
    if not roh or roh.combined < 0.15:
        eintrag.ursache = "NICHT_ENTDECKT"
        relevant_domain_pass = _finde_domain_pass(erw)
        if has_raw_data:
            eintrag.ursache_detail = (
                f"Kein Roh-Kandidat aus keinem Pass matcht dieses Thema auch nur schwach. "
                f"Alle Passes haben das Thema übersehen."
            )
        else:
            eintrag.ursache_detail = (
                f"Keine Roh-Kandidaten-Daten verfügbar (Analyse vor dem Update). "
                f"Thema wurde im finalen Ergebnis nicht gefunden."
            )

        if relevant_domain_pass:
            eintrag.empfehlung = (
                f"Prompt in '{relevant_domain_pass}' ergänzen: "
                f"Prüfpunkt für '{erw.titel}' explizit aufnehmen. "
                f"Klausel-Hint: \"{erw.klausel_hint[:80]}...\""
            )
        else:
            eintrag.empfehlung = (
                f"Prüfpunkt in Pass 1 (Breite Ersterfassung) aufnehmen: "
                f"'{erw.titel}'. "
                f"Klausel-Hint: \"{erw.klausel_hint[:80]}...\""
            )
        return

    # Fallback: partial match but no clear cause
    eintrag.ursache = "KATEGORIE_UNPASSEND"
    eintrag.ursache_detail = (
        f"Finaler Fund vorhanden, aber Kategorie-Zuordnung weicht ab. "
        f"Erwartet: {erw.kategorien}. "
        f"Roh-Kandidat Kategorie: '{roh.kategorie if roh else 'unbekannt'}'."
    )
    eintrag.empfehlung = (
        "Prompt-Kategorieliste prüfen: ggf. Mapping zwischen erwarteter "
        "Kategorie und LLM-Ausgabekategorie anpassen."
    )


def _finde_domain_pass(erw: ErwarteteFundstelle) -> str:
    """Find the most specific pass responsible for this theme's domain."""
    erw_cats_norm = {_norm(k) for k in erw.kategorien}

    # Prefer Pass 2 sub-passes (more specific) over Pass 1 (broad)
    for pass_name, pass_cats in PASS_KATEGORIE_ZUORDNUNG.items():
        if pass_name.startswith("Pass 1"):
            continue  # Check specific passes first
        pass_cats_norm = {_norm(c) for c in pass_cats}
        if erw_cats_norm & pass_cats_norm:
            return pass_name

    return "Pass 1: Breite Ersterfassung"


def _count_causes(eintraege: list[MissAnalyseEintrag]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in eintraege:
        counts[e.ursache] = counts.get(e.ursache, 0) + 1
    return counts
