# OptiFuel

Technical test.

- `exercise_1/`: fuel flow data analysis. `analysis.ipynb` (outputs committed) uses `cleanup.py`, `compute.py`, `plot.py`. Datasets: `signals_*.pkl`.
- `src/optifuel/`: OptiFuel job processor service (exercise 2).
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
| Local stack (postgres, migrate, api, worker-abc, worker-xyz, weather stub) | `docker compose -f deploy/compose.yaml up --build`; API on `localhost:8000` |
| Submit a plan to the stack as ABC | `curl -H 'X-Airline: ABC' -H 'Content-Type: application/json' -d '{"type": "fuel_estimate", "payload": {"airline": "ABC", "aircraft_type": "B777", "registration": "EC-ABC", "flight_id": 1, "waypoints": [{"latitude": 41.3, "longitude": 2.1, "speed": 200, "altitude": 5000}, {"latitude": 41.8, "longitude": 3.0, "speed": 180, "altitude": 4000}]}}' localhost:8000/v1/jobs`, then `curl -H 'X-Airline: ABC' localhost:8000/v1/jobs/<id>` |
| API (dev, reload) | `OPTIFUEL_DATABASE_URL=postgresql://... uv run uvicorn --factory optifuel.api:from_env --reload` |
| Worker (one per airline) | `uv run python -m optifuel.worker` with `OPTIFUEL_WORKER_AIRLINE`, `OPTIFUEL_TENANTS`, `OPTIFUEL_MODEL_DIR` (holding `<airline>/<version>.json`), `OPTIFUEL_WEATHER_URL`, `OPTIFUEL_WEATHER_TOKEN`, `OPTIFUEL_DATABASE_URL` |
| Migrate (Procrastinate schema + `job_records`) | `uv run python -m optifuel.migrate` with `OPTIFUEL_DATABASE_URL` |
| Docker (API only; `/health` answers, `/ready` needs Postgres) | `docker build -t optifuel . && docker run --rm -p 8000:8000 -e OPTIFUEL_DATABASE_URL=postgresql://unused optifuel` |

## Tooling

- **uv**: env, Python version, lockfile (`uv.lock`). Dependency groups: `dev` (tests, lint, types), `analysis` (JupyterLab, plotting). Docker image installs runtime deps only.
- **ruff**: lint + format. Rule set in `pyproject.toml`.
- **ty**: type checker (Astral), whole project. Any diagnostic fails. Editor: `ty server` LSP (VS Code "ty" extension).
- **pytest** + **pytest-cov**.
- **pre-commit**: ruff, ty, zizmor (GitHub Actions security audit; SHA pins required via `.github/zizmor.yml`), `uv.lock` sync check, file hygiene, private-key detection.
- **GitHub Actions** (`.github/workflows/ci.yml`): pre-commit, tests, Docker build; actions pinned by commit SHA. **Dependabot** bumps uv deps, actions (SHA + version comment), Docker base image weekly, 7-day cooldown.

Architecture, decisions, rejected alternatives, and implementation plan: [`ARCHITECTURE.md`](ARCHITECTURE.md).
