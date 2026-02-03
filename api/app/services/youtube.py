import os
import re
from typing import List, Optional, Dict, Any
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

class YouTubeService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)

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
            # 1.2.x API: create instance and use fetch() with innertube backend
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id, languages=['en', 'en-US'])
            # Convert to raw dictionary format
            return transcript.to_raw_data()
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            print(f"DEBUG: Transcript API error for {video_id}: {type(e).__name__}")
            return []
        except Exception as e:
            print(f"DEBUG: Unexpected error fetching transcript for {video_id}: {str(e)}")
            return []

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
