from unittest.mock import MagicMock, patch

import requests

from docket.ai.transcripts import alerts as A


def test_no_url_means_no_request(monkeypatch):
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", None)
    with patch("docket.ai.transcripts.alerts.requests.post") as post:
        assert A.post_alert("transcript_failed", "x", meeting_id=1) is False
        post.assert_not_called()


def test_payload_fits_slack_and_discord(monkeypatch):
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", "https://hooks.example/abc")
    with patch("docket.ai.transcripts.alerts.requests.post") as post:
        post.return_value = MagicMock(status_code=204, ok=True)
        assert A.post_alert("transcript_needs_review", "Transcript 7 held: candidate_cap", meeting_id=7, stage="compare") is True
        kw = post.call_args.kwargs
        assert post.call_args.args[0] == "https://hooks.example/abc" and kw["timeout"] == 10
        body = kw["json"]
        assert body["text"] == body["content"] == "Transcript 7 held: candidate_cap"
        assert body["kind"] == "transcript_needs_review" and body["meeting_id"] == 7 and body["stage"] == "compare"


def test_network_errors_are_swallowed(monkeypatch):
    monkeypatch.setattr(A, "ALERT_WEBHOOK_URL", "https://hooks.example/abc")
    with patch("docket.ai.transcripts.alerts.requests.post", side_effect=requests.ConnectionError("down")):
        assert A.post_alert("x", "y") is False
