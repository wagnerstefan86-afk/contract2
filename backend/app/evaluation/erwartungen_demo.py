"""Curated expected findings for the seeded demo contract.

Each entry represents a risky theme that the pipeline SHOULD detect.
The matching is semantic/keyword-based, not exact-string.

Structure per expectation:
  - id:             stable identifier for tracking across runs
  - titel:          short German title of the expected issue
  - beschreibung:   what the issue is and why it's risky for the Auftragnehmer
  - kategorien:     list of acceptable category labels (pipeline may use any of these)
  - min_risiko:     minimum expected risk level (Hinweis < Niedrig < Mittel < Hoch)
  - schluesselwoerter: keywords/phrases to match against finding text fields
  - klausel_hint:   indicative source text from the contract (for human reference)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ErwarteteFundstelle:
    id: str
    titel: str
    beschreibung: str
    kategorien: list[str] = field(default_factory=list)
    min_risiko: str = "Hinweis"
    schluesselwoerter: list[str] = field(default_factory=list)
    klausel_hint: str = ""


DEMO_ERWARTUNGEN: list[ErwarteteFundstelle] = [
    # ── 1. Scope creep / Auffangklausel ──────────────────────────────
    ErwarteteFundstelle(
        id="E01_SCOPE_AUFFANG",
        titel="Pauschale Leistungsumfang-Auffangklausel",
        beschreibung=(
            "Der Auftragnehmer schuldet 'alle damit zusammenhängenden Tätigkeiten, "
            "die zur Erreichung des Vertragszwecks erforderlich sind' — unbegrenzte "
            "Nachleistungspflicht ohne Vergütung."
        ),
        kategorien=["Leistungsumfang & Abgrenzung", "Vertragsmanagement", "Implizite Pflichten"],
        min_risiko="Mittel",
        schluesselwoerter=[
            "zusammenhängend", "vertragszweck", "erforderlich",
            "leistungsumfang", "auffang", "scope", "nachleistung",
            "alle damit", "pauschal",
        ],
        klausel_hint="alle damit zusammenhängenden Tätigkeiten, die zur Erreichung des Vertragszwecks erforderlich sind",
    ),

    # ── 2. Stand der Technik / vage Norm ─────────────────────────────
    ErwarteteFundstelle(
        id="E02_STAND_TECHNIK",
        titel="Vage Verweisung auf Stand der Technik",
        beschreibung=(
            "Leistungen müssen 'dem Stand der Technik' und 'jeweils aktuellen Fassungen' "
            "entsprechen — unkontrollierbarer, sich ändernder Maßstab."
        ),
        kategorien=["Compliance & Regulatorik", "Leistungsumfang & Abgrenzung", "Vertragsmanagement"],
        min_risiko="Hinweis",
        schluesselwoerter=[
            "stand der technik", "aktuellen fassungen", "normen",
            "standards", "einschlägig", "vage", "unbestimmt",
        ],
        klausel_hint="dem Stand der Technik entsprechen und die einschlägigen gesetzlichen und regulatorischen Anforderungen erfüllen",
    ),

    # ── 3. Überzogene Verfügbarkeit ──────────────────────────────────
    ErwarteteFundstelle(
        id="E03_VERFUEGBARKEIT_9995",
        titel="Extrem hohe Verfügbarkeitszusage (99,95%)",
        beschreibung=(
            "99,95% Verfügbarkeit 24x7x365 ist extrem anspruchsvoll. "
            "Wartungsfenster nur außerhalb 06-22 Uhr. Geplante Wartung zählt nur "
            "bei Vorankündigung nicht als Ausfall."
        ),
        kategorien=["Verfügbarkeit & Betrieb", "SLA / Verfügbarkeit"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "99,95", "verfügbarkeit", "24x7", "wartungsfenster",
            "geschäftszeiten", "ausfallzeit", "sla",
        ],
        klausel_hint="Verfügbarkeit der betriebenen Systeme von 99,95% gemessen auf Monatsbasis (24x7x365)",
    ),

    # ── 4. Vertragsstrafe nicht anrechenbar ──────────────────────────
    ErwarteteFundstelle(
        id="E04_VERTRAGSSTRAFE_KUMULATIV",
        titel="Kumulative Vertragsstrafe ohne Anrechnung auf Schadensersatz",
        beschreibung=(
            "Vertragsstrafen werden NICHT auf den Gesamtschaden angerechnet. "
            "Kumuliert mit vollen Schadensersatzansprüchen."
        ),
        kategorien=[
            "Haftung & Gewährleistung", "Verfügbarkeit & Betrieb",
            "SLA / Verfügbarkeit", "Vertragsmanagement",
        ],
        min_risiko="Hoch",
        schluesselwoerter=[
            "vertragsstrafe", "nicht anrechenbar", "nicht anzurechnen",
            "anrechnung", "schadensersatz", "kumulativ", "kumuliert",
            "weitergehende", "unberührt",
        ],
        klausel_hint="Die Vertragsstrafe ist nicht auf den Gesamtschaden anzurechnen",
    ),

    # ── 5. Unrealistische Reaktionszeiten ────────────────────────────
    ErwarteteFundstelle(
        id="E05_REAKTIONSZEIT_15MIN",
        titel="Unrealistische Reaktionszeit bei Priorität 1 (15 Minuten)",
        beschreibung=(
            "15 Minuten Reaktionszeit bei Totalausfall mit 2h Wiederherstellung "
            "ist extrem ambitioniert. Prioritätseinstufung einseitig durch AG."
        ),
        kategorien=["Verfügbarkeit & Betrieb", "SLA / Verfügbarkeit"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "15 minuten", "reaktionszeit", "priorität 1", "totalausfall",
            "wiederherstellung", "2 stunden", "einseitig", "prioritätseinstufung",
        ],
        klausel_hint="Priorität 1 (Totalausfall): Reaktion innerhalb von 15 Minuten",
    ),

    # ── 6. Einseitige Prioritätseinstufung ───────────────────────────
    ErwarteteFundstelle(
        id="E06_PRIO_EINSEITIG",
        titel="Einseitige Prioritätseinstufung durch Auftraggeber",
        beschreibung=(
            "Der AG bestimmt allein die Priorität von Störungen — "
            "Missbrauchspotenzial ohne Eskalationsschutz."
        ),
        kategorien=["Verfügbarkeit & Betrieb", "Vertragsmanagement", "SLA / Verfügbarkeit"],
        min_risiko="Mittel",
        schluesselwoerter=[
            "prioritätseinstufung", "ausschließlich", "einseitig",
            "auftraggeber", "störung", "priorität",
        ],
        klausel_hint="Die Prioritätseinstufung erfolgt ausschließlich durch den Auftraggeber",
    ),

    # ── 7. ISO 27001 Pflicht + BSI-Grundschutz ──────────────────────
    ErwarteteFundstelle(
        id="E07_ISO27001_PFLICHT",
        titel="ISO 27001 Zertifizierungspflicht und BSI-Grundschutz",
        beschreibung=(
            "Mandatory ISO 27001 certification + BSI Grundschutz implementation "
            "during entire contract term — significant ongoing cost."
        ),
        kategorien=["Informationssicherheit", "Compliance & Regulatorik"],
        min_risiko="Mittel",
        schluesselwoerter=[
            "iso 27001", "isms", "zertifizierung", "bsi",
            "grundschutz", "informationssicherheit",
        ],
        klausel_hint="ISMS gemäß ISO 27001 zu betreiben und die Zertifizierung während der gesamten Vertragslaufzeit aufrechtzuerhalten",
    ),

    # ── 8. 4h Meldefrist + IR-Team 30min ─────────────────────────────
    ErwarteteFundstelle(
        id="E08_INCIDENT_MELDEPFLICHT",
        titel="Extrem kurze Incident-Meldepflicht und IR-Team-Bereitschaft",
        beschreibung=(
            "Sicherheitsvorfälle binnen 4h melden + IR-Team in 30min voll "
            "einsatzbereit auf eigene Kosten."
        ),
        kategorien=["Informationssicherheit"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "4 stunden", "sicherheitsvorfall", "incident", "meldepflicht",
            "response", "30 minuten", "eigene kosten", "unverzüglich",
            "kenntniserlangung",
        ],
        klausel_hint="spätestens jedoch innerhalb von 4 Stunden nach Kenntniserlangung, zu melden",
    ),

    # ── 9. RTO/RPO auf eigene Kosten ─────────────────────────────────
    ErwarteteFundstelle(
        id="E09_BCM_RTO_RPO",
        titel="Unrealistische RTO/RPO-Zusagen auf eigene Kosten",
        beschreibung=(
            "RTO 4h / RPO 1h mit georedundantem RZ auf eigene Kosten — "
            "massive Infrastrukturinvestition ohne Vergütung."
        ),
        kategorien=["Verfügbarkeit & Betrieb", "Informationssicherheit"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "rto", "rpo", "4 stunden", "1 stunde", "georedundant",
            "eigene kosten", "disaster recovery", "business continuity",
            "wiederherstellung", "katastrophenfall",
        ],
        klausel_hint="RTO von 4 Stunden und eines RPO von 1 Stunde",
    ),

    # ── 10. Regulatorik-Übernahme auf eigene Kosten ──────────────────
    ErwarteteFundstelle(
        id="E10_REGULATORIK_BLANKO",
        titel="Pauschale Übernahme regulatorischer Anforderungen des AG",
        beschreibung=(
            "AN muss SÄMTLICHE für den AG geltenden Regularien einhalten "
            "(DORA, NIS2, BAIT, DSGVO, BaFin) und Änderungen auf eigene "
            "Kosten umsetzen."
        ),
        kategorien=["Compliance & Regulatorik"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "dora", "nis2", "bait", "dsgvo", "bafin", "regulatorisch",
            "sämtliche", "eigene kosten", "ohne vergütung",
            "regulatorik", "compliance", "änderungen",
        ],
        klausel_hint="sämtlichen für den Auftraggeber geltenden regulatorischen Anforderungen",
    ),

    # ── 11. Audit ohne Vorankündigung + Kosten AN ────────────────────
    ErwarteteFundstelle(
        id="E11_AUDIT_UEBERDEHNT",
        titel="Überzogene Audit- und Zutrittsrechte",
        beschreibung=(
            "Jederzeit unangekündigte Vor-Ort-Prüfungen, auch durch BaFin-Dritte. "
            "Kosten trägt vollständig der AN. Berichtsformat einseitig bestimmt."
        ),
        kategorien=["Audit & Berichtswesen", "Vertragsmanagement"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "audit", "prüfung", "ohne vorankündigung", "jederzeit",
            "vor-ort", "dritte", "kosten", "auftragnehmer",
            "bafin", "compliance-bericht", "uneingeschränkt",
        ],
        klausel_hint="jederzeit und auch ohne Vorankündigung zu prüfen",
    ),

    # ── 12. Unbeschränkte Haftung ────────────────────────────────────
    ErwarteteFundstelle(
        id="E12_HAFTUNG_UNBESCHRAENKT",
        titel="Unbeschränkte Haftung und Freistellungspflicht",
        beschreibung=(
            "AN haftet unbeschränkt für alle Vertragspflichtverletzungen. "
            "Haftungsbeschränkung auf leichte Fahrlässigkeit ausgeschlossen. "
            "Vollständige Drittfreistellung."
        ),
        kategorien=["Haftung & Gewährleistung"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "unbeschränkt", "haftung", "freistellung", "fahrlässigkeit",
            "dritte", "schutzrechte", "unbegrenzt", "alle schäden",
        ],
        klausel_hint="Der Auftragnehmer haftet unbeschränkt für alle Schäden",
    ),

    # ── 13. 10M€ Versicherung ────────────────────────────────────────
    ErwarteteFundstelle(
        id="E13_VERSICHERUNG_10M",
        titel="Hohe Pflichtversicherung (10 Mio. €)",
        beschreibung=(
            "Berufshaftpflicht mit 10 Mio. € Deckungssumme je Schadensfall — "
            "hohe laufende Kosten, ggf. marktunüblich."
        ),
        kategorien=["Haftung & Gewährleistung", "Vertragsmanagement"],
        min_risiko="Mittel",
        schluesselwoerter=[
            "10 millionen", "10 mio", "versicherung", "haftpflicht",
            "deckungssumme", "berufshaftpflicht", "schadensfall",
        ],
        klausel_hint="Berufshaftpflichtversicherung mit einer Deckungssumme von mindestens 10 Millionen Euro",
    ),

    # ── 14. Personalaustausch ohne Begründung ────────────────────────
    ErwarteteFundstelle(
        id="E14_PERSONAL_AUSTAUSCH",
        titel="Einseitiges Personalablehnungsrecht ohne Begründung",
        beschreibung=(
            "AG kann Austausch einzelner AN-Mitarbeiter ohne Angabe von Gründen "
            "verlangen. AN muss in 10 Werktagen Ersatz stellen."
        ),
        kategorien=["Personalanforderungen", "Vertragsmanagement"],
        min_risiko="Mittel",
        schluesselwoerter=[
            "austausch", "ohne angabe von gründen", "personal",
            "mitarbeiter", "schlüsselpersonal", "10 werktage", "ersatz",
        ],
        klausel_hint="den Austausch einzelner Mitarbeiter des Auftragnehmers ohne Angabe von Gründen zu verlangen",
    ),

    # ── 15. Laufzeit 60 Monate + 24 Monate Verlängerung ─────────────
    ErwarteteFundstelle(
        id="E15_LAUFZEIT_LANG",
        titel="Extrem lange Vertragslaufzeit mit Auto-Verlängerung",
        beschreibung=(
            "60 Monate Mindestlaufzeit, automatische 24-Monats-Verlängerung, "
            "12 Monate Kündigungsfrist. Sehr lange Bindung."
        ),
        kategorien=["Vertragsmanagement", "Kündigung / Laufzeit"],
        min_risiko="Mittel",
        schluesselwoerter=[
            "60 monate", "mindestlaufzeit", "24 monate", "verlängerung",
            "automatisch", "kündigungsfrist", "12 monate", "laufzeit",
        ],
        klausel_hint="Mindestlaufzeit von 60 Monaten. Er verlängert sich jeweils automatisch um weitere 24 Monate",
    ),

    # ── 16. Weiter Kündigungsgrund des AG ────────────────────────────
    ErwarteteFundstelle(
        id="E16_KUENDIGUNG_EINSEITIG",
        titel="Einseitiges außerordentliches Kündigungsrecht des AG",
        beschreibung=(
            "AG kann jederzeit außerordentlich kündigen. 'Wesentliche Änderung "
            "der Geschäftsstrategie' gilt als wichtiger Grund — extrem weit."
        ),
        kategorien=["Vertragsmanagement", "Kündigung / Laufzeit"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "kündigung", "wichtiger grund", "geschäftsstrategie",
            "jederzeit", "außerordentlich", "einseitig",
        ],
        klausel_hint="wesentliche Änderung der Geschäftsstrategie des Auftraggebers",
    ),

    # ── 17. Transition auf Kosten AN ─────────────────────────────────
    ErwarteteFundstelle(
        id="E17_TRANSITION_KOSTEN",
        titel="Transitionspflicht auf Kosten des Auftragnehmers",
        beschreibung=(
            "Bei Vertragsende vollständige Transition an Nachfolger auf "
            "Kosten des AN, bis zu 12 Monate Dauer."
        ),
        kategorien=["Vertragsmanagement", "Kündigung / Laufzeit"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "transition", "nachfolge", "kosten des auftragnehmers",
            "12 monate", "vertragsende", "vollständig",
        ],
        klausel_hint="Die Transition erfolgt auf Kosten des Auftragnehmers und kann bis zu 12 Monate dauern",
    ),

    # ── 18. IP-Übertragung + Rechteverzicht ──────────────────────────
    ErwarteteFundstelle(
        id="E18_IP_UEBERTRAGUNG",
        titel="Vollständige IP-Übertragung mit unwiderruflichem Rechteverzicht",
        beschreibung=(
            "Alle Arbeitsergebnisse gehen mit Entstehung ins ausschließliche "
            "Eigentum des AG über. AN verzichtet unwiderruflich auf alle Rechte."
        ),
        kategorien=["Geistiges Eigentum", "Vertragsmanagement"],
        min_risiko="Hoch",
        schluesselwoerter=[
            "geistiges eigentum", "eigentum", "arbeitsergebnisse",
            "unwiderruflich", "verzicht", "ausschließlich", "ip",
            "software", "dokumentation", "entstehung",
        ],
        klausel_hint="gehen mit ihrer Entstehung in das ausschließliche Eigentum des Auftraggebers über",
    ),

    # ── 19. Subunternehmer-Durchgriff ────────────────────────────────
    ErwarteteFundstelle(
        id="E19_SUBUNTERNEHMER",
        titel="Vollständige Haftungsdurchgriff auf Subunternehmer",
        beschreibung=(
            "AN haftet für Subunternehmer wie für eigenes Verschulden. "
            "Alle vertraglichen Anforderungen gelten in vollem Umfang weiter."
        ),
        kategorien=["Vertragsmanagement", "Haftung & Gewährleistung"],
        min_risiko="Mittel",
        schluesselwoerter=[
            "subunternehmer", "eigenes verschulden", "genehmigung",
            "sicherheitsanforderungen", "audit-rechte", "vollem umfang",
        ],
        klausel_hint="haftet für Subunternehmer wie für eigenes Verschulden",
    ),
]
