from fastapi import FastAPI, HTTPException, Query
from typing import List, Optional
from datetime import datetime
import os
import re
from pydantic import BaseModel
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

# FastAPI app
app = FastAPI()

# Pydantic models
class SearchResult(BaseModel):
    video_id: str
    title: str
    published_at: str
    thumbnail: str
    matches: List[dict]

# YouTube Service class
class YouTubeService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.youtube = build("youtube", "v3", developerKey=api_key)

    def resolve_channel_id(self, channel_url_or_id: str) -> Optional[str]:
        if not channel_url_or_id:
            return None

        # Direct Channel ID (UC...)
        if re.match(r"^UC[a-zA-Z0-9_-]{22}$", channel_url_or_id):
            return channel_url_or_id

        # Standard Channel URL (/channel/UC...)
        match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", channel_url_or_id)
        if match:
            return match.group(1)

        # Handle URL or just @handle
        match = re.search(r"(?:youtube\.com/)?@([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            return self._resolve_name_to_channel_id(match.group(1))

        # Custom/Vanity URL (/c/name or /user/name)
        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            return self._resolve_name_to_channel_id(match.group(1))

        # Fallback: treat as a plain name/search query
        return self._resolve_name_to_channel_id(channel_url_or_id)

    def _resolve_name_to_channel_id(self, name_or_handle: str) -> Optional[str]:
        try:
            search_response = self.youtube.search().list(
                part="snippet",
                q=name_or_handle,
                type="channel",
                maxResults=1
            ).execute()

            if search_response.get("items"):
                return search_response["items"][0]["snippet"]["channelId"]
            return None
        except Exception as e:
            print(f"Error resolving channel name: {e}")
            return None

    def fetch_uploads_playlist_id(self, channel_id: str) -> str:
        response = self.youtube.channels().list(
            part="contentDetails",
            id=channel_id
        ).execute()

        if not response.get("items"):
            raise ValueError(f"No channel found with ID: {channel_id}")

        return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    def fetch_videos(self, playlist_id: str, max_videos: int = 50) -> List[dict]:
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

    def get_transcript(self, video_id: str) -> List[dict]:
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript = ytt_api.fetch(video_id, languages=['en', 'en-US'])
            return transcript.to_raw_data()
        except (TranscriptsDisabled, NoTranscriptFound):
            return []
        except Exception as e:
            print(f"Error fetching transcript for {video_id}: {e}")
            return []

    def search_in_transcript(self, transcript: List[dict], keyword: str) -> List[dict]:
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


@app.get("/api/search", response_model=List[SearchResult])
async def search(
    channel_url: str,
    keyword: str,
    max_videos: int = 20,
    published_after: Optional[str] = None,
):
    api_key = os.getenv("YT_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="YouTube API key not configured")
    
    service = YouTubeService(api_key)
    
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

    try:
        playlist_id = service.fetch_uploads_playlist_id(channel_id)
        fetch_count = max_videos * 3 if published_after else max_videos
        videos = service.fetch_videos(playlist_id, max_videos=fetch_count)

        # Filter by published_after date if provided
        if published_after:
            try:
                cutoff_date = datetime.fromisoformat(published_after.replace('Z', '+00:00'))
                videos = [
                    v for v in videos
                    if datetime.fromisoformat(v['publishedAt'].replace('Z', '+00:00')) >= cutoff_date
                ][:max_videos]
            except ValueError:
                pass

        results = []
        for video in videos:
            transcript = service.get_transcript(video["id"])
            if transcript:
                matches = service.search_in_transcript(transcript, keyword)
                if matches:
                    results.append(SearchResult(
                        video_id=video["id"],
                        title=video["title"],
                        published_at=video["publishedAt"],
                        thumbnail=video["thumbnail"],
                        matches=matches
                    ))
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
