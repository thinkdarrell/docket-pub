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
