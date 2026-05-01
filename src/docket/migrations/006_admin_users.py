"""Admin users table for session-based authentication."""

SQL_UP = """
CREATE TABLE admin_users (
    id              SERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SQL_DOWN = """
DROP TABLE IF EXISTS admin_users CASCADE;
"""
