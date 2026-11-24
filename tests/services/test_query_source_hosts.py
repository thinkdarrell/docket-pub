"""docket.services.query.list_active_base_urls: the stored base addresses.

The one statement behind the source-link allowlist
(``docket.web.source_security``): the ``base_url`` of every active
municipality that stores one, exactly as stored, with no parsing.

Three rows are seeded whose slugs begin ``srchost_test_`` and are deleted
before and after every test. The service's name is imported inside each
test, so the file collects before the service exists. Runs in the services
tier (DATABASE_URL names docket_test_*).

Plan `source-links-and-blog-survive-a-slow-db`, M1.
"""

from __future__ import annotations

import json

import pytest

from docket.db import db_cursor

PREFIX = "srchost_test_"
ACTIVE_URL = "https://Records.Example.gov:8443/x"
INACTIVE_URL = "https://inactive.example.gov"
BIRMINGHAM_URL = "https://bhamal.granicus.com"


def _delete_seeded() -> None:
    with db_cursor() as cur:
        cur.execute("DELETE FROM municipalities WHERE slug LIKE %s", (PREFIX + "%",))


def _city(suffix: str, config: dict, *, active: bool = True) -> None:
    with db_cursor() as cur:
        cur.execute(
            """INSERT INTO municipalities (slug, name, adapter_class, adapter_config, active)
               VALUES (%s, %s, 'GranicusAdapter', %s, %s)""",
            (PREFIX + suffix, "Source host test " + suffix, json.dumps(config), active),
        )


@pytest.fixture(autouse=True)
def _clean():
    _delete_seeded()
    yield
    _delete_seeded()


@pytest.fixture
def seeded():
    _city("active", {"base_url": ACTIVE_URL})
    _city("inactive", {"base_url": INACTIVE_URL}, active=False)
    _city("no_base_url", {"tenant": "srchosttest"})


def test_an_active_citys_base_url_is_returned_exactly_as_stored(seeded):
    from docket.services.query import list_active_base_urls

    assert ACTIVE_URL in list_active_base_urls()


def test_an_inactive_citys_base_url_is_absent(seeded):
    from docket.services.query import list_active_base_urls

    assert INACTIVE_URL not in list_active_base_urls()


def test_the_seeded_birmingham_row_is_present(seeded):
    from docket.services.query import list_active_base_urls

    assert BIRMINGHAM_URL in list_active_base_urls()


def test_every_element_is_a_string_or_none_and_a_city_without_the_key_adds_none():
    from docket.services.query import list_active_base_urls

    before = list_active_base_urls()
    _city("active", {"base_url": ACTIVE_URL})
    _city("inactive", {"base_url": INACTIVE_URL}, active=False)
    _city("no_base_url", {"tenant": "srchosttest"})
    urls = list_active_base_urls()
    assert isinstance(urls, list)
    assert all(u is None or isinstance(u, str) for u in urls)
    # Of the three rows only the active one that stores a base_url adds an
    # element: the inactive row and the row with no base_url key add nothing.
    assert len(urls) == len(before) + 1
