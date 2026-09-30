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
| API (dev, reload) | `uv run uvicorn optifuel.api:app --reload` |
| Docker | `docker build -t optifuel . && docker run --rm -p 8000:8000 optifuel` |

## Tooling

- **uv**: env, Python version, lockfile (`uv.lock`). Dependency groups: `dev` (tests, lint, types), `analysis` (JupyterLab, plotting). Docker image installs runtime deps only.
- **ruff**: lint + format. Rule set in `pyproject.toml`.
- **ty**: type checker (Astral), whole project. Any diagnostic fails. Editor: `ty server` LSP (VS Code "ty" extension).
- **pytest** + **pytest-cov**.
- **pre-commit**: ruff, ty, zizmor (GitHub Actions security audit; SHA pins required via `.github/zizmor.yml`), `uv.lock` sync check, file hygiene, private-key detection.
- **GitHub Actions** (`.github/workflows/ci.yml`): pre-commit, tests, Docker build; actions pinned by commit SHA. **Dependabot** bumps uv deps, actions (SHA + version comment), Docker base image weekly, 7-day cooldown.

Rationale and rejected alternatives: [`REPORT.md`](REPORT.md).
