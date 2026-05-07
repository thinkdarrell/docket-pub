"""Integration tests for migration 013_impact_first_refactor.

Verifies:
1. Migration applies cleanly to a fresh DB.
2. up → down → up returns the schema to a consistent state.
3. New columns and tables are queryable after up().
4. Seed data is present (7 process badges + 4 BHM policy templates + 2 BHM mayoral terms).
"""

from __future__ import annotations

from docket.db import db
from docket.migrations.runner import apply_migrations, rollback_migration


def test_013_applies_cleanly():
    """Migration 013 applies; new objects are present."""
    with db() as conn:
        apply_migrations(conn)

        with conn.cursor() as cur:
            # Enums exist
            cur.execute("""
                SELECT typname FROM pg_type
                WHERE typname IN (
                    'data_quality_enum',
                    'data_debt_priority_enum',
                    'processing_status_enum'
                )
            """)
            assert len(cur.fetchall()) == 3

            # New columns on agenda_items
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'agenda_items'
                  AND column_name IN ('extracted_facts', 'headline', 'why_it_matters',
                                       'data_quality', 'processing_status', 'search_vector')
            """)
            assert len(cur.fetchall()) == 6

            # 10 new tables exist (decisions #91, #93 added cache + status_audit)
            cur.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_name IN (
                    'priority_badge_templates', 'priority_badges_config',
                    'agenda_item_badges', 'agenda_item_badges_audit',
                    'city_score_floor_overrides', 'ai_batches', 'ai_batch_items',
                    'mayoral_terms',
                    'ai_response_cache', 'processing_status_audit'
                )
            """)
            assert len(cur.fetchall()) == 10

            # Process badges seeded (7)
            cur.execute(
                "SELECT COUNT(*) FROM priority_badge_templates WHERE kind = 'process'"
            )
            assert cur.fetchone()[0] == 7

            # BHM policy badges seeded (4)
            cur.execute(
                "SELECT COUNT(*) FROM priority_badge_templates WHERE kind = 'policy'"
            )
            assert cur.fetchone()[0] == 4

            # BHM opt-in config (4 rows)
            cur.execute("""
                SELECT COUNT(*) FROM priority_badges_config c
                JOIN municipalities m ON m.id = c.city_id
                WHERE m.slug = 'birmingham'
            """)
            assert cur.fetchone()[0] == 4

            # BHM mayoral terms (2 rows)
            cur.execute("""
                SELECT COUNT(*) FROM mayoral_terms mt
                JOIN municipalities m ON m.id = mt.city_id
                WHERE m.slug = 'birmingham'
            """)
            assert cur.fetchone()[0] == 2


def test_013_search_vector_trigger_fires_on_insert():
    """Inserting into agenda_items populates search_vector via trigger."""
    with db() as conn:
        apply_migrations(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT id FROM meetings LIMIT 1")
            meeting_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO agenda_items (meeting_id, title, description, summary)
                VALUES (%s, 'Test item title', 'Test description body', NULL)
                RETURNING id, search_vector
            """, [meeting_id])
            new_id, sv = cur.fetchone()
            assert sv is not None
            # tsvector representation contains the lexemes
            assert "title" in str(sv).lower() or "test" in str(sv).lower()

            # Cleanup
            cur.execute("DELETE FROM agenda_items WHERE id = %s", [new_id])


def test_013_up_down_up_cycle():
    """up → down → up leaves schema in a consistent state."""
    with db() as conn:
        apply_migrations(conn)
        rollback_migration(conn, 13)

        with conn.cursor() as cur:
            # Enums should be gone
            cur.execute("""
                SELECT COUNT(*) FROM pg_type
                WHERE typname IN ('data_quality_enum', 'data_debt_priority_enum',
                                   'processing_status_enum')
            """)
            assert cur.fetchone()[0] == 0

            # New tables should be gone
            cur.execute("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_name = 'agenda_item_badges'
            """)
            assert cur.fetchone()[0] == 0

        # Re-apply
        apply_migrations(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM priority_badge_templates")
            # 7 process + 4 policy = 11 templates
            assert cur.fetchone()[0] == 11
