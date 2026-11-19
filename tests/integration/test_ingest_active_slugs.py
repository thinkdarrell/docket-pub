"""active_slugs() is the one list of cities the worker's ingest tasks visit.

Plan `recordings-seen-the-day-posted`, M1. Pattern mirrors
tests/integration/test_ingest_preserves_is_hidden.py.
"""

import pytest

from docket.config import DATABASE_URL
from docket.db import db


pytestmark = pytest.mark.skipif(
    "railway.internal" in DATABASE_URL or "railway.app" in DATABASE_URL,
    reason="Integration tests require local DB; will not run against Railway prod",
)


# Chosen to sort on either side of each other and to collide with no real city.
ACTIVE_FIRST = "aaa_test_active_slugs_on"
INACTIVE = "mmm_test_active_slugs_off"
ACTIVE_LAST = "zzz_test_active_slugs_on"
SLUGS = (ACTIVE_FIRST, INACTIVE, ACTIVE_LAST)


@pytest.fixture
def cities():
    with db() as conn, conn.cursor() as cur:
        # Inserted last-first, so insertion order is not slug order.
        for slug, active in ((ACTIVE_LAST, True), (INACTIVE, False), (ACTIVE_FIRST, True)):
            cur.execute(
                """
                INSERT INTO municipalities (slug, name, state, adapter_class, adapter_config, active)
                VALUES (%s, %s, 'AL', 'GranicusAdapter',
                        '{"view_id": 1, "base_url": "https://example.com"}'::jsonb, %s)
                ON CONFLICT (slug) DO UPDATE SET active = EXCLUDED.active
                """,
                (slug, f"Test {slug}", active),
            )
        conn.commit()
    yield
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM municipalities WHERE slug = ANY(%s)", (list(SLUGS),))
        conn.commit()


def test_active_slugs_lists_the_active_cities_in_slug_order(cities):
    from docket.services.ingest import active_slugs

    slugs = active_slugs()

    assert isinstance(slugs, list)
    assert ACTIVE_FIRST in slugs
    assert ACTIVE_LAST in slugs
    assert INACTIVE not in slugs
    assert slugs == sorted(slugs)
    assert slugs.index(ACTIVE_FIRST) < slugs.index(ACTIVE_LAST)
