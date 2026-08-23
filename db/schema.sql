-- VendorEdge MVP schema — simplified from VE-403B for the lean two-question-type launch.
-- Full multi-tenant / knowledge-item / corroboration complexity deferred per the lean roadmap;
-- this covers exactly what Ask -> Evidence -> Commercial Position -> Feedback needs to run for real.
--
-- IMPORTANT: this file is now designed to be run safely, repeatedly, on ANY
-- Postgres provider -- not just via Docker's local auto-init trick. Every
-- statement uses IF NOT EXISTS / existence checks, and no statement hardcodes
-- a specific database name (real hosting providers assign their own names,
-- e.g. Render generates something like "vendoredge_xk2p"). The application
-- runs this whole file itself on every startup (see app/seed.py) -- this is
-- what makes deployment to a brand new host require zero manual database
-- commands from a non-technical founder.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS organisations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    primary_currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    -- Real, enforced usage cap -- previously the "15 decisions/month" on the
    -- pricing page was pure text with zero backend enforcement, meaning
    -- anyone could ask unlimited questions for free, at real Anthropic API
    -- cost to the founder. Defaults to the free tier; manually raised per
    -- organisation once a real payment is received, until an actual billing
    -- system exists -- deliberately not building payment infrastructure
    -- speculatively before a single paying customer exists.
    monthly_decision_limit INTEGER NOT NULL DEFAULT 3,
    -- Usage is reserved atomically before any paid provider call. Counting
    -- decisions afterwards is race-prone and lets concurrent requests exceed
    -- the commercial limit.
    monthly_usage_period DATE NOT NULL DEFAULT date_trunc('month', now())::date,
    monthly_decisions_used INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organisation_id, email)
);

-- Invitations are bearer secrets, not sessions. Only a SHA-256 token hash is
-- stored, and each token is single-use with a short expiry.
CREATE TABLE IF NOT EXISTS workspace_invites (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    invited_by_user_id UUID NOT NULL REFERENCES users(id),
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    accepted_by_user_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS commercial_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    created_by_user_id UUID NOT NULL REFERENCES users(id),
    raw_question TEXT NOT NULL,
    classified_content_type VARCHAR(30)
        CHECK (classified_content_type IN ('price_increase', 'quote_comparison')),
    classified_decision_type VARCHAR(25)
        CHECK (classified_decision_type IN ('optimization', 'constraint_satisfaction')),
    status VARCHAR(30) NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'classifying', 'awaiting_user_input',
                           'reasoning', 'completed', 'provider_unavailable')),
    missing_inputs_requested JSONB,
    user_supplied_inputs JSONB,
    numeric_facts JSONB DEFAULT '{}',
    commercial_position JSONB,
    -- Quality Gate Guarantee #1 -- Evidence Provenance. Without this,
    -- "where did this number come from" is only answerable DURING the
    -- live request that produced it -- NormalizedEvidence.provenance
    -- existed only in memory and was discarded once the response was
    -- sent. This persists it, so any completed decision can be queried
    -- for real, structured provenance at any later point, not just the
    -- moment it was created.
    evidence_provenance JSONB,
    -- Async reasoning hardening: real timestamp for when this specific
    -- case entered 'reasoning', used to detect genuine staleness (a
    -- worker crash mid-reasoning, not just a slow-but-alive process) so
    -- a stuck case can become safely retriable instead of stuck forever.
    reasoning_started_at TIMESTAMPTZ,
    -- Attempt fencing (job lifecycle hardening): current_attempt_id is the
    -- ONLY attempt permitted to write to this row. Every write associated
    -- with reasoning -- heartbeat AND final result -- is conditioned on
    -- matching this value. An old, superseded attempt's writes silently
    -- fail (zero rows affected), no matter how late it wakes up. This is
    -- what makes duplicate execution harmless rather than merely unlikely.
    current_attempt_id UUID,
    -- Heartbeat: last_heartbeat_at is genuine liveness evidence, updated
    -- by a ticker thread DURING a blocking LLM/search call, not just at
    -- stage boundaries -- a 15-minute call stays provably alive
    -- throughout. current_stage is the real, current phase, used only
    -- for an honest user-facing message, never exposed as raw internal
    -- state.
    last_heartbeat_at TIMESTAMPTZ,
    current_stage TEXT,
    -- Links a follow-up decision to the case it continues -- nullable,
    -- most decisions have no parent. The parent's commercial_position stays
    -- immutable (protected by the tamper-prevention trigger below); a
    -- follow-up is always a NEW row, never an edit to the original.
    parent_decision_id UUID REFERENCES commercial_decisions(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- Durable, database-backed work records. A web request may enqueue work, but
-- the record (not an in-memory BackgroundTask) is the source of truth and is
-- recoverable after a process restart.
CREATE TABLE IF NOT EXISTS reasoning_jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    commercial_decision_id UUID NOT NULL UNIQUE REFERENCES commercial_decisions(id) ON DELETE CASCADE,
    organisation_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    job_kind VARCHAR(32) NOT NULL CHECK (job_kind IN ('specialist', 'generic_triage')),
    status VARCHAR(24) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'retry_scheduled', 'completed', 'failed', 'cancelled', 'timed_out')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    timeout_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    last_error_code VARCHAR(80),
    last_error_detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reasoning_jobs_claim ON reasoning_jobs(status, available_at);
ALTER TABLE commercial_decisions ADD COLUMN IF NOT EXISTS parent_decision_id UUID REFERENCES commercial_decisions(id);
ALTER TABLE commercial_decisions ADD COLUMN IF NOT EXISTS evidence_provenance JSONB;
ALTER TABLE commercial_decisions ADD COLUMN IF NOT EXISTS reasoning_started_at TIMESTAMPTZ;
ALTER TABLE commercial_decisions ADD COLUMN IF NOT EXISTS current_attempt_id UUID;
ALTER TABLE commercial_decisions ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ;
ALTER TABLE commercial_decisions ADD COLUMN IF NOT EXISTS current_stage TEXT;
CREATE INDEX IF NOT EXISTS idx_cd_parent ON commercial_decisions(parent_decision_id);

CREATE OR REPLACE FUNCTION fn_prevent_completed_position_tampering()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status = 'completed' AND NEW.commercial_position IS DISTINCT FROM OLD.commercial_position THEN
        RAISE EXCEPTION 'commercial_position cannot be modified after completion';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_tampering ON commercial_decisions;
CREATE TRIGGER trg_prevent_tampering
    BEFORE UPDATE ON commercial_decisions
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_completed_position_tampering();

CREATE TABLE IF NOT EXISTS decision_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    commercial_decision_id UUID NOT NULL REFERENCES commercial_decisions(id) ON DELETE CASCADE,
    submitted_by_user_id UUID NOT NULL REFERENCES users(id),
    decision_alignment VARCHAR(20) NOT NULL
        CHECK (decision_alignment IN ('followed', 'modified', 'different_direction')),
    outcome_description TEXT NOT NULL,
    validation_verdict VARCHAR(35) NOT NULL
        CHECK (validation_verdict IN ('reasoning_held', 'reasoning_wrong_bad_assumption',
                                        'reasoning_wrong_bad_execution', 'ambiguous_unresolved')),
    unexpected_insight TEXT,
    outcome_recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE decision_feedback ADD COLUMN IF NOT EXISTS unexpected_insight TEXT;
-- R24: structured realized financial impact. Free-text outcomes remain narrative only.
ALTER TABLE decision_feedback ADD COLUMN IF NOT EXISTS actual_financial_impact_usd NUMERIC;
ALTER TABLE decision_feedback ADD COLUMN IF NOT EXISTS actual_measurement_basis VARCHAR(160);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'decision_feedback_actual_impact_reasonable') THEN
        ALTER TABLE decision_feedback ADD CONSTRAINT decision_feedback_actual_impact_reasonable
            CHECK (actual_financial_impact_usd IS NULL OR actual_financial_impact_usd BETWEEN -1000000000000 AND 1000000000000);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS pilot_experience_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    commercial_decision_id UUID NOT NULL REFERENCES commercial_decisions(id) ON DELETE CASCADE,
    submitted_by_user_id UUID NOT NULL REFERENCES users(id),
    ease_of_use VARCHAR(20) NOT NULL CHECK (ease_of_use IN ('very_easy','easy','okay','difficult','very_difficult')),
    trust_level VARCHAR(10) NOT NULL CHECK (trust_level IN ('high','medium','low')),
    time_saved VARCHAR(20) NOT NULL CHECK (time_saved IN ('significant','some','none','more_time')),
    would_use_again BOOLEAN NOT NULL,
    most_valuable TEXT NOT NULL CHECK (length(trim(most_valuable)) > 0),
    missing_or_frustrating TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (commercial_decision_id, submitted_by_user_id)
);
ALTER TABLE pilot_experience_feedback ADD COLUMN IF NOT EXISTS missing_or_frustrating TEXT;

CREATE TABLE IF NOT EXISTS interest_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organisation_id UUID REFERENCES organisations(id) ON DELETE CASCADE,
    feature VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE interest_signals ADD COLUMN IF NOT EXISTS organisation_id UUID REFERENCES organisations(id) ON DELETE CASCADE;

-- AI Reliability Dashboard: every time a deterministic extraction fallback
-- (region, annual spend, requested percent, freight) fires -- meaning the
-- model's own extraction missed something a reliable pattern match caught
-- instead. Real columns, not a single encoded string, specifically so
-- fallback_type can be cross-tabulated against content_type and
-- model_version cleanly in SQL, per real usage findings: some fallbacks
-- fire far more often on one case type than another, and tracking model
-- version shows directly when a model upgrade makes a given fallback
-- unnecessary, simplifying the code over time with real evidence instead
-- of a guess.
CREATE TABLE IF NOT EXISTS fallback_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organisation_id UUID REFERENCES organisations(id) ON DELETE CASCADE,
    fallback_type VARCHAR(50) NOT NULL,
    content_type VARCHAR(50),
    model_version VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- NormalizedEvidence migration: distinguishes a simple "fallback caught
-- something the model missed" event from a genuine "LLM and fallback
-- independently disagreed" conflict -- both real, both worth tracking,
-- but a conflict is a distinct and arguably more interesting signal
-- (it might mean the fallback pattern itself is too naive for that
-- sentence shape, not just that the model missed something).
ALTER TABLE fallback_events ADD COLUMN IF NOT EXISTS is_conflict BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE fallback_events ADD COLUMN IF NOT EXISTS organisation_id UUID REFERENCES organisations(id) ON DELETE CASCADE;

-- Pilot demand-capture: only created when a real user takes the real action
-- of clicking "Notify me" AND completing the short follow-up. The raw click
-- itself (before this form) is logged separately via interest_signals,
-- since the click alone is already a real signal per the stated principle
-- -- this table captures the richer, optional follow-through.
CREATE TABLE IF NOT EXISTS pilot_leads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organisation_id UUID REFERENCES organisations(id),
    email VARCHAR(255) NOT NULL,
    name VARCHAR(200),
    linkedin VARCHAR(300),
    next_case_category VARCHAR(50) NOT NULL,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- General, always-available feedback -- deliberately not tied to any
-- specific moment or question, unlike the quick-feedback and outcome
-- fields. Catches anything that doesn't fit those specific prompts.
CREATE TABLE IF NOT EXISTS general_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organisation_id UUID REFERENCES organisations(id),
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE organisations ADD COLUMN IF NOT EXISTS monthly_decision_limit INTEGER NOT NULL DEFAULT 3;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS monthly_usage_period DATE NOT NULL DEFAULT date_trunc('month', now())::date;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS monthly_decisions_used INTEGER NOT NULL DEFAULT 0;
-- The line above only takes effect for a genuinely NEW column -- since this
-- column already exists on any already-deployed database, this explicit
-- ALTER is what actually changes the default going forward, matching the
-- real pilot plan (3 free cases). Existing organisations already created
-- keep whatever limit they were already given -- this only affects new
-- workspaces created from this point on.
ALTER TABLE organisations ALTER COLUMN monthly_decision_limit SET DEFAULT 3;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_users ON users;
CREATE POLICY org_isolation_users ON users
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

ALTER TABLE organisations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organisations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_organisations ON organisations;
CREATE POLICY org_isolation_organisations ON organisations
    USING (id = current_setting('app.current_org_id')::UUID);

ALTER TABLE workspace_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspace_invites FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_workspace_invites ON workspace_invites;
CREATE POLICY org_isolation_workspace_invites ON workspace_invites
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

ALTER TABLE commercial_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE commercial_decisions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_cd ON commercial_decisions;
CREATE POLICY org_isolation_cd ON commercial_decisions
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

ALTER TABLE reasoning_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE reasoning_jobs FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_reasoning_jobs ON reasoning_jobs;
CREATE POLICY org_isolation_reasoning_jobs ON reasoning_jobs
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

-- CRITICAL: the application must NEVER connect as a PostgreSQL SUPERUSER.
-- FORCE ROW LEVEL SECURITY is applied below so even a table owner is still
-- subject to tenant policies. Where the hosting platform supports separate
-- migration credentials, use them; the application role should otherwise have
-- only the CRUD privileges required by the running service.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'vendoredge_app') THEN
        EXECUTE format('GRANT CONNECT ON DATABASE %I TO vendoredge_app', current_database());
        GRANT USAGE ON SCHEMA public TO vendoredge_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO vendoredge_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vendoredge_app;
    END IF;
END
$$;

ALTER TABLE interest_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE interest_signals FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_interest_signals ON interest_signals;
CREATE POLICY org_isolation_interest_signals ON interest_signals
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

ALTER TABLE fallback_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE fallback_events FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_fallback_events ON fallback_events;
CREATE POLICY org_isolation_fallback_events ON fallback_events
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

ALTER TABLE pilot_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE pilot_leads FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_pilot_leads ON pilot_leads;
CREATE POLICY org_isolation_pilot_leads ON pilot_leads
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

ALTER TABLE general_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE general_feedback FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_general_feedback ON general_feedback;
CREATE POLICY org_isolation_general_feedback ON general_feedback
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

CREATE INDEX IF NOT EXISTS idx_cd_organisation_id ON commercial_decisions(organisation_id);
CREATE INDEX IF NOT EXISTS idx_cd_status ON commercial_decisions(status);
CREATE INDEX IF NOT EXISTS idx_invites_token_hash ON workspace_invites(token_hash);
CREATE INDEX IF NOT EXISTS idx_invites_org ON workspace_invites(organisation_id);
CREATE INDEX IF NOT EXISTS idx_interest_org ON interest_signals(organisation_id);
CREATE INDEX IF NOT EXISTS idx_fallback_org ON fallback_events(organisation_id);

ALTER TABLE pilot_experience_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE pilot_experience_feedback FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_pef ON pilot_experience_feedback;
CREATE POLICY org_isolation_pef ON pilot_experience_feedback
    USING (EXISTS (
        SELECT 1 FROM commercial_decisions cd
        WHERE cd.id = pilot_experience_feedback.commercial_decision_id
        AND cd.organisation_id = current_setting('app.current_org_id')::UUID
    ));

ALTER TABLE decision_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_feedback FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_df ON decision_feedback;
CREATE POLICY org_isolation_df ON decision_feedback
    USING (EXISTS (
        SELECT 1 FROM commercial_decisions cd
        WHERE cd.id = decision_feedback.commercial_decision_id
        AND cd.organisation_id = current_setting('app.current_org_id')::UUID
    ));
