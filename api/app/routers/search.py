import json
import os
import re
from datetime import datetime
from typing import Any, Iterator, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.transcript_index import TranscriptIndexService
from ..services.youtube import (
    SUPPORTED_TRANSCRIPT_LANGUAGES as SUPPORTED_SEARCH_LANGUAGES,
    YouTubeService,
    human_script_variants,
    normalize_language_code,
)

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def detect_query_language(keyword: str) -> str:
    return "hi" if DEVANAGARI_RE.search(keyword or "") else "en"


def transcript_language_orders(query_language: str) -> List[List[str]]:
    preferred = [query_language] + [code for code in SUPPORTED_SEARCH_LANGUAGES if code != query_language]
    orders: List[List[str]] = [preferred]

    for language in preferred[1:]:
        order = [language] + [code for code in preferred if code != language]
        if order not in orders:
            orders.append(order)

    return orders


router = APIRouter()


def get_yt_service():
    api_key = os.getenv("YT_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="YouTube API key not configured")
    return YouTubeService(api_key)


def get_index_service():
    return TranscriptIndexService()


class SearchResult(BaseModel):
    video_id: str
    title: str
    published_at: str
    thumbnail: str
    transcript_language_code: str
    transcript_language_label: str
    search_terms_used: List[str]
    matches: List[dict]


class VideoListRequest(BaseModel):
    channel_url: str
    max_videos: int = 20
    published_after: Optional[str] = None
    exclude_shorts: bool = False


class VideoListResponse(BaseModel):
    channel_id: str
    videos: List[dict]


class IndexChannelRequest(BaseModel):
    channel_url: str
    max_videos: int = 20
    published_after: Optional[str] = None
    exclude_shorts: bool = False
    force_refresh: bool = False


class IndexChannelResponse(BaseModel):
    channel_id: str
    videos_considered: int
    videos_indexed: int
    transcripts_indexed: int
    videos_skipped: int
    index_stats: dict[str, int]


class VideoInput(BaseModel):
    id: str
    title: str
    publishedAt: str
    thumbnail: str


class SegmentInput(BaseModel):
    start: float
    duration: float
    text: str


class TranscriptInput(BaseModel):
    language_code: str
    language_label: str
    is_generated: bool
    segments: List[SegmentInput]


class MatchRequest(BaseModel):
    keyword: str
    video: VideoInput
    transcript: TranscriptInput


class MatchResponse(BaseModel):
    match_result: Optional[SearchResult] = None


class IndexTranscriptRequest(BaseModel):
    channel_id: str
    source_url: str
    video: VideoInput
    transcript: TranscriptInput


class IndexTranscriptResponse(BaseModel):
    stored: int


def _fetch_channel_videos(
    service: YouTubeService,
    channel_id: str,
    max_videos: int,
    published_after: Optional[str],
    exclude_shorts: bool,
) -> List[dict]:
    playlist_id = service.fetch_uploads_playlist_id(channel_id)
    fetch_count = max_videos * 3 if (published_after or exclude_shorts) else max_videos
    videos = service.fetch_videos(playlist_id, max_videos=fetch_count, exclude_shorts=exclude_shorts)

    if published_after:
        try:
            cutoff_date = datetime.fromisoformat(published_after.replace("Z", "+00:00"))
            videos = [
                video
                for video in videos
                if datetime.fromisoformat(video["publishedAt"].replace("Z", "+00:00")) >= cutoff_date
            ][:max_videos]
        except ValueError:
            pass

    return videos


def _build_match_result(
    service: YouTubeService,
    keyword: str,
    video_id: str,
    title: str,
    published_at: str,
    thumbnail: str,
    transcript_data: dict,
) -> Optional[SearchResult]:
    query_language = detect_query_language(keyword)
    search_terms = human_script_variants(keyword)
    transcript_language = normalize_language_code(transcript_data.get("language_code"))
    segments = transcript_data.get("segments") or []
    if not segments:
        return None

    transcript_search_terms = service.expand_search_terms_for_transcript(
        search_terms,
        segments,
        transcript_language or query_language,
    )

    matches = service.search_in_transcript(
        segments,
        transcript_search_terms,
        transcript_language=transcript_language or query_language,
    )

    if not matches:
        return None

    return SearchResult(
        video_id=video_id,
        title=title,
        published_at=published_at,
        thumbnail=thumbnail,
        transcript_language_code=transcript_language or query_language,
        transcript_language_label=transcript_data.get("language_label") or transcript_language or query_language,
        search_terms_used=transcript_search_terms,
        matches=matches,
    )


def _get_indexed_match(
    service: YouTubeService,
    index_service: TranscriptIndexService,
    video: dict,
    keyword: str,
    preferred_language_orders: Sequence[Sequence[str]],
) -> Optional[SearchResult]:
    tried_transcript_languages = set()

    for language_order in preferred_language_orders:
        for language in language_order:
            transcript_data = index_service.get_transcript(video["id"], language)
            if not transcript_data or not transcript_data.get("segments"):
                continue

            transcript_language = normalize_language_code(transcript_data.get("language_code"))
            if transcript_language in tried_transcript_languages:
                continue

            tried_transcript_languages.add(transcript_language)
            match_result = _build_match_result(
                service=service,
                keyword=keyword,
                video_id=video["id"],
                title=video["title"],
                published_at=video["publishedAt"],
                thumbnail=video["thumbnail"],
                transcript_data=transcript_data,
            )
            if match_result:
                return match_result

    return None


def _get_live_match_and_cacheable_transcripts(
    service: YouTubeService,
    video: dict,
    keyword: str,
    preferred_language_orders: Sequence[Sequence[str]],
) -> Tuple[Optional[SearchResult], List[dict]]:
    tried_transcript_languages = set()
    cacheable_transcripts: List[dict] = []

    for language_order in preferred_language_orders:
        transcript_data = service.get_transcript(video["id"], preferred_languages=list(language_order))
        if not transcript_data or not transcript_data.get("segments"):
            continue

        transcript_language = normalize_language_code(transcript_data.get("language_code"))
        if transcript_language in tried_transcript_languages:
            continue

        tried_transcript_languages.add(transcript_language)
        cacheable_transcripts.append(transcript_data)

        match_result = _build_match_result(
            service=service,
            keyword=keyword,
            video_id=video["id"],
            title=video["title"],
            published_at=video["publishedAt"],
            thumbnail=video["thumbnail"],
            transcript_data=transcript_data,
        )
        if match_result:
            return match_result, cacheable_transcripts

    return None, cacheable_transcripts


def _fetch_transcripts_for_index(service: YouTubeService, video_id: str) -> List[dict]:
    transcripts: List[dict] = []
    seen_languages = set()

    for language in SUPPORTED_SEARCH_LANGUAGES:
        transcript_data = service.get_transcript(video_id, preferred_languages=[language])
        if not transcript_data or not transcript_data.get("segments"):
            continue

        transcript_language = normalize_language_code(transcript_data.get("language_code"))
        if not transcript_language or transcript_language in seen_languages:
            continue

        seen_languages.add(transcript_language)
        transcripts.append(transcript_data)

    return transcripts


def _search_stream(
    service: YouTubeService,
    index_service: TranscriptIndexService,
    channel_url: str,
    channel_id: str,
    keyword: str,
    max_videos: int,
    published_after: Optional[str],
    exclude_shorts: bool,
    skip_live: bool = False,
) -> Iterator[str]:
    try:
        videos = _fetch_channel_videos(
            service=service,
            channel_id=channel_id,
            max_videos=max_videos,
            published_after=published_after,
            exclude_shorts=exclude_shorts,
        )

        query_language = detect_query_language(keyword)
        preferred_language_orders = transcript_language_orders(query_language)
        search_terms = human_script_variants(keyword)

        video_ids = [video["id"] for video in videos if video.get("id")]
        indexed_video_ids = index_service.get_indexed_video_ids(channel_id, video_ids)
        candidate_indexed_video_ids = index_service.find_candidate_video_ids(list(indexed_video_ids), search_terms)

        indexed_candidates = [video for video in videos if video["id"] in candidate_indexed_video_ids]
        indexed_remainder = [
            video
            for video in videos
            if video["id"] in indexed_video_ids and video["id"] not in candidate_indexed_video_ids
        ]
        live_videos = [video for video in videos if video["id"] not in indexed_video_ids]

        meta_payload = {
            "channel_id": channel_id,
            "total": len(videos),
            "indexed": len(indexed_video_ids),
            "indexed_candidates": len(indexed_candidates),
            "indexed_remainder": len(indexed_remainder),
            "live": len(live_videos),
            "skip_live": skip_live,
        }
        yield f"event: meta\ndata: {json.dumps(meta_payload)}\n\n"

        for batch in (indexed_candidates, indexed_remainder):
            for video in batch:
                try:
                    match_result = _get_indexed_match(
                        service=service,
                        index_service=index_service,
                        video=video,
                        keyword=keyword,
                        preferred_language_orders=preferred_language_orders,
                    )
                    if match_result:
                        yield f"data: {match_result.model_dump_json()}\n\n"
                except Exception:
                    pass

        if skip_live:
            # Hand un-indexed videos back to the client so it can fetch transcripts
            # locally (e.g. an extension's service worker) and call /api/match.
            payload = {"videos": live_videos}
            yield f"event: unindexed_videos\ndata: {json.dumps(payload)}\n\n"
        else:
            for video in live_videos:
                try:
                    match_result, cacheable_transcripts = _get_live_match_and_cacheable_transcripts(
                        service=service,
                        video=video,
                        keyword=keyword,
                        preferred_language_orders=preferred_language_orders,
                    )
                    if cacheable_transcripts:
                        try:
                            index_service.cache_video_transcripts(
                                channel_id=channel_id,
                                source_url=channel_url,
                                video=video,
                                transcripts=cacheable_transcripts,
                            )
                        except Exception:
                            pass

                    if match_result:
                        yield f"data: {match_result.model_dump_json()}\n\n"
                except Exception:
                    pass

        yield "event: done\ndata: {}\n\n"

    except Exception:
        yield f"event: error\ndata: {json.dumps({'detail': 'An internal server error occurred.', 'status': 500})}\n\n"


@router.get("/transcript/{video_id}")
async def get_transcript(
    video_id: str,
    lang: str = "en",
    service: YouTubeService = Depends(get_yt_service),
):
    preferred = [lang, "en", "hi"]
    result = service.get_transcript(video_id, preferred_languages=preferred)
    if not result:
        raise HTTPException(status_code=404, detail="No transcript available")
    return result


@router.get("/search")
async def search(
    channel_url: str,
    keyword: str,
    max_videos: int = 20,
    published_after: Optional[str] = None,
    exclude_shorts: bool = False,
    skip_live: bool = False,
    service: YouTubeService = Depends(get_yt_service),
    index_service: TranscriptIndexService = Depends(get_index_service),
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

    return StreamingResponse(
        _search_stream(
            service=service,
            index_service=index_service,
            channel_url=channel_url,
            channel_id=channel_id,
            keyword=keyword,
            max_videos=max_videos,
            published_after=published_after,
            exclude_shorts=exclude_shorts,
            skip_live=skip_live,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/suggest-channels")
async def suggest_channels(
    q: str = "",
    service: YouTubeService = Depends(get_yt_service),
):
    if len(q.strip()) < 2:
        return []
    try:
        response = service.youtube.search().list(
            part="snippet",
            q=q,
            type="channel",
            maxResults=5,
        ).execute()
        return [
            {
                "id": item["id"]["channelId"],
                "title": item["snippet"]["title"],
                "thumbnail": item["snippet"].get("thumbnails", {}).get("default", {}).get("url", ""),
            }
            for item in response.get("items", [])
        ]
    except Exception:
        return []


@router.get("/resolve-channel")
async def resolve_channel(
    channel_url: str,
    service: YouTubeService = Depends(get_yt_service),
):
    channel_id = service.resolve_channel_id(channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Could not resolve channel")
    return {"channel_id": channel_id}


@router.post("/videos", response_model=VideoListResponse)
async def list_videos(
    req: VideoListRequest,
    service: YouTubeService = Depends(get_yt_service),
):
    channel_id = service.resolve_channel_id(req.channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

    videos = _fetch_channel_videos(
        service=service,
        channel_id=channel_id,
        max_videos=req.max_videos,
        published_after=req.published_after,
        exclude_shorts=req.exclude_shorts,
    )
    return VideoListResponse(channel_id=channel_id, videos=videos)


@router.post("/index/channel", response_model=IndexChannelResponse)
async def index_channel(
    req: IndexChannelRequest,
    service: YouTubeService = Depends(get_yt_service),
    index_service: TranscriptIndexService = Depends(get_index_service),
):
    channel_id = service.resolve_channel_id(req.channel_url)
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube channel URL or ID")

    videos = _fetch_channel_videos(
        service=service,
        channel_id=channel_id,
        max_videos=req.max_videos,
        published_after=req.published_after,
        exclude_shorts=req.exclude_shorts,
    )

    existing_indexed_video_ids = set()
    if not req.force_refresh:
        existing_indexed_video_ids = index_service.get_indexed_video_ids(
            channel_id,
            [video["id"] for video in videos if video.get("id")],
        )

    videos_indexed = 0
    transcripts_indexed = 0
    videos_skipped = 0

    for video in videos:
        if not req.force_refresh and video["id"] in existing_indexed_video_ids:
            videos_skipped += 1
            continue

        try:
            transcripts = _fetch_transcripts_for_index(service, video["id"])
            if not transcripts:
                continue

            stored_count = index_service.cache_video_transcripts(
                channel_id=channel_id,
                source_url=req.channel_url,
                video=video,
                transcripts=transcripts,
            )
            if stored_count:
                videos_indexed += 1
                transcripts_indexed += stored_count
        except Exception:
            continue

    return IndexChannelResponse(
        channel_id=channel_id,
        videos_considered=len(videos),
        videos_indexed=videos_indexed,
        transcripts_indexed=transcripts_indexed,
        videos_skipped=videos_skipped,
        index_stats=index_service.get_channel_stats(channel_id),
    )


@router.post("/index/transcript", response_model=IndexTranscriptResponse)
async def index_transcript(
    req: IndexTranscriptRequest,
    service: YouTubeService = Depends(get_yt_service),
    index_service: TranscriptIndexService = Depends(get_index_service),
):
    # Trust source_url, never the client-provided channel_id. Otherwise any
    # caller could pollute the index for any channel.
    resolved_id = service.resolve_channel_id(req.source_url)
    if not resolved_id:
        raise HTTPException(status_code=400, detail="Could not resolve channel from source_url")
    if req.channel_id != resolved_id:
        raise HTTPException(status_code=400, detail="channel_id does not match source_url")

    transcript_data = {
        "language_code": req.transcript.language_code,
        "language_label": req.transcript.language_label,
        "is_generated": req.transcript.is_generated,
        "segments": [segment.model_dump() for segment in req.transcript.segments],
    }
    video_data = req.video.model_dump()

    stored = index_service.cache_video_transcripts(
        channel_id=resolved_id,
        source_url=req.source_url,
        video=video_data,
        transcripts=[transcript_data],
    )
    return IndexTranscriptResponse(stored=stored)


@router.post("/match", response_model=MatchResponse)
async def match_transcript(
    req: MatchRequest,
    service: YouTubeService = Depends(get_yt_service),
):
    transcript_data = {
        "language_code": req.transcript.language_code,
        "language_label": req.transcript.language_label,
        "is_generated": req.transcript.is_generated,
        "segments": [segment.model_dump() for segment in req.transcript.segments],
    }

    match_result = _build_match_result(
        service=service,
        keyword=req.keyword,
        video_id=req.video.id,
        title=req.video.title,
        published_at=req.video.publishedAt,
        thumbnail=req.video.thumbnail,
        transcript_data=transcript_data,
    )

    return MatchResponse(match_result=match_result)
