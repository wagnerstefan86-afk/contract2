# Deutsche Terminologie — Vertragsprüfung

Dieses Dokument definiert die verbindliche deutsche Terminologie für die gesamte Benutzeroberfläche.
Interne Code-Bezeichnungen (Variablen, Dateinamen) dürfen englisch bleiben.

## Kern-Entitäten

| Deutsch         | Englisch (intern)  | Beschreibung                                |
|-----------------|--------------------|---------------------------------------------|
| Vertrag         | Contract           | Hochgeladenes Vertragsdokument              |
| Analyse         | Analysis           | Ein Analyselauf über einen Vertrag          |
| Fundstelle      | Finding            | Eine entdeckte problematische Stelle        |
| Prüfung         | Review             | Menschliche Überprüfung einer Fundstelle    |
| Einstellung     | Setting            | Systemkonfiguration (LLM, etc.)            |
| Protokoll       | Log                | System- und Analyseprotokoll               |

## Statuskategorien

### Vertragsstatus
- **Hochgeladen** — Datei empfangen, noch nicht verarbeitet
- **Extrahiert** — Text erfolgreich extrahiert
- **In Analyse** — Analyselauf aktiv
- **Analysiert** — Analyse abgeschlossen
- **Archiviert** — Nicht mehr aktiv

### Analysestatus
- **Gestartet** — Analyselauf initialisiert
- **Pass 1 läuft** — Breite Ersterfassung aktiv
- **Pass 2 läuft** — Perspektivische Vertiefung aktiv
- **Pass 3 läuft** — Suche nach impliziten Pflichten aktiv
- **Pass 4 läuft** — Querverweisanalyse aktiv
- **Konsolidierung** — Zusammenführung und Deduplizierung
- **Abgeschlossen** — Erfolgreich beendet
- **Fehlgeschlagen** — Mit Fehler abgebrochen

### Risikostufe
- **Hoch** — Kritisches Risiko für den Auftragnehmer
- **Mittel** — Erhöhtes Risiko, Verhandlung empfohlen
- **Niedrig** — Geringes Risiko, zur Kenntnis nehmen
- **Hinweis** — Informativ, kein direktes Risiko

### Prüfstatus (Fundstelle)
- **Offen** — Noch nicht überprüft
- **Bestätigt** — Fundstelle als relevant bestätigt
- **Abgelehnt** — Als Fehlalarm eingestuft
- **Zurückgestellt** — Entscheidung vertagt

## Kategorien der Fundstellen

| Kategorie                        | Umfang                                       |
|----------------------------------|----------------------------------------------|
| Informationssicherheit           | Verschlüsselung, Zugriff, Vorfälle         |
| Datenschutz                      | DSGVO, Datenverarbeitung                     |
| Compliance & Regulatorik         | Regulatorische Durchreichung, Zertifikate   |
| Verfügbarkeit & Betrieb          | SLA, Betriebszeit, BCM, DR                  |
| Haftung & Gewährleistung         | Haftungsgrenzen, Freistellung               |
| Audit & Berichtswesen            | Prüfrechte, Berichtspflichten               |
| Vertragsmanagement               | Kündigung, Verlängerung, Änderungsverfahren |
| Leistungsumfang & Abgrenzung     | Scope Creep, unklare Leistungsbeschreibung  |
| Personalanforderungen            | Personalvorgaben, Schlüsselpersonal         |
| Geistiges Eigentum               | IP-Übertragung, Lizenzierung                |
| Implizite Pflichten              | Versteckte / stillschweigende Verpflichtungen|

## UI-Aktionen

| Deutsch              | Aktion                          |
|----------------------|---------------------------------|
| Hochladen            | Vertrag hochladen               |
| Analyse starten      | Neuen Analyselauf starten       |
| Löschen              | Vertrag / Fundstelle entfernen  |
| Bestätigen           | Fundstelle als relevant markieren |
| Ablehnen             | Fundstelle als Fehlalarm markieren |
| Zurückstellen        | Entscheidung vertagen           |
| Speichern            | Änderungen speichern            |
| Verbindung testen    | LLM-Verbindung prüfen          |
| Exportieren          | Ergebnisse exportieren          |
