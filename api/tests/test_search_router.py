import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import os

# Set dummy env vars before importing main to prevent auth failures globally
os.environ["YT_API_KEY"] = "mock_api_key"

from api.app.main import app

# In newer httpx/starlette, TestClient requires the app to be passed properly.
client = TestClient(app)


@patch("api.app.routers.search.YouTubeService")
def test_search_router_success(mock_yt_service_class):
    # Mock the service instance
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service
    
    # Configure mock returns
    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.fetch_uploads_playlist_id.return_value = "PL123"
    mock_service.fetch_videos.return_value = [
        {"id": "vid1", "title": "Test Video 1", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": "thumb1"}
    ]
    mock_service.get_transcript.return_value = [{"start": 0, "text": "mock transcript"}]
    mock_service.search_in_transcript.return_value = [{"start": 0, "text": "mock match", "context_before": "", "context_after": ""}]
    mock_service.block_detected = False
    
    response = client.get("/api/search?channel_url=fake&keyword=mock")
    
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["video_id"] == "vid1"
    assert data[0]["matches"][0]["text"] == "mock match"

@patch("api.app.routers.search.YouTubeService")
def test_search_router_returns_403_on_block(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service
    
    mock_service.resolve_channel_id.return_value = "UC123"
    mock_service.fetch_uploads_playlist_id.return_value = "PL123"
    mock_service.fetch_videos.return_value = [{"id": "vid1", "title": "Test", "publishedAt": "2024-01-01T00:00:00Z", "thumbnail": ""}]
    
    # Simulate a transcript fetch that sets the block_detected flag
    mock_service.get_transcript.return_value = []
    mock_service.block_detected = True
    
    response = client.get("/api/search?channel_url=fake&keyword=mock")
    
    # Assert we surface the 403
    assert response.status_code == 403
    assert "YouTube blocked the request" in response.json()["detail"]

@patch("api.app.routers.search.YouTubeService")
def test_search_router_sanitizes_500_errors(mock_yt_service_class):
    mock_service = MagicMock()
    mock_yt_service_class.return_value = mock_service
    
    mock_service.resolve_channel_id.return_value = "UC123"
    # Simulate an unexpected critical failure in playlist fetching
    mock_service.fetch_uploads_playlist_id.side_effect = Exception("SENSITIVE_DB_OR_NETWORK_ERROR")
    
    response = client.get("/api/search?channel_url=fake&keyword=mock")
    
    # Assert we surface a 500, but NOT the sensitive error string
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "An internal server error occurred" in detail
    assert "SENSITIVE" not in detail
