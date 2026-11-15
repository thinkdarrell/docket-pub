-- scripts/sql/create_transcriber_role.sql
-- Run once per database as the app owner:
--   psql "$PGURL" -v password="$(openssl rand -hex 32)" -f scripts/sql/create_transcriber_role.sql
-- Then put the URL in transcriber/.env as
--   TRANSCRIBER_DATABASE_URL=postgresql://transcriber:<password>@<host>:<port>/railway?sslmode=require
-- The role writes only the producer's tables and reads the reference
-- tables the claim query joins. It also reads meeting_videos (the YouTube
-- recordings attached to a meeting) and writes meeting_video_alignments
-- (where each recording sits on its Granicus clip's clock, one row per
-- confirmed stretch) with DELETE, because a re-measure replaces a
-- recording's stretch rows. It never sees votes, AI tables, or the review
-- tables.
--
-- A role created before migration 042 lacks the last two GRANT statements
-- of this file (meeting_videos and meeting_video_alignments); the owner
-- runs those two alone, since CREATE ROLE refuses a role that exists. A
-- role created between migrations 042 and 046 lacks only the DELETE, which
-- the owner grants alone with
--   GRANT DELETE ON meeting_video_alignments TO transcriber;

CREATE ROLE transcriber LOGIN PASSWORD :'password';

DO $$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO transcriber', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO transcriber;

GRANT SELECT ON meetings, municipalities, council_members, agenda_items TO transcriber;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON transcripts, transcript_segments, transcript_speakers, producer_heartbeats
    TO transcriber;

GRANT USAGE, SELECT
    ON SEQUENCE transcripts_id_seq, transcript_segments_id_seq, transcript_speakers_id_seq
    TO transcriber;

GRANT SELECT ON meeting_videos TO transcriber;

GRANT SELECT, INSERT, UPDATE, DELETE ON meeting_video_alignments TO transcriber;
