import pytest
from unittest.mock import patch, MagicMock
from api.app.services.youtube import YouTubeService

# Sample transcript data representing raw output from youtube-transcript-api
MOCK_TRANSCRIPT = [
    {"start": 1.0, "duration": 2.5, "text": "Welcome to the video"},
    {"start": 4.0, "duration": 1.5, "text": "Today we will discuss python"},
    {"start": 6.0, "duration": 3.0, "text": "Python is a great programming language"},
    {"start": 10.0, "duration": 2.0, "text": "Thanks for watching"}
]

def test_search_in_transcript_finds_single_match():
    service = YouTubeService(api_key="fake-key")
    matches = service.search_in_transcript(MOCK_TRANSCRIPT, "welcome")
    
    assert len(matches) == 1
    assert matches[0]["start"] == 1.0
    assert matches[0]["text"] == "Welcome to the video"
    # First item has no context_before
    assert matches[0]["context_before"] == ""
    assert matches[0]["context_after"] == "Today we will discuss python"

def test_search_in_transcript_finds_multiple_matches():
    service = YouTubeService(api_key="fake-key")
    matches = service.search_in_transcript(MOCK_TRANSCRIPT, "python")
    
    assert len(matches) == 2
    assert matches[0]["text"] == "Today we will discuss python"
    assert matches[0]["context_before"] == "Welcome to the video"
    assert matches[0]["context_after"] == "Python is a great programming language"

def test_search_in_transcript_case_insensitive():
    service = YouTubeService(api_key="fake-key")
    matches = service.search_in_transcript(MOCK_TRANSCRIPT, "PYTHON")
    assert len(matches) == 2

def test_search_in_transcript_no_match():
    service = YouTubeService(api_key="fake-key")
    matches = service.search_in_transcript(MOCK_TRANSCRIPT, "rust")
    assert len(matches) == 0

def test_proxy_wiring():
    # Verify that the HTTP client helper correctly applies the proxy URL
    service = YouTubeService(api_key="fake", proxy_url="http://mock-proxy:8080")
    session = service._get_http_client()
    
    assert session.proxies["http"] == "http://mock-proxy:8080"
    assert session.proxies["https"] == "http://mock-proxy:8080"
    assert "User-Agent" in session.headers

def test_block_detection_logic():
    # Verify the service safely swallows block exceptions and sets the flag
    service = YouTubeService(api_key="fake")
    
    with patch("youtube_transcript_api.YouTubeTranscriptApi.fetch") as mock_fetch:
        # Simulate a block error string that youtube-transcript-api throws sometimes
        mock_fetch.side_effect = Exception("YouTube is blocking requests from your IP...")
        
        # We expect the fetch to raise, but `service.block_detected` should be set to True.
        with pytest.raises(Exception):
            service.get_transcript("fake-video-id")
            
        assert service.block_detected is True
