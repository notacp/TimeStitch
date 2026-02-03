from fastapi import APIRouter, HTTPException, Query, Depends
from ..services.youtube import YouTubeService
from typing import List, Optional
from datetime import datetime
import os
from pydantic import BaseModel

router = APIRouter()

def get_yt_service():
    api_key = os.getenv("YT_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="YouTube API key not configured")
    return YouTubeService(api_key)

class SearchResult(BaseModel):
    video_id: str
    title: str
    published_at: str
    thumbnail: str
    matches: List[dict]

@router.get("/search", response_model=List[SearchResult])
async def search(
    channel_url: str,
    keyword: str,
    max_videos: int = 20,
    published_after: Optional[str] = None,
    service: YouTubeService = Depends(get_yt_service)
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

    try:
        playlist_id = service.fetch_uploads_playlist_id(channel_id)
        # Fetch more videos initially to account for date filtering
        fetch_count = max_videos * 3 if published_after else max_videos
        videos = service.fetch_videos(playlist_id, max_videos=fetch_count)

        # Filter by published_after date if provided
        if published_after:
            try:
                cutoff_date = datetime.fromisoformat(published_after.replace('Z', '+00:00'))
                videos = [
                    v for v in videos
                    if datetime.fromisoformat(v['publishedAt'].replace('Z', '+00:00')) >= cutoff_date
                ][:max_videos]  # Limit after filtering
            except ValueError as e:
                print(f"DEBUG: Invalid date format: {published_after}, error: {e}")

        print(f"DEBUG: Found {len(videos)} videos in playlist {playlist_id} (after date filter)")
        
        results = []
        for video in videos:
            print(f"DEBUG: Analyzing Video {video['id']}: '{video['title']}'...")
            transcript = service.get_transcript(video["id"])
            if transcript:
                print(f"DEBUG: Transcript found for {video['id']}. Searching for '{keyword}'...")
                matches = service.search_in_transcript(transcript, keyword)
                if matches:
                    print(f"DEBUG: FOUND {len(matches)} matches in {video['id']}")
                    results.append(SearchResult(
                        video_id=video["id"],
                        title=video["title"],
                        published_at=video["publishedAt"],
                        thumbnail=video["thumbnail"],
                        matches=matches
                    ))
                else:
                    print(f"DEBUG: No matches found in {video['id']}")
            else:
                print(f"DEBUG: No transcript found for {video['id']}")
        
        print(f"DEBUG: Returning {len(results)} total video results")
        return results
    except Exception as e:
        print(f"DEBUG: ERROR in search: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/resolve-channel")
async def resolve_channel(
    channel_url: str,
    service: YouTubeService = Depends(get_yt_service)
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Could not resolve channel")
    return {"channel_id": channel_id}
