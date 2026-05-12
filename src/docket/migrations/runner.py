"""Migration runner for PostgreSQL.

Usage:
    python -m docket.migrations.runner           # apply pending migrations
    python -m docket.migrations.runner --status   # show migration status
    python -m docket.migrations.runner --down 1   # rollback migration 1
"""

from __future__ import annotations

import argparse
import importlib

from docket.db import db

MIGRATIONS = [
    "docket.migrations.001_initial",
    "docket.migrations.002_seed_cities",
    "docket.migrations.003_add_topic",
    "docket.migrations.004_expand_meeting_types",
    "docket.migrations.005_seed_council_rosters",
    "docket.migrations.006_admin_users",
    "docket.migrations.007_council_terms_and_backfill",
    "docket.migrations.008_vote_matching_support",
    "docket.migrations.009_vote_agenda_items",
    "docket.migrations.010_backfill_vote_agenda_items",
    "docket.migrations.011_drop_deprecated_vote_columns",
    "docket.migrations.012_ai_summaries_and_scoring",
    "docket.migrations.013_impact_first_refactor",
    "docket.migrations.015_search_vector_v3",
    "docket.migrations.016_relax_audit_fk",
    "docket.migrations.018_ai_batches_ingested_at",
    "docket.migrations.020_raise_headline_caps",
    "docket.migrations.021_badge_status_column",
    "docket.migrations.022_badge_mv_status_filter",
    "docket.migrations.023_processing_status_withdrawn",
    "docket.migrations.024_category_landing_v1",
]


def ensure_schema_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name    TEXT NOT NULL,
                applied TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
    conn.commit()


def applied_versions(conn) -> set[int]:
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        return {row[0] for row in cur.fetchall()}


def apply_migrations(conn) -> None:
    ensure_schema_table(conn)
    applied = applied_versions(conn)

    for module_path in MIGRATIONS:
        parts = module_path.rsplit(".", 1)[-1]
        version = int(parts.split("_")[0])

        if version in applied:
            continue

        mod = importlib.import_module(module_path)
        print(f"Applying migration {version}: {module_path}")

        with conn.cursor() as cur:
            cur.execute(mod.SQL_UP)
            cur.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (%s, %s)",
                (version, module_path),
            )
        conn.commit()
        print(f"  Applied migration {version}")

    print("All migrations applied.")


def rollback_migration(conn, version: int) -> None:
    ensure_schema_table(conn)
    applied = applied_versions(conn)

    if version not in applied:
        print(f"Migration {version} is not applied.")
        return

    module_path = None
    for mp in MIGRATIONS:
        parts = mp.rsplit(".", 1)[-1]
        v = int(parts.split("_")[0])
        if v == version:
            module_path = mp
            break

    if module_path is None:
        print(f"Migration {version} not found.")
        return

    mod = importlib.import_module(module_path)
    print(f"Rolling back migration {version}: {module_path}")

    with conn.cursor() as cur:
        cur.execute(mod.SQL_DOWN)
        cur.execute("DELETE FROM schema_migrations WHERE version = %s", (version,))
    conn.commit()
    print(f"  Rolled back migration {version}")


def show_status(conn) -> None:
    ensure_schema_table(conn)
    applied = applied_versions(conn)

    for module_path in MIGRATIONS:
        parts = module_path.rsplit(".", 1)[-1]
        version = int(parts.split("_")[0])
        status = "applied" if version in applied else "pending"
        print(f"  [{status}] {version}: {module_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run database migrations")
    parser.add_argument("--status", action="store_true", help="Show migration status")
    parser.add_argument("--down", type=int, metavar="VERSION", help="Rollback a migration")
    args = parser.parse_args()

    with db() as conn:
        if args.status:
            show_status(conn)
        elif args.down is not None:
            rollback_migration(conn, args.down)
        else:
            apply_migrations(conn)


if __name__ == "__main__":
    main()
