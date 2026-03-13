# Vertragsprüfung — KI-gestützte Vertragsanalyse

Webanwendung zur automatisierten Erstprüfung von Verträgen aus Auftragnehmer-Perspektive.
Schwerpunkt: hohe Erkennungsrate (Recall) bei der Identifikation problematischer Klauseln.

## Voraussetzungen

- Docker und Docker Compose (v2)
- Ports 8088 (Frontend) und 8766 (Backend-API) müssen frei sein

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
| Frontend  | http://&lt;server&gt;:8088   |
| API       | http://&lt;server&gt;:8766   |
| API-Docs  | http://&lt;server&gt;:8766/docs |
| Health    | http://&lt;server&gt;:8766/health |

Postgres ist nur intern erreichbar (kein Host-Port).

## Stack stoppen

```bash
docker compose down        # Container stoppen
docker compose down -v     # inkl. Volumes (Datenbank + Uploads löschen)
```

## Architektur

Siehe [ARCHITECTURE.md](ARCHITECTURE.md) für die vollständige Architekturdokumentation
und [docs/terminologie.md](docs/terminologie.md) für die deutsche Begriffsdefinition.
