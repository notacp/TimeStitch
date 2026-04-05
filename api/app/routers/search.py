from fastapi import APIRouter, HTTPException, Query, Depends
from ..services.youtube import YouTubeService
from typing import List, Optional
from datetime import datetime
import os
from pydantic import BaseModel

def translate_keyword(keyword: str, target_lang: str) -> Optional[str]:
    """Translate keyword to target language. Returns None silently if translation fails."""
    try:
        from deep_translator import GoogleTranslator
        translated = GoogleTranslator(source="auto", target=target_lang).translate(keyword)
        # Only return if it's actually different (i.e. a real translation happened)
        if translated and translated.lower() != keyword.lower():
            print(f"DEBUG: Translated '{keyword}' → '{translated}' ({target_lang})")
            return translated
    except Exception as e:
        print(f"DEBUG: Translation failed ({target_lang}): {e}")
    return None

router = APIRouter()

def get_yt_service():
    api_key = os.getenv("YT_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="YouTube API key not configured")
    proxy_url = os.getenv("PROXY_URL")
    worker_url = os.getenv("TRANSCRIPT_WORKER_URL")
    if worker_url:
        print(f"DEBUG: Using Cloudflare Worker for transcripts: {worker_url}")
    elif proxy_url:
        print("DEBUG: PROXY_URL is configured for transcript requests.")
    else:
        print("DEBUG: No Worker or proxy configured — using direct transcript API (local dev only).")
    return YouTubeService(api_key, proxy_url=proxy_url, worker_url=worker_url)

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
    exclude_shorts: bool = False,
    service: YouTubeService = Depends(get_yt_service)
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

    try:
        playlist_id = service.fetch_uploads_playlist_id(channel_id)
        # Fetch more videos initially to account for date filtering and Shorts exclusion
        fetch_count = max_videos * 3 if (published_after or exclude_shorts) else max_videos
        videos = service.fetch_videos(playlist_id, max_videos=fetch_count, exclude_shorts=exclude_shorts)

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

        # Translate keyword to Hindi once — reused for all videos in this search
        hindi_keyword = translate_keyword(keyword, "hi")
        extra_keywords = [hindi_keyword] if hindi_keyword else []

        results = []
        for video in videos:
            print(f"DEBUG: Analyzing Video {video['id']}: '{video['title']}'...")

            # Catch exceptions here so we don't drop the entire request if one transcript fails
            try:
                transcript = service.get_transcript(video["id"])
                if transcript:
                    print(f"DEBUG: Transcript found for {video['id']}. Searching for '{keyword}'...")
                    matches = service.search_in_transcript(transcript, keyword, extra_keywords=extra_keywords)
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
            except Exception as inner_e:
                print(f"DEBUG ERROR: Failed analyzing video {video['id']}: {inner_e}")
                # We log it, but let the loop continue or let block_detected trigger 403 later

        # If we got no results and proxy failures happened, surface a sanitized 502.
        if not results and getattr(service, "proxy_error_detected", False):
            print("DEBUG ERROR: Search finished but proxy errors were detected. Raising 502.")
            raise HTTPException(
                status_code=502,
                detail="Proxy connection failed. Verify PROXY_URL format and credentials."
            )

        # If worker is configured but every transcript call failed, surface a 502.
        if not results and getattr(service, "worker_url", None) and getattr(service, "worker_failures", 0) > 0:
            print("DEBUG ERROR: Search finished but all Worker transcript calls failed. Raising 502.")
            raise HTTPException(
                status_code=502,
                detail="Cloudflare Worker failed to fetch transcripts. Check that the Worker is deployed and TRANSCRIPT_WORKER_URL is correct."
            )

        # If we got no results and a block was detected, surface the 403.
        if not results and service.block_detected:
            print("DEBUG ERROR: Search finished but IP block was detected. Raising 403.")
            if getattr(service, "proxy_url", None):
                detail = (
                    "YouTube blocked the request even with PROXY_URL. "
                    "Verify proxy quality, rotation, and credentials."
                )
            else:
                detail = "YouTube blocked the request. Please configure PROXY_URL."
            raise HTTPException(
                status_code=403, 
                detail=detail
            )

        print(f"DEBUG: Returning {len(results)} total video results")
        return results
        
    except HTTPException:
        # Re-raise HTTPExceptions (like our 400 or 403)
        raise
    except Exception as e:
        # Sanitize internal 500 errors
        print(f"DEBUG ERROR: Unexpected error in search router: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="An internal server error occurred.")

@router.get("/resolve-channel")
async def resolve_channel(
    channel_url: str,
    service: YouTubeService = Depends(get_yt_service)
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Could not resolve channel")
    return {"channel_id": channel_id}
