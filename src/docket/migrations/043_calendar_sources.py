"""Migration 043 — the calendar's other sources: `city_calendar_events.event_status` and Birmingham's search and sitemap metadata.

Until now `city_calendar_events` was filled from the council page alone,
which lists the next four events. Birmingham's metadata gains the
addresses of two more readers and the facts they need:
`calendar_search_url` (the site's events search, which answers with every
upcoming event of one department), `calendar_department_id` (`"55"`, the
search's id for the City Council department) and `calendar_department`
(`"City Council"`, the name an event page gives its department; only that
department's events are stored), `calendar_sitemap_url` (the sitemap,
the one public listing that still holds past event pages), and
`calendar_complete_from` (`"2026-10-05"`, the earliest date from which the
sitemap held the council's events when it was read on 2026-11-11; a day
before it with no stored event says nothing about what was scheduled).
The site's `robots.txt` disallows `/search` and not `/api/search`.

`event_status` is the source's `eventStatus` (`active` on every event read
so far), NULL on every existing row and on an event whose source reports
none, which the search does not. It is stored so that a cancelled event can
be told from a held one.

Additive; the down removes the five keys and the column, and leaves
038's `calendar_url` and `council_schedule` alone.
Plan `committee-clips-named-or-hidden`, M1.
"""

from __future__ import annotations


SQL_UP = r"""
ALTER TABLE city_calendar_events
    ADD COLUMN IF NOT EXISTS event_status TEXT NULL;

UPDATE municipalities
   SET metadata = metadata || '{"calendar_search_url": "https://www.birminghamal.gov/api/search/events", "calendar_department_id": "55", "calendar_department": "City Council", "calendar_sitemap_url": "https://www.birminghamal.gov/sitemap.xml", "calendar_complete_from": "2026-10-05"}'::jsonb
 WHERE slug = 'birmingham';
"""

SQL_DOWN = r"""
UPDATE municipalities
   SET metadata = metadata - 'calendar_search_url' - 'calendar_department_id' - 'calendar_department'
                           - 'calendar_sitemap_url' - 'calendar_complete_from'
 WHERE slug = 'birmingham';

ALTER TABLE IF EXISTS city_calendar_events
    DROP COLUMN IF EXISTS event_status;
"""
