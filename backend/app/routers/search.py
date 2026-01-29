from fastapi import APIRouter, HTTPException, Query, Depends
from app.services.youtube import YouTubeService
from typing import List, Optional
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
    max_videos: int = 10,
    service: YouTubeService = Depends(get_yt_service)
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

    try:
        playlist_id = service.fetch_uploads_playlist_id(channel_id)
        videos = service.fetch_videos(playlist_id, max_videos=max_videos)
        
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

@router.get("/resolve-channel")
async def resolve_channel(
    channel_url: str,
    service: YouTubeService = Depends(get_yt_service)
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Could not resolve channel")
    return {"channel_id": channel_id}
