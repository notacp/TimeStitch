import json
import os
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

# Set dummy env vars before importing main to prevent auth failures globally
os.environ["YT_API_KEY"] = "mock_api_key"

from api.app.main import app

client = TestClient(app)


def parse_sse_results(response) -> list:
    """Collect all match-result data lines from an SSE response."""
    results = []
    for line in response.text.splitlines():
        if line.startswith("data: ") and line[6:] not in ("{}", ""):
            results.append(json.loads(line[6:]))
    return results


def parse_sse_error(response) -> dict:
    """Return the payload of the first `event: error` in an SSE response."""
    lines = response.text.splitlines()
    for i, line in enumerate(lines):
        if line == "event: error" and i + 1 < len(lines):
            data_line = lines[i + 1]
            if data_line.startswith("data: "):
                return json.loads(data_line[6:])
    return {}


@patch("api.app.routers.search.YouTubeService")
def test_search_router_success(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.fetch_uploads_playlist_id.return_value = "PL123"
    mock_service.fetch_videos.return_value = [
        {"id": "vid1", "title": "Test Video 1", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": "thumb1"},
    ]
    mock_service.get_transcript.return_value = {
        "language_code": "en",
        "language_label": "English",
        "is_generated": False,
        "segments": [{"start": 0, "text": "mock transcript"}],
    }
    mock_service.expand_search_terms_for_transcript.side_effect = lambda terms, transcript, transcript_language: terms
    mock_service.search_in_transcript.return_value = [{"start": 0, "text": "mock match", "context_before": "", "context_after": ""}]
    response = client.get("/api/search?channel_url=fake&keyword=mock")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    data = parse_sse_results(response)
    assert len(data) == 1
    assert data[0]["video_id"] == "vid1"
    assert data[0]["transcript_language_code"] == "en"
    assert data[0]["transcript_language_label"] == "English"
    assert data[0]["search_terms_used"] == ["mock"]
    assert data[0]["matches"][0]["text"] == "mock match"
    assert mock_service.get_transcript.call_count == 1
    mock_service.get_transcript.assert_called_with("vid1", preferred_languages=["en", "hi", "fr", "es", "pt"])
    mock_service.search_in_transcript.assert_called_once_with(
        [{"start": 0, "text": "mock transcript"}],
        ["mock"],
        transcript_language="en",
    )


@patch("api.app.routers.search.YouTubeService")
def test_search_router_uses_romanized_variant_for_devanagari_query(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.fetch_uploads_playlist_id.return_value = "PL123"
    mock_service.fetch_videos.return_value = [
        {"id": "vid1", "title": "Test", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": ""},
    ]
    mock_service.get_transcript.return_value = {
        "language_code": "en",
        "language_label": "English",
        "is_generated": False,
        "segments": [{"start": 0, "text": "startup"}],
    }
    mock_service.expand_search_terms_for_transcript.return_value = ["स्टार्टअप", "staartapa"]
    mock_service.search_in_transcript.return_value = [{"start": 0, "text": "startup", "context_before": "", "context_after": ""}]

    response = client.get("/api/search?channel_url=fake&keyword=%E0%A4%B8%E0%A5%8D%E0%A4%9F%E0%A4%BE%E0%A4%B0%E0%A5%8D%E0%A4%9F%E0%A4%85%E0%A4%AA")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    data = parse_sse_results(response)
    assert data[0]["search_terms_used"] == ["स्टार्टअप", "staartapa"]
    assert mock_service.get_transcript.call_count == 1
    mock_service.get_transcript.assert_called_with("vid1", preferred_languages=["hi", "en", "fr", "es", "pt"])
    mock_service.search_in_transcript.assert_called_once_with(
        [{"start": 0, "text": "startup"}],
        ["स्टार्टअप", "staartapa"],
        transcript_language="en",
    )


@patch("api.app.routers.search.YouTubeService")
def test_search_router_keeps_latin_query_without_translation(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.fetch_uploads_playlist_id.return_value = "PL123"
    mock_service.fetch_videos.return_value = [
        {"id": "vid1", "title": "Test", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": ""},
    ]
    mock_service.get_transcript.return_value = {
        "language_code": "hi",
        "language_label": "Hindi",
        "is_generated": False,
        "segments": [{"start": 0, "text": "स्टार्टअप"}],
    }
    mock_service.expand_search_terms_for_transcript.return_value = ["startup", "स्टार्टअप"]
    mock_service.search_in_transcript.return_value = [{"start": 0, "text": "स्टार्टअप", "context_before": "", "context_after": ""}]

    response = client.get("/api/search?channel_url=fake&keyword=startup")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    data = parse_sse_results(response)
    assert data[0]["search_terms_used"] == ["startup", "स्टार्टअप"]
    assert mock_service.get_transcript.call_count == 1
    mock_service.get_transcript.assert_called_with("vid1", preferred_languages=["en", "hi", "fr", "es", "pt"])
    mock_service.search_in_transcript.assert_called_once_with(
        [{"start": 0, "text": "स्टार्टअप"}],
        ["startup", "स्टार्टअप"],
        transcript_language="hi",
    )


@patch("api.app.routers.search.YouTubeService")
def test_search_router_falls_back_to_hindi_track_when_english_track_misses(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.fetch_uploads_playlist_id.return_value = "PL123"
    mock_service.fetch_videos.return_value = [
        {"id": "vid1", "title": "Test", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": ""},
    ]
    mock_service.get_transcript.side_effect = [
        {
            "language_code": "en",
            "language_label": "English",
            "is_generated": False,
            "segments": [{"start": 0, "text": "we did not invest"}],
        },
        {
            "language_code": "hi",
            "language_label": "Hindi",
            "is_generated": False,
            "segments": [{"start": 12, "text": "हमने क्लाइंट्स को इन्वेस्ट नहीं किया"}],
        },
    ]
    mock_service.expand_search_terms_for_transcript.side_effect = [
        ["invest"],
        ["invest", "इन्वेस्ट"],
    ]
    mock_service.search_in_transcript.side_effect = [
        [],
        [{"start": 12, "text": "हमने क्लाइंट्स को इन्वेस्ट नहीं किया", "context_before": "", "context_after": ""}],
    ]

    response = client.get("/api/search?channel_url=fake&keyword=invest")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    data = parse_sse_results(response)
    assert data[0]["transcript_language_code"] == "hi"
    assert data[0]["search_terms_used"] == ["invest", "इन्वेस्ट"]
    assert mock_service.get_transcript.call_args_list == [
        (("vid1",), {"preferred_languages": ["en", "hi", "fr", "es", "pt"]}),
        (("vid1",), {"preferred_languages": ["hi", "en", "fr", "es", "pt"]}),
    ]
    assert mock_service.search_in_transcript.call_args_list[0].kwargs["transcript_language"] == "en"
    assert mock_service.search_in_transcript.call_args_list[1].kwargs["transcript_language"] == "hi"


@patch("api.app.routers.search.YouTubeService")
def test_search_router_adds_finology_candidate_from_hindi_transcript(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.fetch_uploads_playlist_id.return_value = "PL123"
    mock_service.fetch_videos.return_value = [
        {"id": "vid1", "title": "Test", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": ""},
    ]
    mock_service.get_transcript.return_value = {
        "language_code": "hi",
        "language_label": "Hindi",
        "is_generated": False,
        "segments": [{"start": 12, "text": "मेरे में आपका 30 स्टॉक्स का पोर्टफोलियो बने, तो फिनोलॉजी"}],
    }
    mock_service.expand_search_terms_for_transcript.return_value = ["Finology", "फिनोलॉजी"]
    mock_service.search_in_transcript.return_value = [
        {"start": 12, "text": "मेरे में आपका 30 स्टॉक्स का पोर्टफोलियो बने, तो फिनोलॉजी", "context_before": "", "context_after": ""}
    ]

    response = client.get("/api/search?channel_url=fake&keyword=Finology")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    data = parse_sse_results(response)
    assert data[0]["search_terms_used"] == ["Finology", "फिनोलॉजी"]
    mock_service.search_in_transcript.assert_called_once_with(
        [{"start": 12, "text": "मेरे में आपका 30 स्टॉक्स का पोर्टफोलियो बने, तो फिनोलॉजी"}],
        ["Finology", "फिनोलॉजी"],
        transcript_language="hi",
    )



@patch("api.app.routers.search.YouTubeService")
def test_videos_endpoint_returns_video_list(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.resolve_channel_id.return_value = "UC456"
    mock_service.fetch_uploads_playlist_id.return_value = "PL456"
    mock_service.fetch_videos.return_value = [
        {"id": "v1", "title": "Video 1", "publishedAt": "2024-06-01T00:00:00Z", "thumbnail": "t1"},
        {"id": "v2", "title": "Video 2", "publishedAt": "2024-05-01T00:00:00Z", "thumbnail": "t2"},
    ]

    response = client.post("/api/videos", json={"channel_url": "@fakechannel", "max_videos": 10})

    assert response.status_code == 200
    data = response.json()
    assert data["channel_id"] == "UC456"
    assert len(data["videos"]) == 2
    assert data["videos"][0]["id"] == "v1"
    mock_service.resolve_channel_id.assert_called_once_with("@fakechannel")
    mock_service.fetch_uploads_playlist_id.assert_called_once_with("UC456")
    # No date filter / no shorts → fetch_count == max_videos
    mock_service.fetch_videos.assert_called_once_with("PL456", max_videos=10, exclude_shorts=False)


@patch("api.app.routers.search.YouTubeService")
def test_match_endpoint_returns_match(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.expand_search_terms_for_transcript.return_value = ["posthog"]
    mock_service.search_in_transcript.return_value = [
        {"start": 5.0, "text": "we use posthog for analytics", "context_before": "", "context_after": ""}
    ]

    payload = {
        "keyword": "posthog",
        "video": {"id": "abc", "title": "Test Video", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": ""},
        "transcript": {
            "language_code": "en",
            "language_label": "English",
            "is_generated": False,
            "segments": [{"start": 5.0, "duration": 2.0, "text": "we use posthog for analytics"}],
        },
    }
    response = client.post("/api/match", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["match_result"] is not None
    assert data["match_result"]["video_id"] == "abc"
    assert data["match_result"]["title"] == "Test Video"
    assert data["match_result"]["transcript_language_code"] == "en"
    assert data["match_result"]["search_terms_used"] == ["posthog"]
    assert data["match_result"]["matches"][0]["start"] == 5.0


@patch("api.app.routers.search.YouTubeService")
def test_match_endpoint_returns_null_when_no_matches(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.expand_search_terms_for_transcript.return_value = ["posthog"]
    mock_service.search_in_transcript.return_value = []

    payload = {
        "keyword": "posthog",
        "video": {"id": "abc", "title": "Test Video", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": ""},
        "transcript": {
            "language_code": "en",
            "language_label": "English",
            "is_generated": False,
            "segments": [{"start": 0.0, "duration": 3.0, "text": "nothing relevant here"}],
        },
    }
    response = client.post("/api/match", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["match_result"] is None


@patch("api.app.routers.search.YouTubeService")
def test_search_router_sanitizes_500_errors(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service

    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.expand_search_terms_for_transcript.side_effect = lambda terms, transcript, transcript_language: terms
    mock_service.fetch_uploads_playlist_id.side_effect = Exception("SENSITIVE_DB_OR_NETWORK_ERROR")

    response = client.get("/api/search?channel_url=fake&keyword=mock")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    error = parse_sse_error(response)
    assert error.get("status") == 500
    assert "An internal server error occurred" in error.get("detail", "")
    assert "SENSITIVE" not in error.get("detail", "")
