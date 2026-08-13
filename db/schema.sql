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

CREATE TABLE IF NOT EXISTS interest_signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    feature VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

ALTER TABLE commercial_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE commercial_decisions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_cd ON commercial_decisions;
CREATE POLICY org_isolation_cd ON commercial_decisions
    USING (organisation_id = current_setting('app.current_org_id')::UUID);

-- CRITICAL: the application must NEVER connect to the database as its
-- superuser/owner account -- discovered via a real, live test during MVP
-- build. Role created automatically; uses current_database() instead of a
-- hardcoded name so this works on any hosting provider's auto-named database.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vendoredge_app') THEN
        CREATE ROLE vendoredge_app LOGIN PASSWORD 'change_this_before_production';
    END IF;
END
$$;
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO vendoredge_app', current_database());
END
$$;
GRANT USAGE ON SCHEMA public TO vendoredge_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO vendoredge_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vendoredge_app;

CREATE INDEX IF NOT EXISTS idx_cd_organisation_id ON commercial_decisions(organisation_id);
CREATE INDEX IF NOT EXISTS idx_cd_status ON commercial_decisions(status);

ALTER TABLE decision_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_feedback FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_df ON decision_feedback;
CREATE POLICY org_isolation_df ON decision_feedback
    USING (EXISTS (
        SELECT 1 FROM commercial_decisions cd
        WHERE cd.id = decision_feedback.commercial_decision_id
        AND cd.organisation_id = current_setting('app.current_org_id')::UUID
    ));
