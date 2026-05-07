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
