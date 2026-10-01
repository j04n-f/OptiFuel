# Engineering principles

**Build ladder.** The best code is code never written. Before writing code, stop at the first rung that works:

1. Skip it (YAGNI).
2. Standard library.
3. Platform feature.
4. Installed dependency.
5. A one-line change.
6. The minimum code that solves the problem.

**Rules:**

- Prefer deletion to addition, boring to clever, and fewer files to more.
- Change only what was asked. Match the surrounding style. Remove anything your change leaves unused.
- Read a file in full before editing it. Search results locate code; they do not justify a change.
- Ask before removing behaviour that looks intentional.
- The project is 0.x: break APIs freely. Add compatibility shims only on request.
- Add abstractions and dependencies only when requested or when the ladder forces them.
- When two options cost the same, choose the one that handles edge cases correctly.

**Be relentless about:** input validation, error handling wherever data could be lost, security, accessibility, and explicit requests. Non-trivial logic ships with one runnable check, written as **Tests** below describes.

**Multi-step work:** before starting, state assumptions, raise ambiguities, outline the plan, and push back on unnecessary complexity.

# Communication

Write tersely: every sentence carries a fact, a decision, or a risk. Sentence fragments are fine; technical terms are exact.

- Structure statements as `[subject] [action] [reason]`.
- When receiving feedback, state agreement or disagreement first, then what changed.
- For non-trivial design, give the problem, a concrete trace, and the solution, and explain why the solution is necessary.
- Write in full prose for security warnings, irreversible actions, code, commits, and PRs.

# Before pushing

`README.md` is the command table; `pyproject.toml` holds every tool's config. Done means CI's four jobs pass locally: `uv run pre-commit run --all-files` (Lint: ruff, ty, zizmor, uv-lock, file hygiene), `uv run pytest` (Test), the image builds (Docker), and `scripts/kind-smoke.sh` (Kind Smoke).

- **Commits**: conventional commits, imperative lowercase subject, 72 columns.
- **Warnings are errors** (`filterwarnings = ["error"]`). Fix a deprecation at its cause, the way `httpx2` replaced `httpx` for Starlette's `TestClient`; a warning filter needs the user's OK.
- **Suppressions** name the rule and the reason: `# noqa: S301  provided dataset`, `# ty: ignore[<rule>]  <reason>`. ty is beta: a ty bump that adds diagnostics lands with its fixes.
- **Deps** move through `uv add` / `uv remove`: `--group dev` for tooling, `--group analysis` for exercise-1-only libraries. Runtime `dependencies` is exactly what the Docker image ships, so it holds only what `src/` imports.
- **Pins**: every action is a full commit SHA plus `# vX.Y.Z` (zizmor fails anything else); resolve with `git ls-remote https://github.com/<owner>/<repo> refs/tags/<tag> 'refs/tags/<tag>^{}'`, taking the `^{}` line when present (annotated tag). Docker images are tag plus digest (`docker buildx imagetools inspect <image>:<tag>`). Checkout keeps `persist-credentials: false`.
- **Smoke test** keeps `curl --retry-all-errors`: Docker's port proxy resets connections until uvicorn binds, so `--retry-connrefused` alone flakes.

# Changing code

**Where it goes:**

- `exercise_1/`: `analysis.ipynb` holds the narrative and calls `cleanup.py`, `compute.py`, `plot.py`, where the logic lives. After every change, Run All and save so committed outputs match the code: `uv run jupyter nbconvert --to notebook --execute --inplace exercise_1/analysis.ipynb` (needs the undistributed `signals_*.pkl` in `exercise_1/`, see README), then pre-commit (ruff formats notebook cells). Dead ends stay in, each under a markdown cell saying what was tried and why it was dropped: the assignment grades the decision trail. Here addition beats deletion.
- `models/*/*.json` ship the notebook's Q4 refit on all flights, which prints the exact coefficients. A refit moves all of: both model files, `ABC_MODEL` in `tests/conftest.py`, the expected fuel in `test_estimates_route_fuel`, `ARCHITECTURE.md` §6, and the README example result (rerun on compose).
- `src/`: the job processor service (exercise 2), imported as package `src` (`from src.config import Settings`, `python -m src.worker`), laid out as below. Design and decisions: `ARCHITECTURE.md`; read it before changing the service's shape.
- `scripts/`: dev tooling run against the service (`seed.py`: fake airline DEMO with a job in every status; `kind-smoke.sh`, `kind-dev.sh`: the chart on kind). `src/` holds only code the image ships; anything else lives here.

```
src/
  api.py             composition root: Settings → clients → repositories → services → FastAPI app
  config.py          Settings (pydantic-settings)
  schemas.py         pydantic models: FlightPlan, JobView, model file
  controllers/       FastAPI routers: parse request, call one service, map result or error to HTTP
  services/          business rules: tenants.py (registry), jobs.py (job queue: App, task, retry, status, identity), fuel.py (pipeline)
  repositories/      persistence: protocols.py (JobStore Protocol + JobRow), postgres.py, files.py (models)
  clients/           external I/O: weather.py, clock.py (Protocol + real implementation each)
  worker.py          worker process: build (tenant, weather, model checks) → run the queue's task
  migrate.py         one-shot: apply schema
  cleanup.py         one-shot: retry stalled jobs, purge old ones
  sql/schema.sql
  static/            index.html, style.css, app.js
tests/
  conftest.py        fakes for every seam (JobStore over Procrastinate's InMemoryConnector, weather, clock); app fixture built through api.py; run_workers drains the queue
  test_<feature>.py  one file per user-facing feature
deploy/              weather-stub/, helm/optifuel/
scripts/             seed.py, kind-smoke.sh, kind-dev.sh
docker-compose.yaml  local stack
```

- **Layers**: calls flow controller → service → repository or client, one direction. Controllers hold HTTP only, services hold every business rule and import no FastAPI, repositories hold SQL and file access only.
- **Tenant** scope: every event carries `airline`, and its model, config, and results are keyed by it. An unknown airline or a disabled aircraft type rejects the event with an explicit error; each tenant runs only its own model, with no default or shared fallback.
- Flight plans enter as pydantic models, validated at the boundary. `pickle` / `joblib` load only trusted artifacts: the provided datasets and models from the configured per-airline path.
- Config is one `pydantic-settings` class read at startup, the only place an environment variable is read. Credentials are `SecretStr`.
- **Dependency injection** by default: every service, repository, and client takes its dependencies as constructor arguments typed by a `Protocol`. `api.py` builds the real ones once at startup, next to the config, and controllers receive services through FastAPI `Depends`, so tests hand in fakes.

**Comments:** one or two lines carrying the why, the invariant, or the gotcha the code cannot show. Mark an intentional shortcut with a `Limitation:` comment stating its limit and upgrade path; docs record it the same way, as **Limitation:**.

**Docs:** `README.md` holds what to run (API, config, commands); `ARCHITECTURE.md` holds the design and why. Each fact lives in one of them. Short and plain: tables and one-line bullets, example numbers taken from a real run.

**Tests:**

- **End-to-end first**: drive the app over HTTP through `TestClient`, wired by `api.py`, with fakes only at the outer edge (repositories, clients). A job test submits with `POST /v1/jobs`, the fake queue runs the worker task inline, and `GET /v1/jobs/{id}` reads the outcome. A unit test is for pure logic whose edge cases HTTP cannot reach cheaply (fuel integration math).
- **Black box**: assert what a user observes: status code, response body, what the weather API was asked. A test survives any refactor that keeps behaviour; one that breaks on a rename or a moved function is testing implementation, and gets rewritten.
- Red first: the test fails, then the code turns it green. A bug fix lands with the test that failed first.
- Tests run offline. Fakes are small hand-written classes that satisfy the seam's `Protocol`, typed so ty flags them when the seam changes; they live as fixtures in `tests/conftest.py` and enter through `app.dependency_overrides`. The queue itself is not faked: tests run the real task on Procrastinate's `InMemoryConnector`, and `run_workers()` is the explicit "a worker claimed it" step after `POST`.
- Mocks need a reason: `unittest.mock`, `pytest-mock`, and `monkeypatch` of internals are a last resort for code no seam reaches, and every mock is one more copy of an interface to maintain. Refactor to a seam first; if a mock still lands, a comment names why the seam was impossible.
- Name tests by behaviour (`test_rejects_unknown_airline`). Variants of one behaviour are one `@pytest.mark.parametrize` list.
- Body is arrange / act / assert, with one blank line between the blocks as the only separator.
