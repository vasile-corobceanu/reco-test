# Asana Sync — Claude Code Instructions

## Project Overview

Background service that periodically extracts users and projects from the Asana API, writing each entity as an individual JSON file to `asana/`.

## Architecture

- `asana_client.py` — Asana API client with pagination and rate limit retry (respects `Retry-After` header)
- `pipeline.py` — extraction pipeline with overlap guard (`SyncState`), writes `asana/user_details/<gid>.json` and `asana/project_details/<gid>.json`
- `app.py` — Flask + APScheduler, exposes `/health`, `/status`, `/trigger`
- `gunicorn.conf.py` — single worker (scheduler must not be duplicated)

## Key Conventions

- Use explicit keyword arguments for function calls
- Keep comments minimal — only where logic isn't self-evident
- All API interaction goes through `AsanaClient` — never call `requests` directly elsewhere
- Tests use `unittest.mock` to mock HTTP responses — no real API calls in tests
- Output files are overwritten each sync run, not appended

## Environment Variables

- `ASANA_TOKEN` — Asana personal access token (required)
- `ASANA_WORKSPACE_GID` — workspace to sync (required)
- `SYNC_INTERVAL` — `"5m"` or `"30s"` (default: `"5m"`)
- `OUTPUT_DIR` — output directory (default: `"asana"`)

## Running

```bash
# Local
python -m pytest tests/ -v
python app.py

# Docker
docker compose build    # tests run during build
docker compose up -d
```

## Testing

- Tests live in `tests/` and run during Docker build (fail = build fails)
- All Asana API calls are mocked — tests never hit the real API
- Run locally: `python -m pytest tests/ -v`