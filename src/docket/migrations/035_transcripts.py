"""Migration 035 — meeting transcripts, event timelines, discrepancies.

Seven tables from docs/superpowers/specs/2026-10-05-meeting-transcripts-design.md
Section 1. `transcripts` is the per-meeting status machine; segments cascade
from it so a re-transcription is delete-and-replace. Speakers and
discrepancies key to `meeting_id`, not to segment ids, so manual work
survives a re-run. The resolved speaker name is deliberately not part of
`transcript_segments.search_vector` (speaker search is a join filter).
Word-level timestamps are not stored.
"""

from __future__ import annotations


SQL_UP = r"""
CREATE TABLE IF NOT EXISTS transcripts (
    id                     SERIAL PRIMARY KEY,
    meeting_id             INTEGER NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
    status                 TEXT NOT NULL CHECK (status IN (
                               'claimed', 'audio_fetched', 'transcribed', 'uploaded',
                               'speakers_resolved', 'events_extracted', 'compared',
                               'failed', 'needs_review', 'low_speech')),
    version                INTEGER NOT NULL DEFAULT 1,
    engine                 TEXT,
    asr_model              TEXT,
    diarization_model      TEXT,
    audio_duration_s       REAL,
    speech_ratio           REAL,
    word_count             INTEGER,
    producer_host          TEXT,
    claimed_at             TIMESTAMPTZ,
    uploaded_at            TIMESTAMPTZ,
    audio_sha256           TEXT,
    raw_output_path        TEXT,
    stage_attempts         INTEGER NOT NULL DEFAULT 0,
    last_error             TEXT,
    last_attempted_at      TIMESTAMPTZ,
    compare_skipped_reason TEXT,
    needs_review_reason    TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transcripts_status ON transcripts (status);

CREATE TABLE IF NOT EXISTS transcript_speakers (
    id                    SERIAL PRIMARY KEY,
    meeting_id            INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    cluster_label         TEXT NOT NULL,
    council_member_id     INTEGER REFERENCES council_members(id) ON DELETE SET NULL,
    display_name          TEXT,
    role                  TEXT CHECK (role IN ('council', 'mayor', 'clerk', 'attorney',
                                               'staff', 'public', 'unknown')),
    confidence            REAL,
    method                TEXT CHECK (method IN ('roll_call', 'addressed_by_chair',
                                                 'llm_inference', 'manual')),
    is_manual             BOOLEAN NOT NULL DEFAULT FALSE,
    embedding             REAL[],
    remapped_from_version INTEGER,
    needs_review          BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (meeting_id, cluster_label)
);

CREATE INDEX IF NOT EXISTS idx_transcript_speakers_member
    ON transcript_speakers (council_member_id);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id                BIGSERIAL PRIMARY KEY,
    transcript_id     INTEGER NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    seq               INTEGER NOT NULL,
    start_s           REAL NOT NULL,
    end_s             REAL NOT NULL,
    text              TEXT NOT NULL,
    cluster_label     TEXT,
    speaker_id        INTEGER REFERENCES transcript_speakers(id) ON DELETE SET NULL,
    agenda_item_id    INTEGER REFERENCES agenda_items(id) ON DELETE SET NULL,
    assignment_method TEXT CHECK (assignment_method IN ('index_point', 'event', 'manual')),
    avg_logprob       REAL,
    no_speech_prob    REAL,
    is_silence        BOOLEAN NOT NULL DEFAULT FALSE,
    search_vector     TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    UNIQUE (transcript_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_transcript_segments_search
    ON transcript_segments USING GIN (search_vector);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_trgm
    ON transcript_segments USING GIN (text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_item
    ON transcript_segments (agenda_item_id);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_speaker
    ON transcript_segments (speaker_id);

CREATE TABLE IF NOT EXISTS minutes_texts (
    id           SERIAL PRIMARY KEY,
    meeting_id   INTEGER NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
    source_url   TEXT,
    pdf_sha256   TEXT,
    text         TEXT NOT NULL,
    page_offsets JSONB NOT NULL DEFAULT '[]'::jsonb,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meeting_events (
    id               BIGSERIAL PRIMARY KEY,
    meeting_id       INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    source           TEXT NOT NULL CHECK (source IN ('transcript', 'minutes')),
    seq              INTEGER NOT NULL,
    event_type       TEXT NOT NULL CHECK (event_type IN (
                         'item_opened', 'item_deferred', 'consent_amendment', 'motion',
                         'second', 'amendment', 'vote', 'executive_session_motion',
                         'recusal', 'procedural_ruling', 'roll_call', 'recess',
                         'reconvene', 'adjourn', 'public_comment', 'statement')),
    scope            TEXT NOT NULL DEFAULT 'item' CHECK (scope IN ('item', 'consent_block', 'meeting')),
    agenda_item_refs INTEGER[] NOT NULL DEFAULT '{}',
    actor_member_id  INTEGER REFERENCES council_members(id) ON DELETE SET NULL,
    actor_text       TEXT,
    summary          TEXT NOT NULL,
    detail           JSONB NOT NULL DEFAULT '{}'::jsonb,
    start_s          REAL,
    page             INTEGER,
    char_offset      INTEGER,
    segment_id       BIGINT REFERENCES transcript_segments(id) ON DELETE SET NULL,
    prompt_version   INTEGER NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meeting_events_meeting
    ON meeting_events (meeting_id, source, seq);

CREATE TABLE IF NOT EXISTS minutes_discrepancies (
    id                    SERIAL PRIMARY KEY,
    meeting_id            INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    agenda_item_id        INTEGER REFERENCES agenda_items(id) ON DELETE SET NULL,
    category              TEXT NOT NULL CHECK (category IN (
                              'vote_outcome', 'omission', 'addition', 'wording',
                              'sequence', 'speaker')),
    severity              TEXT NOT NULL CHECK (severity IN ('material', 'minor')),
    title                 TEXT NOT NULL,
    description           TEXT NOT NULL,
    admin_title           TEXT,
    admin_description     TEXT,
    transcript_event_id   BIGINT REFERENCES meeting_events(id) ON DELETE SET NULL,
    minutes_event_id      BIGINT REFERENCES meeting_events(id) ON DELETE SET NULL,
    transcript_excerpt    TEXT,
    transcript_start_s    REAL,
    minutes_excerpt       TEXT,
    minutes_page          INTEGER,
    citation_match        TEXT NOT NULL DEFAULT 'missing'
                          CHECK (citation_match IN ('exact', 'fuzzy', 'missing')),
    confidence            REAL,
    origin                TEXT NOT NULL DEFAULT 'aligner'
                          CHECK (origin IN ('aligner', 'model_initiated')),
    review_state          TEXT NOT NULL DEFAULT 'proposed'
                          CHECK (review_state IN ('proposed', 'approved', 'rejected',
                                                  'dismissed_by_model', 'stale')),
    previous_review_state TEXT,
    reject_reason         TEXT,
    reviewed_at           TIMESTAMPTZ,
    reviewed_by           TEXT,
    review_note           TEXT,
    prompt_version        INTEGER NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT minutes_discrepancies_has_event
        CHECK (transcript_event_id IS NOT NULL OR minutes_event_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_minutes_discrepancies_review
    ON minutes_discrepancies (review_state, severity, meeting_id);

CREATE TABLE IF NOT EXISTS producer_heartbeats (
    host             TEXT PRIMARY KEY,
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_status      TEXT,
    last_meeting_id  INTEGER,
    producer_version TEXT
);
"""

SQL_DOWN = r"""
DROP TABLE IF EXISTS producer_heartbeats;
DROP TABLE IF EXISTS minutes_discrepancies;
DROP TABLE IF EXISTS meeting_events;
DROP TABLE IF EXISTS minutes_texts;
DROP TABLE IF EXISTS transcript_segments;
DROP TABLE IF EXISTS transcript_speakers;
DROP TABLE IF EXISTS transcripts;
"""
