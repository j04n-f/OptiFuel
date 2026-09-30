-- Applied by `python -m optifuel.migrate` after Procrastinate's schema; safe to re-run.
CREATE TABLE IF NOT EXISTS job_records (
    job_id       bigint PRIMARY KEY REFERENCES procrastinate_jobs (id) ON DELETE CASCADE,
    airline      text        NOT NULL,
    type         text        NOT NULL,
    flight_id    bigint      NOT NULL,
    plan_key     text        NOT NULL,
    submitted_at timestamptz NOT NULL,
    finished_at  timestamptz,
    result       jsonb,
    error        text
);
CREATE INDEX IF NOT EXISTS job_records_airline_submitted
    ON job_records (airline, submitted_at DESC);
CREATE INDEX IF NOT EXISTS job_records_plan ON job_records (airline, plan_key);
