# Vertragsprüfung — KI-gestützte Vertragsanalyse

Webanwendung zur automatisierten Erstprüfung von Verträgen aus Auftragnehmer-Perspektive.
Schwerpunkt: hohe Erkennungsrate (Recall) bei der Identifikation problematischer Klauseln.

## Voraussetzungen

- Docker und Docker Compose (v2)
- Ports 8088 (Frontend) und 8766 (Backend-API) müssen frei sein
- Ein LLM-API-Schlüssel (OpenAI, Anthropic, Azure oder kompatibler Anbieter)

## Schnellstart auf dem Server

```bash
# 1. Repository klonen
git clone <repo-url> contract2
cd contract2

# 2. Umgebungsvariablen anlegen und anpassen
cp .env.example .env
# In .env mindestens POSTGRES_PASSWORD und SECRET_KEY ändern

# 3. Stack bauen
docker compose build

# 4. Stack starten
docker compose up -d

# 5. Logs prüfen
docker compose logs -f
```

## Zugriff

| Dienst    | URL                          |
|-----------|------------------------------|
| Frontend  | http://\<server\>:8088       |
| API       | http://\<server\>:8766       |
| API-Docs  | http://\<server\>:8766/docs  |
| Health    | http://\<server\>:8766/health |

Postgres ist nur intern erreichbar (kein Host-Port).

## Erste Testanalyse durchführen

### Schritt 1: LLM-Konfiguration setzen

Über die API (oder im Frontend unter "Einstellungen"):

```bash
# OpenAI-Beispiel:
curl -X PUT http://localhost:8766/api/einstellungen/llm_anbieter \
  -H "Content-Type: application/json" -d '{"wert": "openai"}'

curl -X PUT http://localhost:8766/api/einstellungen/llm_modell \
  -H "Content-Type: application/json" -d '{"wert": "gpt-4o"}'

curl -X PUT http://localhost:8766/api/einstellungen/llm_api_schluessel \
  -H "Content-Type: application/json" -d '{"wert": "sk-..."}'
```

### Schritt 2: Demo-Vertrag anlegen und Analyse starten

```bash
# Demo-Vertrag mit absichtlich problematischen Klauseln anlegen
curl -X POST http://localhost:8766/api/demo/vertrag-anlegen

# Vertrag-ID aus der Antwort nehmen, dann Analyse starten:
curl -X POST http://localhost:8766/api/analysen/vertrag/<VERTRAG-ID>
```

Oder im Frontend:
1. http://\<server\>:8088 aufrufen
2. "Demo-Vertrag laden" klicken
3. Auf den Vertragsnamen klicken
4. "Analyse starten" klicken
5. Fortschritt live verfolgen

### Schritt 3: Ergebnisse prüfen

```bash
# Analyse-Status prüfen
curl http://localhost:8766/api/analysen/vertrag/<VERTRAG-ID>

# Fundstellen abrufen
curl http://localhost:8766/api/fundstellen/vertrag/<VERTRAG-ID>

# Protokoll einer Analyse einsehen
curl http://localhost:8766/api/protokoll/analyse/<ANALYSE-ID>
```

Oder im Frontend die Vertragsdetailseite öffnen.

## Stack stoppen

```bash
docker compose down        # Container stoppen
docker compose down -v     # inkl. Volumes (Datenbank + Uploads löschen)
```

## Architektur

Siehe [ARCHITECTURE.md](ARCHITECTURE.md) für die vollständige Architekturdokumentation
und [docs/terminologie.md](docs/terminologie.md) für die deutsche Begriffsdefinition.
