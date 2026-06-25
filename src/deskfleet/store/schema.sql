-- DeskFleet durable record. Applied on every cold start; never destructive.

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id         TEXT PRIMARY KEY,
    -- Redacted body only. The raw ticket never leaves the request object.
    body              TEXT        NOT NULL,
    category          TEXT,
    decision          TEXT        NOT NULL,
    reply             TEXT,
    escalation_reason TEXT,
    latency_ms        INTEGER     NOT NULL DEFAULT 0,
    tokens_in         INTEGER     NOT NULL DEFAULT 0,
    tokens_out        INTEGER     NOT NULL DEFAULT 0,
    usd               NUMERIC(10, 6) NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The tool audit trail. Rejected off-allowlist calls are recorded, not discarded --
-- that row is exactly what a security reviewer comes looking for.
CREATE TABLE IF NOT EXISTS tool_calls (
    id             BIGSERIAL PRIMARY KEY,
    ticket_id      TEXT        NOT NULL,
    name           TEXT        NOT NULL,
    args_json      TEXT        NOT NULL,
    ok             BOOLEAN     NOT NULL,
    rejected       BOOLEAN     NOT NULL DEFAULT FALSE,
    result_summary TEXT        NOT NULL DEFAULT '',
    latency_ms     INTEGER     NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS escalations (
    id              BIGSERIAL PRIMARY KEY,
    ticket_id       TEXT        NOT NULL,
    reason          TEXT        NOT NULL,
    detail          TEXT,
    -- The best draft seen before retries ran out; the human inherits work already paid for.
    best_draft      TEXT,
    tool_calls_json TEXT        NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets (created_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ticket_id ON tool_calls (ticket_id);
