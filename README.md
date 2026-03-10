# Asana Sync

Background service that periodically extracts users and projects from the Asana API and stores each entity as an individual JSON file.

## Project Structure

```
├── app.py               # Flask app + APScheduler
├── asana_client.py      # Asana API client (pagination, rate limit handling)
├── pipeline.py          # Extraction pipeline + sync state
├── gunicorn.conf.py     # Gunicorn production config
├── tests/               # Test suite (32 tests)
│   ├── test_asana_client.py
│   ├── test_pipeline.py
│   └── test_app.py
├── Dockerfile           # Multi-stage: test → production
├── docker-compose.yml
├── requirements.txt
└── .env                 # Environment variables (not committed)
```

## Output

Each sync produces individual JSON files named by GID:

```
asana/
├── users/
│   ├── 123456.json      # {"gid": "123456", "name": "Alice", "email": "alice@example.com"}
│   └── 789012.json
└── projects/
    ├── 345678.json      # {"gid": "345678", "name": "My Project", "archived": false, ...}
    └── 901234.json
```

Files are overwritten on each sync run.

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

### Docker (recommended)

```bash
docker compose build     # runs tests during build
docker compose up -d
```

### Local

```bash
pip install -r requirements.txt
python app.py
```

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check — returns `{"status": "ok"}` |
| `GET /status` | Sync state — last run time, record counts, errors |
| `GET /trigger` | Manually trigger a sync |

## Rate Limit Handling

The client respects Asana's rate limits:

- On `429 Too Many Requests`, reads the `Retry-After` header and waits
- Falls back to 30s wait if header is missing
- Retries up to 5 times before failing
- Overlap guard skips scheduled runs if a previous sync is still active

## Testing

```bash
python -m pytest tests/ -v
```

Tests are also executed during `docker compose build` — a failing test will fail the build.

Test coverage includes:
- Authentication and request parameters
- Rate limiting (429 retry, Retry-After header, max retries exhaustion)
- Pagination (single page, multi-page, empty responses)
- File output (one file per entity, overwrite behavior)
- Sync state management and overlap prevention
- Flask endpoints