"""Configuration — reads from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://docket:docket_dev@localhost:5432/docket_db",
)

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
