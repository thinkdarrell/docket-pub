"""YouTube Data API v3 client: lists a channel's uploads, with durations and stream times.

A thin, read-only client over three calls, each one quota unit:

    channels?part=contentDetails&forHandle=<handle>      -> the uploads playlist id
    playlistItems?part=snippet,contentDetails&playlistId  -> every upload, newest first
    videos?part=contentDetails,liveStreamingDetails,snippet&id=<up to 50>
                                                         -> duration, stream start, live state

The uploads playlist holds completed live streams as well as ordinary uploads,
which is why it is read instead of the channel's videos tab: the council's
committee meetings are live streams.

The HTTP call is injected (``get``, default ``requests.get``) so tests drive the
client with canned pages and no network. Nothing here touches the database;
``docket.services.youtube_meetings`` decides what the videos mean.

Plan: plans/active/youtube-council-channel.md (M1).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/youtube/v3"
PAGE_SIZE = 50  # the API's maximum for playlistItems and videos


@dataclass(frozen=True)
class YouTubeVideo:
    """One upload: what the playlist says, plus what ``fill_details`` adds."""

    video_id: str
    title: str
    published_at: datetime  # timezone-aware UTC
    duration_s: int | None = None
    started_at: datetime | None = None
    broadcast: str = "none"  # 'none' | 'live' | 'upcoming'


class YouTubeAPIError(RuntimeError):
    """A non-200 answer from the Data API, with its HTTP status and error reason."""

    def __init__(self, status: int, reason: str | None, message: str = ""):
        self.status = status
        self.reason = reason
        super().__init__(f"YouTube Data API {status} {reason or 'unknown'}: {message}".rstrip(": "))


class QuotaExceeded(YouTubeAPIError):
    """The key's daily quota is spent; the caller ends its run."""


_ISO_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def parse_iso_duration(text: str) -> int | None:
    """``PT3H10M6S`` -> 11406; ``P0D`` (an upcoming stream) -> 0; anything else -> None."""
    if not text:
        return None
    m = _ISO_DURATION.match(text.strip())
    if not m or text.strip() in ("P", "PT"):
        return None
    days, hours, minutes, seconds = (int(g) if g else 0 for g in m.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _parse_ts(text: str | None) -> datetime | None:
    """An API timestamp (``2026-09-30T23:10:06Z``, sometimes with fractions) as aware UTC."""
    if not text:
        return None
    cleaned = re.sub(r"\.\d+", "", text.strip()).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class YouTubeClient:
    """Read-only Data API v3 client keyed by an API key."""

    def __init__(self, api_key: str, *, get=requests.get, delay: float = 0.0):
        self._key = api_key
        self._get = get
        self._delay = delay
        self._calls = 0

    def _call(self, endpoint: str, params: dict) -> dict:
        if self._delay and self._calls:
            time.sleep(self._delay)
        self._calls += 1
        resp = self._get(f"{API_BASE}/{endpoint}", params={**params, "key": self._key}, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        reason, message = None, ""
        try:
            error = (resp.json() or {}).get("error") or {}
            message = error.get("message") or ""
            errors = error.get("errors") or []
            if errors:
                reason = errors[0].get("reason")
        except (ValueError, AttributeError):
            pass
        if reason == "quotaExceeded":
            raise QuotaExceeded(resp.status_code, reason, message)
        raise YouTubeAPIError(resp.status_code, reason, message)

    def uploads_playlist_id(self, handle: str) -> str:
        """The id of the channel's uploads playlist (``UU…`` for channel ``UC…``)."""
        body = self._call("channels", {"part": "contentDetails", "forHandle": handle})
        items = body.get("items") or []
        if not items:
            raise YouTubeAPIError(200, "channelNotFound", f"no channel for handle {handle!r}")
        return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def list_uploads(self, playlist_id: str, *, published_after: datetime | None = None) -> list[YouTubeVideo]:
        """Every upload in the playlist, newest first, optionally only those at or after a cutoff.

        The playlist is newest-first, but a finished stream's publish time can
        sit a little out of order, so one old item never ends the walk: paging
        stops when the playlist ends or after a whole page is older than the
        cutoff. Items older than the cutoff are dropped from the result.
        """
        videos: list[YouTubeVideo] = []
        token: str | None = None
        while True:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": PAGE_SIZE,
            }
            if token:
                params["pageToken"] = token
            body = self._call("playlistItems", params)
            items = body.get("items") or []
            page_all_old = bool(items)
            for item in items:
                snippet = item.get("snippet") or {}
                details = item.get("contentDetails") or {}
                video_id = details.get("videoId") or (snippet.get("resourceId") or {}).get("videoId")
                published = _parse_ts(details.get("videoPublishedAt") or snippet.get("publishedAt"))
                if not video_id or published is None:
                    continue
                if published_after is not None and published < published_after:
                    continue
                page_all_old = False
                videos.append(YouTubeVideo(video_id=video_id, title=snippet.get("title") or "", published_at=published))
            token = body.get("nextPageToken")
            if not token or (published_after is not None and page_all_old):
                break
        return videos

    def fill_details(self, videos: list[YouTubeVideo]) -> list[YouTubeVideo]:
        """Add duration, stream start, and live state, 50 ids per call; order is kept.

        A video the API no longer returns (deleted, made private) comes back
        unchanged, so its ``duration_s`` stays None.
        """
        found: dict[str, dict] = {}
        ids = [v.video_id for v in videos]
        for start in range(0, len(ids), PAGE_SIZE):
            batch = ids[start : start + PAGE_SIZE]
            body = self._call(
                "videos",
                {"part": "contentDetails,liveStreamingDetails,snippet", "id": ",".join(batch)},
            )
            for item in body.get("items") or []:
                found[item.get("id")] = item
        filled = []
        for video in videos:
            item = found.get(video.video_id)
            if item is None:
                filled.append(video)
                continue
            filled.append(
                replace(
                    video,
                    duration_s=parse_iso_duration((item.get("contentDetails") or {}).get("duration") or ""),
                    started_at=_parse_ts((item.get("liveStreamingDetails") or {}).get("actualStartTime")),
                    broadcast=(item.get("snippet") or {}).get("liveBroadcastContent") or "none",
                )
            )
        return filled
