"""Configuration — reads from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://docket:docket_dev@localhost:5432/docket_db",
)

# Timezone the cron worker (src/docket/worker/scheduler.py) registers its
# jobs in. Every task time in docs/runbooks/cron-worker.md is in this zone.
WORKER_TIMEZONE: str = os.environ.get("WORKER_TIMEZONE", "America/Chicago")

SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

DOMAIN_NAME: str = os.environ.get("DOMAIN_NAME", "docket.pub")

FLASK_ENV: str = os.environ.get("FLASK_ENV", "development")

# Admin contact email — surfaced in citizen-facing templates as a
# `mailto:` target for "report missing data" links (decision #77 retired
# the `data_issue_reports` schema in favor of email-based reporting).
ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "admin@docket.pub")

# AI pipeline (summaries + scoring)
ANTHROPIC_API_KEY: str | None = os.environ.get("ANTHROPIC_API_KEY")
AI_ITEM_MODEL: str = os.environ.get("AI_ITEM_MODEL", "claude-haiku-4-5-20251001")
AI_MEETING_MODEL: str = os.environ.get("AI_MEETING_MODEL", "claude-sonnet-4-6")
AI_DAILY_BUDGET_USD: float = float(os.environ.get("AI_DAILY_BUDGET_USD", "10"))
AI_MAX_BATCH_SIZE: int = int(os.environ.get("AI_MAX_BATCH_SIZE", "200"))
AI_ITEM_DEBOUNCE_MINUTES: int = int(os.environ.get("AI_ITEM_DEBOUNCE_MINUTES", "5"))

# Blog (see docs/superpowers/specs/2026-06-02-blog-design.md)
BLOG_CONTENT_ROOT = os.environ.get("BLOG_CONTENT_ROOT", "content/blog")
BLOG_AUTHORS_YAML = os.environ.get("BLOG_AUTHORS_YAML", "config/blog_authors.yaml")
BLOG_PREVIEW_TOKEN = os.environ.get("BLOG_PREVIEW_TOKEN", "")

# YouTube Data API v3 key for the youtube_ingest task and
# scripts/backfill_youtube_meetings.py; unset, both read nothing
# (plans/active/youtube-council-channel.md, M4).
YOUTUBE_API_KEY: str | None = os.environ.get("YOUTUBE_API_KEY")

# Transcripts: meetings dated before this have no transcript and are not data
# debt until a later backfill is approved (current-council cutoff).
TRANSCRIPT_BACKFILL_SINCE: str = os.environ.get("TRANSCRIPT_BACKFILL_SINCE", "2025-10-28")

# Decision #45 + plan §FINAL-3: the IMPACT_FIRST_ENABLED flag gates the
# v3 worker path. When False (default), the worker runs the legacy v2
# pipeline (Haiku item summaries + Sonnet meeting executives). When
# True, the items task uses pipeline.process_item (Wave 0 → Stage 1 →
# 2 → 2.5 → reconcile → atomic commit + on-write badges). Meeting
# summaries continue to use v2 until decision #93 / Phase 2 SMART_BREVITY_UI
# wires the citizen rendering switch.
IMPACT_FIRST_ENABLED: bool = (
    os.environ.get("IMPACT_FIRST_ENABLED", "false").lower() == "true"
)

# Transcript pipeline (spec 2026-10-05 Sections 3-4; plan 2026-10-10).
# Sonnet 5.5 resolves speakers and extracts events; Opus 5.5 judges and
# hunts discrepancies. Haiku is an A/B experiment, never a default here.
AI_TRANSCRIPT_SPEAKER_MODEL: str = os.environ.get("AI_TRANSCRIPT_SPEAKER_MODEL", "claude-sonnet-5-5")
AI_TRANSCRIPT_EVENTS_MODEL: str = os.environ.get("AI_TRANSCRIPT_EVENTS_MODEL", "claude-sonnet-5-5")
AI_TRANSCRIPT_COMPARE_MODEL: str = os.environ.get("AI_TRANSCRIPT_COMPARE_MODEL", "claude-opus-5-5")
AI_TRANSCRIPT_AB_MODEL: str = os.environ.get("AI_TRANSCRIPT_AB_MODEL", "claude-haiku-4-5-20251001")
# Guards against runaway cost from a bad input, not against long meetings:
# a twelve-hour hearing plus a 300-page packet is about 300K tokens.
TRANSCRIPT_TOKEN_CEILING: int = int(os.environ.get("TRANSCRIPT_TOKEN_CEILING", "500000"))
# More candidates than this usually means a timestamp offset, not 40 problems.
TRANSCRIPT_CANDIDATE_CAP: int = int(os.environ.get("TRANSCRIPT_CANDIDATE_CAP", "40"))
TRANSCRIPT_PER_TICK: int = int(os.environ.get("TRANSCRIPT_PER_TICK", "5"))
# Granicus junk clips (a 6-minute mic check had 24 words) get transcribed;
# anything under this many words is not a meeting and gets no LLM call.
TRANSCRIPT_MIN_WORDS: int = int(os.environ.get("TRANSCRIPT_MIN_WORDS", "300"))
# Outbound alert webhook (Slack or Discord incoming webhook). Unset = silent.
ALERT_WEBHOOK_URL: str | None = os.environ.get("ALERT_WEBHOOK_URL") or None
