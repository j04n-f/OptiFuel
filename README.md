# OptiFuel

Technical test.

- `exercise_1/`: fuel flow data analysis. `analysis.ipynb` (outputs committed) uses `cleanup.py`, `compute.py`, `plot.py`. Datasets: `signals_*.pkl`.
- `src/`: OptiFuel job processor service (exercise 2), imported as package `src`.
- `tests/`: pytest suite.

## Setup

Requires [uv](https://docs.astral.sh/uv/). uv installs the pinned Python (`.python-version`) itself.

```sh
uv sync                        # venv + all groups (dev, analysis)
uv run pre-commit install      # git hooks
```

## Commands

| Task | Command |
| --- | --- |
| Tests + coverage | `uv run pytest` |
| Lint + format + type check (all hooks) | `uv run pre-commit run --all-files` |
| Lint / fix | `uv run ruff check --fix` |
| Format | `uv run ruff format` |
| Type check | `uv run ty check` |
| Exercise 1 notebook | `uv run jupyter lab exercise_1/analysis.ipynb` (Run All + save after changing the modules) |
| Local stack (postgres, migrate, seed, api, worker-abc, worker-xyz, cleanup, weather stub) | `docker compose up --build`; page and API on `localhost:8000` |
| Demo data: airline `DEMO` with one job per status (queued, running, succeeded, failed) | Seeded by compose on `up`; re-seed with `docker compose run --rm seed`. Outside compose: `uv run python scripts/seed.py` with `OPTIFUEL_DATABASE_URL`; refuses when `OPTIFUEL_ENVIRONMENT=prod` |
| Submit a plan to the stack as ABC | `curl -H 'X-Airline: ABC' -H 'Content-Type: application/json' -d '{"type": "fuel_estimate", "payload": {"airline": "ABC", "aircraft_type": "B777", "registration": "EC-ABC", "flight_id": 1, "waypoints": [{"latitude": 41.3, "longitude": 2.1, "speed": 200, "altitude": 5000}, {"latitude": 41.8, "longitude": 3.0, "speed": 180, "altitude": 4000}]}}' localhost:8000/v1/jobs`, then `curl -H 'X-Airline: ABC' localhost:8000/v1/jobs/<id>` |
| API (dev, reload) | `OPTIFUEL_DATABASE_URL=postgresql://... uv run uvicorn --factory src.api:from_env --reload` |
| Worker (one per airline) | `uv run python -m src.worker` with `OPTIFUEL_WORKER_AIRLINE`, `OPTIFUEL_TENANTS`, `OPTIFUEL_MODEL_DIR` (holding `<airline>/<version>.json`), `OPTIFUEL_WEATHER_URL`, `OPTIFUEL_WEATHER_TOKEN`, `OPTIFUEL_DATABASE_URL` |
| Migrate (Procrastinate schema + `job_records`) | `uv run python -m src.migrate` with `OPTIFUEL_DATABASE_URL` |
| Cleanup (requeue jobs of dead workers, purge finished jobs after `OPTIFUEL_RETENTION_DAYS`, default 30) | `uv run python -m src.cleanup` with `OPTIFUEL_DATABASE_URL`; compose runs it every 5 minutes, once now with `docker compose run --rm cleanup python -m src.cleanup` |
| Docker (API only; `/health` answers, `/ready` needs Postgres) | `docker build -t optifuel . && docker run --rm -p 8000:8000 -e OPTIFUEL_DATABASE_URL=postgresql://unused optifuel` |

## Tooling

- **uv**: env, Python version, lockfile (`uv.lock`). Dependency groups: `dev` (tests, lint, types), `analysis` (JupyterLab, plotting). Docker image installs runtime deps only.
- **ruff**: lint + format. Rule set in `pyproject.toml`.
- **ty**: type checker (Astral), whole project. Any diagnostic fails. Editor: `ty server` LSP (VS Code "ty" extension).
- **pytest** + **pytest-cov**.
- **pre-commit**: ruff, ty, zizmor (GitHub Actions security audit; SHA pins required via `.github/zizmor.yml`), `uv.lock` sync check, file hygiene, private-key detection.
- **GitHub Actions** (`.github/workflows/ci.yml`): pre-commit, tests, Docker build; actions pinned by commit SHA. **Dependabot** bumps uv deps, actions (SHA + version comment), Docker base image weekly, 7-day cooldown.

Architecture, decisions, rejected alternatives, and implementation plan: [`ARCHITECTURE.md`](ARCHITECTURE.md).
