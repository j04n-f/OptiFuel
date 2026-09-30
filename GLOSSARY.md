# OptiFuel

Airlines submit flight plans; OptiFuel estimates each route's fuel with that airline's own model
and lets the airline track the outcome.

## Language

### Tenancy

**Tenant**:
An airline that OptiFuel is configured to serve, identified by its airline code. Every plan, job,
model and queue belongs to exactly one tenant.
_Avoid_: customer, client, account

**Tenant registry**:
The configured set of tenants and what each one is allowed: enabled aircraft types and the model
version it estimates with. The single answer to "is this airline known, and may it do this?".
_Avoid_: tenants config, settings

**Airline code**:
The short code (`ABC`) that names a tenant everywhere: on plans, jobs, models and queues.

### Plans and estimates

**Flight plan**:
The route an airline intends to fly: ordered waypoints, each with airspeed and altitude, plus
aircraft type, registration, flight id and an optional departure time.
_Avoid_: payload, event

**Fuel model**:
A tenant's fitted fuel-flow function, with the version it was fitted under and the envelope it is
valid in.
_Avoid_: the model, ML model

**Model envelope**:
The airspeed and altitude ranges a fuel model was fitted on. A waypoint outside it cannot be
estimated; the job fails rather than extrapolate.

**Fuel estimate**:
The outcome of a job: total fuel, distance and duration for a flight plan, with the model version
that produced it.
_Avoid_: result, prediction

### Jobs

**Job**:
One request to estimate a flight plan for a tenant. It is queued, runs once a worker claims it, and
ends succeeded or failed; a tenant sees only its own jobs.
_Avoid_: task, event, request

**Job queue**:
Where jobs wait and are claimed, one queue per tenant, and the source of a job's status and attempt
count.
_Avoid_: broker, task queue

**Worker**:
A process bound to one tenant that claims that tenant's jobs and runs them with that tenant's fuel
model only.

**Plan key**:
The identity of a flight plan as submitted, so the same plan sent twice is recognised as the same
plan.

**Duplicate submission**:
A flight plan submitted while an earlier job for the same plan key is still queued. It returns
the queued job; once that job has been claimed, the same plan makes a new job.
_Avoid_: idempotent request, replay

**Transient failure**:
An attempt that failed for a reason a later attempt can clear: the weather source or the store was
unreachable. The job is retried with backoff, a limited number of times.

**Permanent failure**:
An attempt that failed for a reason retrying cannot fix: a waypoint outside the model envelope,
non-positive ground speed, a malformed weather reply. The job fails at once.

**Stalled job**:
A running job whose worker stopped reporting; it is returned to the queue for another worker.
_Avoid_: orphaned job, zombie
