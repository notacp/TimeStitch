import os
import re
from typing import List, Optional, Dict, Any
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

class YouTubeService:
    def __init__(self, api_key: str, proxy_url: Optional[str] = None):
        self.api_key = api_key
        self.proxy_url = proxy_url
        self.youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)
        self.block_detected = False

    def _get_http_client(self) -> Any:
        import requests
        import random
        
        session = requests.Session()
        
        # Randomize User-Agent to help bypass basic blocks
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        ]
        session.headers.update({
            "User-Agent": random.choice(user_agents),
            "Accept-Language": "en-US,en;q=0.9",
        })
        
        # Configure proxy if provided
        if self.proxy_url:
            print("DEBUG: Configuring HTTP Client with Proxy")
            session.proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url
            }
            
        return session

    def resolve_channel_id(self, channel_url_or_id: str) -> Optional[str]:
        if not channel_url_or_id:
            return None

        # 1. Direct Channel ID (UC...)
        if re.match(r"^UC[a-zA-Z0-9_-]{22}$", channel_url_or_id):
            return channel_url_or_id

        # 2. Standard Channel URL (/channel/UC...)
        match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", channel_url_or_id)
        if match:
            return match.group(1)

        # 3. Handle URL or just @handle
        match = re.search(r"(?:youtube\.com/)?@([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            return self._resolve_name_to_channel_id(match.group(1))

        # 4. Custom/Vanity URL (/c/name or /user/name)
        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            return self._resolve_name_to_channel_id(match.group(1))

        # 5. Fallback: treat as a plain name/search query
        return self._resolve_name_to_channel_id(channel_url_or_id)

    def _resolve_name_to_channel_id(self, name_or_handle: str) -> Optional[str]:
        try:
            print(f"DEBUG: Resolving '{name_or_handle}' to Channel ID via search...")
            search_response = self.youtube.search().list(
                part="snippet",
                q=name_or_handle,
                type="channel",
                maxResults=1
            ).execute()

            if search_response.get("items"):
                channel_id = search_response["items"][0]["snippet"]["channelId"]
                print(f"DEBUG: Resolved to {channel_id}")
                return channel_id
            print(f"DEBUG: No channel found for '{name_or_handle}'")
            return None
        except Exception as e:
            print(f"DEBUG: Error resolving channel name: {str(e)}")
            return None

    def fetch_uploads_playlist_id(self, channel_id: str) -> str:
        response = self.youtube.channels().list(
            part="contentDetails",
            id=channel_id
        ).execute()

        if not response.get("items"):
            raise ValueError(f"No channel found with ID: {channel_id}")

        return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def fetch_videos(self, playlist_id: str, max_videos: int = 50) -> List[Dict[str, Any]]:
        videos = []
        next_page_token = None
        
        while len(videos) < max_videos:
            response = self.youtube.playlistItems().list(
                part="contentDetails,snippet",
                playlistId=playlist_id,
                maxResults=min(50, max_videos - len(videos)),
                pageToken=next_page_token
            ).execute()

            for item in response.get('items', []):
                snippet = item.get('snippet', {})
                content_details = item.get('contentDetails', {})
                videos.append({
                    "id": content_details.get('videoId'),
                    "title": snippet.get('title'),
                    "publishedAt": snippet.get('publishedAt'),
                    "thumbnail": snippet.get('thumbnails', {}).get('high', {}).get('url')
                })

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
                
        return videos

    def get_transcript(self, video_id: str) -> List[Dict[str, Any]]:
        """Fetch transcript using the 1.2.x API (instance methods with innertube)."""
        try:
            # 1.2.x API: Pass custom http_client for User-Agent rotation and Proxy
            http_client = self._get_http_client()
            ytt_api = YouTubeTranscriptApi(http_client=http_client)
            transcript = ytt_api.fetch(video_id, languages=['en', 'en-US'])
            # Convert to raw dictionary format
            return transcript.to_raw_data()
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            print(f"DEBUG: Transcript API error for {video_id}: {type(e).__name__}")
            return []
        except Exception as e:
            error_msg = str(e)
            if "blocking requests from your IP" in error_msg or "429" in error_msg or "blocked" in error_msg.lower():
                print(f"DEBUG ERROR: YouTube blocked the request. IP/Block detected for {video_id}.")
                self.block_detected = True
            else:
                print(f"DEBUG ERROR: Unexpected error fetching transcript for {video_id}: {error_msg}")
            
            # Re-raise so the router can handle 500s or detect the block state
            raise


    def search_in_transcript(self, transcript: List[Dict[str, Any]], keyword: str) -> List[Dict[str, Any]]:
        matches = []
        keyword_lower = keyword.lower()
        for i, segment in enumerate(transcript):
            if keyword_lower in segment['text'].lower():
                matches.append({
                    "start": segment['start'],
                    "text": segment['text'],
                    "context_before": transcript[i-1]['text'] if i > 0 else "",
                    "context_after": transcript[i+1]['text'] if i < len(transcript) - 1 else ""
                })
        return matches
