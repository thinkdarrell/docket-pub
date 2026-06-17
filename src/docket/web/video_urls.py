"""Video player deep-link URL construction.

Granicus's player wrapper page (``MediaPlayer.php``) ignores HTML5-native
``#t=NNN`` fragments. The correct chapter-jump param is ``&meta_id=N``,
matching the ``id`` field of the player's JS cuepoints array. The
Granicus adapter already stores those cuepoint ids as
``agenda_items.external_id`` (granicus.py builds RawAgendaItem with
``external_id=meta_id``).

Registered as the Jinja global ``chapter_url`` in :mod:`docket.web`.
"""
from __future__ import annotations

from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl


def chapter_url(video_url: str | None, meta_id: object) -> str | None:
    """Return ``video_url`` deep-linked to a specific chapter, when supported.

    Falls back to ``video_url`` unchanged when the player doesn't support
    deep links or when ``meta_id`` is missing / non-numeric. Returns
    ``None`` when ``video_url`` is None.

    Currently only Granicus ``MediaPlayer.php`` URLs are recognized; the
    rendered URL appends ``meta_id`` as a query param so Granicus's JS
    player seeks to the matching cuepoint on load.
    """
    if not video_url:
        return None
    if meta_id is None:
        return video_url
    meta_id_str = str(meta_id)
    if not meta_id_str.isdigit():
        return video_url
    if "MediaPlayer.php" not in video_url:
        return video_url

    parsed = urlparse(video_url)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    params["meta_id"] = meta_id_str
    return urlunparse(parsed._replace(query=urlencode(params), fragment=""))
