# Asana Sync

Background service that periodically extracts users and projects from the Asana API and stores each entity as an individual JSON file.

## How It Works

The service runs as a Flask web application with a background scheduler (APScheduler) that triggers a sync pipeline at a configurable interval.

### Sync Pipeline

1. **List entities** — fetches all users and projects from a given Asana workspace using paginated API calls.
2. **Fetch details concurrently** — for each user/project GID discovered in step 1, fetches the full detail record in parallel using a thread pool (up to 50 concurrent requests, matching Asana's concurrency limit).
3. **Write to disk** — each detail record is written as an individual JSON file (`<gid>.json`) under `asana/user_details/` and `asana/project_details/`. Files are overwritten on every run so the output always reflects the latest state.

### Rate Limit Handling

The Asana API client handles `429 Too Many Requests` responses automatically:

- Reads the `Retry-After` header and sleeps for the specified duration.
- Falls back to a 30-second wait if the header is missing.
- Retries up to 5 times before raising an error.
- A threading semaphore caps concurrent GET requests at 50 to stay within Asana's limits.

### Overlap Guard

A thread-safe `SyncState` object prevents concurrent sync runs. If a scheduled run fires while a previous sync is still active, it is skipped. This avoids duplicate API traffic and file-write conflicts.

## Project Structure

```
├── app.py               # Flask app + APScheduler setup + HTTP endpoints
├── asana_client.py      # Asana API client (pagination, rate limits, concurrency)
├── pipeline.py          # Extraction pipeline + SyncState overlap guard
├── gunicorn.conf.py     # Gunicorn config (single worker to avoid scheduler duplication)
├── tests/               # Test suite
│   ├── test_asana_client.py
│   ├── test_pipeline.py
│   └── test_app.py
├── Dockerfile           # Multi-stage build: test → production
├── docker-compose.yml
├── requirements.txt
└── .env                 # Environment variables (not committed)
```

## Output

Each sync produces individual JSON files named by GID:

```
asana/
├── user_details/
│   ├── 123456.json      # Full user record (name, email, photo, workspaces, ...)
│   └── 789012.json
└── project_details/
    ├── 345678.json      # Full project record (name, notes, custom_fields, members, ...)
    └── 901234.json
```

## Setup

### Environment Variables

Create a `.env` file:

```
ASANA_TOKEN=your-personal-access-token
ASANA_WORKSPACE_GID=your-workspace-gid
SYNC_INTERVAL=5m
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `ASANA_TOKEN` | Yes | — | Asana personal access token |
| `ASANA_WORKSPACE_GID` | Yes | — | Workspace GID to extract from |
| `SYNC_INTERVAL` | No | `5m` | Sync frequency: `5m` or `30s` |
| `OUTPUT_DIR` | No | `asana` | Directory for output JSON files |

## Running

### Docker (recommended)

```bash
docker compose build     # runs tests during build — failing tests fail the build
docker compose up -d     # starts the service on port 8000
```

The Docker build uses a multi-stage approach: a **test stage** runs the full test suite first, and the **production stage** only proceeds if all tests pass. The production image strips out test files and runs as a non-root user.

The output directory is mounted as a volume (`./asana:/app/asana`), so extracted JSON files are available on the host.

### Local development

```bash
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Start the service (runs on port 5001)
python app.py
```

On startup, the service immediately runs one sync and then continues on the configured interval.

### Gunicorn (production without Docker)

```bash
pip install -r requirements.txt
gunicorn app:app -c gunicorn.conf.py
```

Gunicorn is configured with a single worker to ensure the scheduler runs in exactly one process. The app is preloaded so the scheduler starts before the worker fork. Scaling is done by running multiple containers, not multiple workers.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check — returns `{"status": "ok"}` |
| `/status` | GET | Sync state — last run time, record counts, errors |
| `/trigger` | GET | Manually trigger a sync and return the resulting state |

### Example: check sync status

```bash
curl http://localhost:8000/status
```

```json
{
  "running": false,
  "last_sync": "2026-03-10T14:30:00.123456+00:00",
  "last_error": null,
  "users_count": 42,
  "projects_count": 15
}
```

## Testing

```bash
python -m pytest tests/ -v
```

All Asana API calls are mocked with `unittest.mock` — tests never hit the real API.

Test coverage includes:
- Authentication and request parameters
- Rate limiting (429 retry, Retry-After header, max retries exhaustion)
- Pagination (single page, multi-page, empty responses)
- Detail file output (one file per entity, overwrite behavior)
- Sync state management and overlap prevention
- Flask endpoints (`/health`, `/status`, `/trigger`)
