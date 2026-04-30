"""Initial schema — multi-city municipal meeting platform."""

SQL_UP = """
-- Municipality registry
CREATE TABLE municipalities (
    id              SERIAL PRIMARY KEY,
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'AL',
    county          TEXT,
    adapter_class   TEXT NOT NULL,
    adapter_config  JSONB DEFAULT '{}',
    council_type    TEXT,  -- 'district' | 'at_large' | 'mixed'
    timezone        TEXT NOT NULL DEFAULT 'America/Chicago',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Districts / wards
CREATE TABLE districts (
    id              SERIAL PRIMARY KEY,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id),
    name            TEXT NOT NULL,
    number          INTEGER,
    UNIQUE(municipality_id, name)
);

-- Council members
CREATE TABLE council_members (
    id              SERIAL PRIMARY KEY,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id),
    district_id     INTEGER REFERENCES districts(id),
    name            TEXT NOT NULL,
    term_start      DATE,
    term_end        DATE,
    email           TEXT,
    photo_url       TEXT,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Meetings
CREATE TABLE meetings (
    id              SERIAL PRIMARY KEY,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id),
    external_id     TEXT,
    title           TEXT NOT NULL,
    meeting_date    DATE,
    meeting_type    TEXT,  -- 'council' | 'work_session' | 'bza' | 'planning' | 'special'
    agenda_url      TEXT,
    minutes_url     TEXT,
    video_url       TEXT,
    source_url      TEXT,
    search_vector   TSVECTOR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(municipality_id, external_id)
);

CREATE INDEX idx_meetings_date ON meetings(meeting_date DESC);
CREATE INDEX idx_meetings_municipality ON meetings(municipality_id);
CREATE INDEX idx_meetings_search ON meetings USING GIN(search_vector);

-- Auto-update search vector on meetings
CREATE OR REPLACE FUNCTION meetings_search_update() RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', COALESCE(NEW.title, ''));
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER meetings_search_trigger
    BEFORE INSERT OR UPDATE ON meetings
    FOR EACH ROW EXECUTE FUNCTION meetings_search_update();

-- Agenda items
CREATE TABLE agenda_items (
    id                      SERIAL PRIMARY KEY,
    meeting_id              INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    external_id             TEXT,
    item_number             TEXT,
    title                   TEXT NOT NULL,
    description             TEXT,
    section                 TEXT,
    is_consent              BOOLEAN NOT NULL DEFAULT FALSE,
    sponsor                 TEXT,
    dollars_amount          NUMERIC(15, 2),
    significance_score      REAL,       -- 0-10
    consent_placement_score REAL,       -- 0-10
    search_vector           TSVECTOR,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(meeting_id, external_id)
);

CREATE INDEX idx_agenda_items_meeting ON agenda_items(meeting_id);
CREATE INDEX idx_agenda_items_consent ON agenda_items(is_consent) WHERE is_consent = TRUE;
CREATE INDEX idx_agenda_items_search ON agenda_items USING GIN(search_vector);

-- Auto-update search vector on agenda_items
CREATE OR REPLACE FUNCTION agenda_items_search_update() RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('english',
        COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.description, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER agenda_items_search_trigger
    BEFORE INSERT OR UPDATE ON agenda_items
    FOR EACH ROW EXECUTE FUNCTION agenda_items_search_update();

-- Votes
CREATE TABLE votes (
    id              SERIAL PRIMARY KEY,
    meeting_id      INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    agenda_item_id  INTEGER REFERENCES agenda_items(id) ON DELETE SET NULL,
    external_id     TEXT,
    result          TEXT NOT NULL,  -- 'passed' | 'failed' | 'tabled'
    yeas            INTEGER,
    nays            INTEGER,
    abstentions     INTEGER,
    source          TEXT NOT NULL,  -- 'video_ocr' | 'minutes_text' | 'api' | 'manual'
    confidence      TEXT NOT NULL DEFAULT 'high',  -- 'high' | 'medium' | 'low'
    header_result   TEXT,
    needs_review    BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason   TEXT,
    video_timestamp REAL,
    raw_text        TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_votes_meeting ON votes(meeting_id);
CREATE INDEX idx_votes_review ON votes(needs_review) WHERE needs_review = TRUE;

-- Individual member votes
CREATE TABLE member_votes (
    id                  SERIAL PRIMARY KEY,
    vote_id             INTEGER NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
    council_member_id   INTEGER REFERENCES council_members(id),
    member_name         TEXT NOT NULL,
    position            TEXT NOT NULL  -- 'yea' | 'nay' | 'abstain' | 'absent'
);

CREATE INDEX idx_member_votes_vote ON member_votes(vote_id);
CREATE INDEX idx_member_votes_member ON member_votes(council_member_id);

-- Source freshness checks
CREATE TABLE source_checks (
    id              SERIAL PRIMARY KEY,
    municipality_id INTEGER NOT NULL REFERENCES municipalities(id),
    check_type      TEXT NOT NULL,  -- 'meetings' | 'minutes' | 'roster'
    last_checked    TIMESTAMPTZ,
    last_found      TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'pending',  -- 'ok' | 'error' | 'changed' | 'pending'
    error_message   TEXT,
    auto_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(municipality_id, check_type)
);

-- Processing status per meeting (tracks pipeline stages)
CREATE TABLE processing_status (
    id                      SERIAL PRIMARY KEY,
    meeting_id              INTEGER NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
    agenda_items_scraped    BOOLEAN NOT NULL DEFAULT FALSE,
    agenda_pdf_downloaded   BOOLEAN NOT NULL DEFAULT FALSE,
    votes_scanned           BOOLEAN NOT NULL DEFAULT FALSE,
    votes_matched           BOOLEAN NOT NULL DEFAULT FALSE,
    minutes_checked         BOOLEAN NOT NULL DEFAULT FALSE,
    last_processed          TIMESTAMPTZ,
    review_status           TEXT DEFAULT 'pending'  -- 'pending' | 'reviewed' | 'published'
);

-- Seed Birmingham as the first municipality
INSERT INTO municipalities (slug, name, state, county, adapter_class, adapter_config, council_type)
VALUES (
    'birmingham',
    'Birmingham',
    'AL',
    'Jefferson',
    'GranicusAdapter',
    '{"base_url": "https://bhamal.granicus.com", "view_id": 2}',
    'district'
);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS processing_status CASCADE;
DROP TABLE IF EXISTS source_checks CASCADE;
DROP TABLE IF EXISTS member_votes CASCADE;
DROP TABLE IF EXISTS votes CASCADE;
DROP TABLE IF EXISTS agenda_items CASCADE;
DROP TABLE IF EXISTS meetings CASCADE;
DROP TABLE IF EXISTS council_members CASCADE;
DROP TABLE IF EXISTS districts CASCADE;
DROP TABLE IF EXISTS municipalities CASCADE;
DROP FUNCTION IF EXISTS meetings_search_update CASCADE;
DROP FUNCTION IF EXISTS agenda_items_search_update CASCADE;
"""
