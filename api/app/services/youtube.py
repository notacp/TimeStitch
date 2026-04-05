import os
import re
from typing import List, Optional, Dict, Any

def _keyword_matches(text: str, keyword: str) -> bool:
    """Case-insensitive whole-word match so 'CRED' doesn't match 'incredible'."""
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', text, re.IGNORECASE | re.UNICODE))
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

class YouTubeService:
    def __init__(self, api_key: str, proxy_url: Optional[str] = None, worker_url: Optional[str] = None):
        self.api_key = api_key
        self.proxy_url = proxy_url.strip() if proxy_url and proxy_url.strip() else None
        self.worker_url = worker_url.rstrip("/") if worker_url and worker_url.strip() else None
        self.youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)
        self.block_detected = False
        self.proxy_error_detected = False
        self.worker_failures = 0

    def _get_http_client(self) -> Any:
        import requests
        import random
        
        session = requests.Session()
        session.trust_env = False
        
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

    def fetch_videos(self, playlist_id: str, max_videos: int = 50, exclude_shorts: bool = False) -> List[Dict[str, Any]]:
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

        if exclude_shorts and videos:
            videos = self._filter_out_shorts(videos)

        return videos

    def _filter_out_shorts(self, videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove Shorts (duration <= 60s) via a batched videos.list call."""
        import re
        video_ids = [v["id"] for v in videos if v["id"]]

        # videos.list accepts up to 50 IDs per request
        durations = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            response = self.youtube.videos().list(
                part="contentDetails",
                id=",".join(batch)
            ).execute()
            for item in response.get("items", []):
                duration_str = item.get("contentDetails", {}).get("duration", "PT0S")
                # ISO 8601 duration e.g. PT1M30S, PT59S, P0D
                total_seconds = 0
                for value, unit in re.findall(r"(\d+)([HMSD])", duration_str):
                    if unit == "H": total_seconds += int(value) * 3600
                    elif unit == "M": total_seconds += int(value) * 60
                    elif unit == "S": total_seconds += int(value)
                durations[item["id"]] = total_seconds

        filtered = [v for v in videos if durations.get(v["id"], 61) > 60]
        print(f"DEBUG: Filtered out {len(videos) - len(filtered)} Shorts (≤60s) from {len(videos)} videos")
        return filtered

    def get_transcript(self, video_id: str) -> List[Dict[str, Any]]:
        """Fetch transcript via Cloudflare Worker (production) or youtube-transcript-api (local dev)."""
        if self.worker_url:
            return self._get_transcript_from_worker(video_id)
        return self._get_transcript_from_api(video_id)

    def _get_transcript_from_worker(self, video_id: str) -> List[Dict[str, Any]]:
        """Call the Cloudflare Worker which fetches transcripts from YouTube's edge IPs."""
        import requests as req
        url = f"{self.worker_url}/transcript"
        try:
            print(f"DEBUG: Fetching transcript via Worker for {video_id}")
            response = req.get(url, params={"video_id": video_id}, timeout=30)
            if response.status_code == 200:
                return response.json()
            if response.status_code == 404:
                # Worker signals no captions available
                return []
            error = response.json().get("error", f"Worker returned {response.status_code}")
            print(f"DEBUG ERROR: Worker error for {video_id}: {error}")
            raise Exception(error)
        except Exception as e:
            self.worker_failures += 1
            print(f"DEBUG ERROR: Worker request failed for {video_id}: {e}")
            raise

    def _get_transcript_from_api(self, video_id: str) -> List[Dict[str, Any]]:
        """Fallback: fetch transcript using youtube-transcript-api (for local dev)."""
        try:
            http_client = self._get_http_client()
            ytt_api = YouTubeTranscriptApi(http_client=http_client)
            transcript = ytt_api.fetch(video_id, languages=['en', 'en-US', 'hi'])
            return transcript.to_raw_data()
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            print(f"DEBUG: Transcript API error for {video_id}: {type(e).__name__}")
            return []
        except Exception as e:
            error_msg = str(e)
            error_msg_lower = error_msg.lower()

            if (
                "blocking requests from your ip" in error_msg_lower
                or "blocked" in error_msg_lower
                or "429" in error_msg_lower
                or "too many requests" in error_msg_lower
            ):
                print(
                    f"DEBUG ERROR: YouTube blocked transcript request for {video_id}. "
                    f"proxy_configured={bool(self.proxy_url)}"
                )
                self.block_detected = True
            elif (
                "proxy" in error_msg_lower
                or "407" in error_msg_lower
                or "tunnel connection failed" in error_msg_lower
                or "cannot connect to proxy" in error_msg_lower
                or "proxyerror" in error_msg_lower
            ):
                print(
                    f"DEBUG ERROR: Proxy failure while fetching transcript for {video_id}: {error_msg}"
                )
                self.proxy_error_detected = True
            else:
                print(f"DEBUG ERROR: Unexpected error fetching transcript for {video_id}: {error_msg}")
            raise


    def search_in_transcript(self, transcript: List[Dict[str, Any]], keyword: str, extra_keywords: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Search transcript for keyword and any extra translated variants."""
        all_keywords = [keyword] + list(extra_keywords or [])
        seen_starts = set()
        matches = []
        for i, segment in enumerate(transcript):
            if any(_keyword_matches(segment['text'], k) for k in all_keywords) and segment['start'] not in seen_starts:
                seen_starts.add(segment['start'])
                matches.append({
                    "start": segment['start'],
                    "text": segment['text'],
                    "context_before": transcript[i-1]['text'] if i > 0 else "",
                    "context_after": transcript[i+1]['text'] if i < len(transcript) - 1 else ""
                })
        return matches
