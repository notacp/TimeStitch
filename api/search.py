from fastapi import FastAPI, HTTPException, Query, Request
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import re
import sys
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
        print(f"DEBUG: Resolving channel ID for: {channel_url_or_id}")
        if not channel_url_or_id:
            return None

        # Direct Channel ID (UC...)
        if re.match(r"^UC[a-zA-Z0-9_-]{22}$", channel_url_or_id):
            print(f"DEBUG: Matched direct channel ID pattern: {channel_url_or_id}")
            return channel_url_or_id

        # Standard Channel URL (/channel/UC...)
        match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", channel_url_or_id)
        if match:
            print(f"DEBUG: Matched standard channel URL pattern: {match.group(1)}")
            return match.group(1)

        # Handle URL or just @handle
        match = re.search(r"(?:youtube\.com/)?@([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            print(f"DEBUG: Matched handle pattern: {match.group(1)}")
            return self._resolve_name_to_channel_id(match.group(1))

        # Custom/Vanity URL (/c/name or /user/name)
        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            print(f"DEBUG: Matched custom/vanity URL pattern: {match.group(1)}")
            return self._resolve_name_to_channel_id(match.group(1))

        # Fallback: treat as a plain name/search query
        print(f"DEBUG: Fallback to search query for: {channel_url_or_id}")
        return self._resolve_name_to_channel_id(channel_url_or_id)

    def _resolve_name_to_channel_id(self, name_or_handle: str) -> Optional[str]:
        try:
            print(f"DEBUG: Searching for channel: {name_or_handle}")
            search_response = self.youtube.search().list(
                part="snippet",
                q=name_or_handle,
                type="channel",
                maxResults=1
            ).execute()

            if search_response.get("items"):
                channel_id = search_response["items"][0]["snippet"]["channelId"]
                print(f"DEBUG: Resolved to channel ID: {channel_id}")
                return channel_id
            print(f"DEBUG: No items found in channel search for: {name_or_handle}")
            return None
        except Exception as e:
            print(f"DEBUG ERROR: Error resolving channel name: {e}")
            return None

    def fetch_uploads_playlist_id(self, channel_id: str) -> str:
        print(f"DEBUG: Fetching uploads playlist for channel: {channel_id}")
        response = self.youtube.channels().list(
            part="contentDetails",
            id=channel_id
        ).execute()

        if not response.get("items"):
            print(f"DEBUG ERROR: No channel items found for ID: {channel_id}")
            raise ValueError(f"No channel found with ID: {channel_id}")

        playlist_id = response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        print(f"DEBUG: Uploads playlist ID: {playlist_id}")
        return playlist_id

    def fetch_videos(self, playlist_id: str, max_videos: int = 50) -> List[dict]:
        print(f"DEBUG: Fetching up to {max_videos} videos from playlist: {playlist_id}")
        videos = []
        next_page_token = None
        
        while len(videos) < max_videos:
            try:
                response = self.youtube.playlistItems().list(
                    part="contentDetails,snippet",
                    playlistId=playlist_id,
                    maxResults=min(50, max_videos - len(videos)),
                    pageToken=next_page_token
                ).execute()

                items = response.get('items', [])
                print(f"DEBUG: Fetched {len(items)} items in this page")
                
                for item in items:
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
            except Exception as e:
                print(f"DEBUG ERROR: Error fetching playlist items: {e}")
                break
                
        print(f"DEBUG: Total videos collected: {len(videos)}")
        return videos

    def get_transcript(self, video_id: str) -> List[dict]:
        print(f"DEBUG: Attempting to fetch transcript for video: {video_id}")
        try:
            ytt_api = YouTubeTranscriptApi()
            # Try fetching in multiple languages
            transcript = ytt_api.fetch(video_id, languages=['en', 'en-US', 'en-GB'])
            data = transcript.to_raw_data()
            print(f"DEBUG: Successfully fetched transcript for {video_id} ({len(data)} segments)")
            return data
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            print(f"DEBUG: No transcript found/enabled for {video_id}: {type(e).__name__}")
            return []
        except Exception as e:
            print(f"DEBUG ERROR: Unexpected error fetching transcript for {video_id}: {e}")
            # Log the full exception for better debugging in Vercel logs
            import traceback
            traceback.print_exc()
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

@app.get("/")
@app.get("/api/search")
async def search(
    request: Request,
    channel_url: str = Query(...),
    keyword: str = Query(...),
    max_videos: int = Query(20),
    published_after: Optional[str] = Query(None),
):
    print(f"DEBUG: --- New Search Request ---")
    print(f"DEBUG: URL: {request.url}")
    print(f"DEBUG: Params: channel_url={channel_url}, keyword={keyword}, max_videos={max_videos}, published_after={published_after}")
    
    api_key = os.getenv("YT_API_KEY")
    if not api_key:
        print("DEBUG ERROR: YT_API_KEY environment variable is NOT SET")
        raise HTTPException(status_code=500, detail="YouTube API key not configured")
    
    # Check for empty or whitespace-only key
    if not api_key.strip():
        print("DEBUG ERROR: YT_API_KEY is empty or whitespace")
        raise HTTPException(status_code=500, detail="YouTube API key is empty")

    print(f"DEBUG: Using API Key (start): {api_key[:10]}...")
    
    service = YouTubeService(api_key)
    
    try:
        channel_id = service.resolve_channel_id(channel_url)
        if not channel_id:
            print(f"DEBUG ERROR: Could not resolve channel ID for {channel_url}")
            raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

        playlist_id = service.fetch_uploads_playlist_id(channel_id)
        # Fetch more videos if we have a date filter to ensure we get enough
        fetch_count = max_videos * 5 if published_after else max_videos
        videos = service.fetch_videos(playlist_id, max_videos=fetch_count)

        if not videos:
            print(f"DEBUG: No videos found in playlist {playlist_id}")
            return []

        # Filter by published_after date if provided
        if published_after:
            print(f"DEBUG: Filtering videos published after {published_after}")
            try:
                cutoff_date = datetime.fromisoformat(published_after.replace('Z', '+00:00'))
                original_count = len(videos)
                videos = [
                    v for v in videos
                    if datetime.fromisoformat(v['publishedAt'].replace('Z', '+00:00')) >= cutoff_date
                ][:max_videos]
                print(f"DEBUG: Filtered from {original_count} to {len(videos)} videos")
            except ValueError as e:
                print(f"DEBUG ERROR: Invalid date format {published_after}: {e}")
                pass

        results = []
        for video in videos:
            print(f"DEBUG: Examining video: {video['id']} - {video['title']}")
            transcript = service.get_transcript(video["id"])
            if transcript:
                matches = service.search_in_transcript(transcript, keyword)
                if matches:
                    print(f"DEBUG: Found {len(matches)} matches in {video['id']}")
                    results.append(SearchResult(
                        video_id=video["id"],
                        title=video["title"],
                        published_at=video["publishedAt"],
                        thumbnail=video["thumbnail"],
                        matches=matches
                    ))
                else:
                    print(f"DEBUG: No keyword matches in {video['id']}")
            else:
                print(f"DEBUG: No transcript found for {video['id']}, skipping.")
        
        print(f"DEBUG: Returning {len(results)} results")
        return results
    except HTTPException:
        raise
    except Exception as e:
        print(f"DEBUG ERROR: Global search error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/search/debug")
async def debug():
    return {
        "env_keys": list(os.environ.keys()),
        "yt_api_key_set": bool(os.getenv("YT_API_KEY")),
        "python_version": sys.version,
    }
