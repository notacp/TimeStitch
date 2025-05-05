import os
from dotenv import load_dotenv
import sys
import re
import time # Added for sleep in retries
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type # Removed tenacity
from typing import List, Tuple, Optional, Dict, Any, Union, Generator
from datetime import datetime, date, timezone
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import streamlit as st # Changed from gradio

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
YT_API_KEY = os.getenv("YT_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # Optional, keep for potential future use

# Validate essential API keys - Check happens within Streamlit UI now
# if not YT_API_KEY:
#     print("Error: YouTube API key (YT_API_KEY) not found in environment variables.", file=sys.stderr)
#     print("Please create a .env file in the root directory and add YT_API_KEY=<your_key>", file=sys.stderr)
    # In a real deployment (like Streamlit Cloud), secrets would be set in the environment.
    # For local development, ensure the .env file is correctly set up.
    # sys.exit(1) # Exit if the key is crucial for the app to run at all. - Handled in UI

print("Environment variables loaded.") # Placeholder print for verification

# --- YouTube API Helper Functions ---

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# Configure retry mechanism for API calls
RETRY_ATTEMPTS = 3
RETRY_WAIT_SECONDS = 2

# Custom exception for clearer error handling
class YouTubeChannelError(Exception):
    pass

def _resolve_name_to_channel_id_sync(name_or_handle: str, api_key: str) -> str | None:
    """
    Synchronously resolves a username, custom URL, or handle to a channel ID using search.list.
    """
    st.write(f"Attempting to resolve '{name_or_handle}' to a channel ID...") # Use st.write
    if not api_key:
        raise ValueError("YouTube API Key is not configured.")
    try:
        youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)
        search_response = youtube.search().list(
            part="snippet",
            q=name_or_handle, # Search query is the name/handle
            type="channel",   # We are looking for a channel
            maxResults=1      # We only need the most likely match
        ).execute()

        if search_response.get("items"):
            # The first item should be the channel we're looking for
            channel_id = search_response["items"][0]["snippet"]["channelId"]
            channel_title = search_response["items"][0]["snippet"]["title"]
            st.write(f"Resolved '{name_or_handle}' to Channel ID: {channel_id} (Title: {channel_title})") # Use st.write
            return channel_id
        else:
            # If no items are returned, the handle/name likely doesn't exist or isn't searchable this way
            st.warning(f"Could not resolve '{name_or_handle}' to a channel ID via search.") # Use st.warning
            return None # Indicate resolution failure

    except HttpError as e:
        # Handle API errors during the search call
        raise YouTubeChannelError(f"YouTube API error during name resolution for '{name_or_handle}': {e.resp.status} {e.content.decode()}") from e
    except Exception as e:
        # Catch potential other errors
        raise YouTubeChannelError(f"An unexpected error occurred resolving '{name_or_handle}': {e}") from e


def _extract_channel_id(channel_url_or_id: str, api_key: str) -> str | None:
    """
    Extracts YouTube Channel ID from various URL formats, resolving handles/vanity URLs if necessary.
    Requires API key for resolution.
    """
    if not channel_url_or_id:
        return None

    # 1. Direct Channel ID (UC...)
    if re.match(r"^UC[a-zA-Z0-9_-]{22}$", channel_url_or_id):
        st.write("Input appears to be a direct Channel ID.") # Use st.write
        return channel_url_or_id

    # 2. Standard Channel URL (/channel/UC...)
    match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", channel_url_or_id)
    if match:
        st.write("Found standard /channel/ URL.") # Use st.write
        return match.group(1)

    # 3. Handle URL (/@handle)
    match = re.search(r"youtube\.com/@([a-zA-Z0-9_.-]+)", channel_url_or_id)
    if match:
        handle = match.group(1)
        st.write(f"Found handle URL: @{handle}. Attempting resolution...") # Use st.write
        return _resolve_name_to_channel_id_sync(handle, api_key)

    # 4. Custom/Vanity URL (/c/name or /user/name)
    match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_.-]+)", channel_url_or_id)
    if match:
        name = match.group(1)
        st.write(f"Found custom/user URL: {name}. Attempting resolution...") # Use st.write
        return _resolve_name_to_channel_id_sync(name, api_key)

    # If none of the patterns match or resolution fails for handle/custom
    st.warning(f"Could not extract or resolve channel ID from input: {channel_url_or_id}") # Use st.warning
    return None


def fetch_playlist_id(channel_id: str, api_key: str) -> str:
    """Synchronous function to fetch uploads playlist ID."""
    st.write(f"Fetching uploads playlist ID for channel: {channel_id}...") # Use st.write
    if not api_key:
        raise ValueError("YouTube API Key is not configured.")
    try:
        youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)
        response = youtube.channels().list(
            part="contentDetails",
            id=channel_id
        ).execute()

        if not response.get("items"):
            raise YouTubeChannelError(f"No channel found with ID: {channel_id}")

        content_details = response["items"][0].get("contentDetails", {})
        related_playlists = content_details.get("relatedPlaylists", {})
        uploads_playlist_id = related_playlists.get("uploads")

        if not uploads_playlist_id:
             raise YouTubeChannelError(f"Could not find uploads playlist ID for channel: {channel_id}")

        st.write(f"Found uploads playlist ID: {uploads_playlist_id}") # Use st.write
        return uploads_playlist_id

    except HttpError as e:
        raise YouTubeChannelError(f"YouTube API error fetching playlist ID: {e.resp.status} {e.content.decode()}") from e
    except Exception as e:
        raise YouTubeChannelError(f"An unexpected error occurred fetching playlist ID: {e}") from e


def _fetch_video_details_page(playlist_id: str, api_key: str, page_token: Optional[str] = None) -> Tuple[List[Tuple[str, str, str]], Optional[str]]:
    """Fetches one page of video IDs, published dates, and titles from a playlist."""
    if not api_key:
        raise ValueError("YouTube API Key is not configured.")
    try:
        youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)
        request = youtube.playlistItems().list(
            part="contentDetails,snippet", # Already fetching snippet
            playlistId=playlist_id,
            maxResults=50, # Max allowed by API
            pageToken=page_token
        )
        response = request.execute()

        video_details = []
        for item in response.get('items', []):
            video_id = item.get('contentDetails', {}).get('videoId')
            snippet = item.get('snippet', {})
            published_at = snippet.get('publishedAt') # ISO 8601 format string
            title = snippet.get('title') # Get the video title
            # Add basic filtering for potentially deleted/private videos that might lack full details
            if video_id and published_at and title:
                video_details.append((video_id, published_at, title))
            # else: print(f"Skipping item due to missing data: {item.get('id')}") # Keep as comment or use st.warning

        next_page_token = response.get('nextPageToken')
        # Return list of (id, date_str, title) tuples
        return video_details, next_page_token

    except HttpError as e:
        raise YouTubeChannelError(f"YouTube API error fetching video details page: {e.resp.status} {e.content.decode()}") from e
    except Exception as e:
        raise YouTubeChannelError(f"An unexpected error occurred fetching video details page: {e}") from e


def fetch_all_video_details(playlist_id: str, api_key: str, max_videos: int) -> List[Tuple[str, str, str]]:
    """Fetches all video details (ID, publishedAt, title) handling pagination and retries."""
    st.write(f"Fetching up to {max_videos} video details for playlist: {playlist_id}...") # Use st.write
    all_details = []
    next_page_token = None
    fetch_attempt = 0
    max_fetch_attempts = RETRY_ATTEMPTS # Use constant
    page_count = 0

    # Placeholder for progress bar
    progress_bar = st.progress(0)
    status_text = st.empty()

    while True:
        try:
            page_count += 1
            status_text.text(f"Fetching video details page {page_count}...")
            details_page, next_page_token = _fetch_video_details_page(
                playlist_id, api_key, next_page_token
            )
            # st.write(f"Fetched {len(details_page)} video details this page.") # Can be verbose
            all_details.extend(details_page)

            # Update progress (estimate based on max_videos, might not be linear)
            progress = min(1.0, len(all_details) / max_videos if max_videos > 0 else 0)
            progress_bar.progress(progress)
            status_text.text(f"Fetched {len(all_details)} video details so far...")

            if len(all_details) >= max_videos:
                status_text.text(f"Reached max_videos limit ({max_videos}).")
                break
            if not next_page_token:
                status_text.text("No more pages of videos.")
                progress_bar.progress(1.0) # Mark as complete
                break
            fetch_attempt = 0 # Reset attempts on success
        except YouTubeChannelError as e:
            fetch_attempt += 1
            st.warning(f"Error fetching video details page: {e}. Attempt {fetch_attempt}/{max_fetch_attempts}") # Use st.warning
            if fetch_attempt >= max_fetch_attempts:
                raise YouTubeChannelError(f"Failed to fetch video details after {max_fetch_attempts} attempts.") from e
            time.sleep(RETRY_WAIT_SECONDS) # Use constant
        except Exception as e:
            st.error(f"Unexpected error during video details fetch pagination: {e}") # Use st.error
            raise # Reraise unexpected errors immediately

    # Truncate and return
    final_details = all_details[:max_videos]
    status_text.text(f"Finished fetching. Total video details collected: {len(final_details)}")
    time.sleep(1) # Keep final message visible briefly
    status_text.empty() # Clear status text
    progress_bar.empty() # Clear progress bar
    return final_details


# --- Transcript Fetching ---

_transcript_cache: Dict[str, List[Dict[str, Any]]] = {}

# Custom exception for transcript errors
class TranscriptFetchError(Exception):
    pass

def fetch_transcript(video_id: str) -> List[Dict[str, Any]]:
    """Synchronous function to fetch a transcript for a given video ID."""
    # st.write(f"Attempting transcript fetch for video ID: {video_id}") # Can be too verbose
    if video_id in _transcript_cache:
        # st.write(f"Using cached transcript for {video_id}")
        return _transcript_cache[video_id]
    try:
        # Fetch the transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'en-US']) # Prioritize English
        _transcript_cache[video_id] = transcript_list # Cache successful fetch
        return transcript_list
    except TranscriptsDisabled:
        raise TranscriptFetchError(f"Transcripts are disabled for video: {video_id}")
    except NoTranscriptFound:
        try:
             available_transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
             langs = [t.language for t in available_transcripts]
             raise TranscriptFetchError(f"No English transcript found for {video_id}. Available: {langs if langs else 'None'}")
        except Exception as inner_e:
             # This might happen if the video is unavailable after the initial fetch
             raise TranscriptFetchError(f"Could not fetch transcript or list available ones for {video_id}: {inner_e}")
    except Exception as e:
        # Catch other potential errors from the API
        raise TranscriptFetchError(f"An unexpected error occurred fetching transcript for {video_id}: {e}") from e


# --- Transcript Searching ---

def search_in_transcript(transcript: List[Dict[str, Any]], keyword: str) -> List[Dict[str, Any]]:
    """
    Searches for a keyword in the transcript text (case-insensitive).
    Returns a list of matching segments with context.
    """
    matches = []
    keyword_lower = keyword.lower()
    for i, segment in enumerate(transcript):
        if keyword_lower in segment['text'].lower():
            # Add context (previous and next segment if available)
            context_before = transcript[i-1]['text'] if i > 0 else ""
            context_after = transcript[i+1]['text'] if i < len(transcript) - 1 else ""
            match_info = {
                "start": segment['start'],
                "text": segment['text'],
                "context_before": context_before,
                "context_after": context_after,
            }
            matches.append(match_info)
    return matches


# --- Main Application Logic (to be added later) ---

# Updated test section

# ... rest of the application code (Streamlit interface etc.) ... 

# --- Constants ---
MAX_CONCURRENT_TASKS = 5 # Semaphore limit

# --- Core Processing Logic ---

# Helper to parse date string - simplified to focus on YYYY-MM-DD format
def parse_date(date_input: Union[str, date, None]) -> Optional[datetime]:
    """
    Parses string or date object into a timezone-aware datetime at the start of the day.
    """
    if not date_input:
        return None
    try:
        # If it's already a date object from st.date_input
        if isinstance(date_input, date):
            dt = datetime.combine(date_input, datetime.min.time())
        # If it's a string (e.g., from manual input or testing)
        elif isinstance(date_input, str):
             dt = datetime.strptime(date_input, "%Y-%m-%d")
        else:
            return None
        # Make timezone-aware (UTC)
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        st.warning(f"Invalid date format: {date_input}. Please use YYYY-MM-DD.") # Use st.warning
        return None

def _process_single_video(video_id: str, title: str, pub_date_str: str, keyword: str) -> List[str]:
    """Processes a single video: fetch transcript (with cache & retry), search, format results."""
    video_results = []
    print(f"[{video_id}] Processing '{title}'... Check cache.")
    try:
        # Check cache synchronously
        if video_id in _transcript_cache:
            print(f"Cache hit for transcript: {video_id}")
            transcript = _transcript_cache[video_id]
        else:
            print(f"Cache miss. Fetching transcript sync for: {video_id}")
            # Call the sync helper directly + Add manual retry logic
            transcript_fetch_attempt = 0
            transcript = None
            last_transcript_error = None
            while transcript_fetch_attempt < RETRY_ATTEMPTS:
                try:
                    transcript = fetch_transcript(video_id) # Use renamed function
                    break # Success
                except TranscriptFetchError as e:
                    transcript_fetch_attempt += 1
                    last_transcript_error = e
                    print(f"Transcript fetch error attempt {transcript_fetch_attempt}/{RETRY_ATTEMPTS} for {video_id}: {e}", file=sys.stderr)
                    if transcript_fetch_attempt < RETRY_ATTEMPTS:
                        time.sleep(RETRY_WAIT_SECONDS)
                except Exception as e: # Catch other potential errors
                    last_transcript_error = e
                    print(f"Unexpected transcript fetch error for {video_id}: {e}", file=sys.stderr)
                    break # Don't retry unexpected errors
            
            if transcript is None:
                # Raise the error to be caught by the outer loop
                raise last_transcript_error or TranscriptFetchError(f"Failed to fetch transcript for {video_id} after retries.")

            _transcript_cache[video_id] = transcript # Cache result
            print(f"Successfully fetched and cached transcript for: {video_id} ('{title}')")

        print(f"[{video_id}] Transcript obtained for '{title}'. Searching for '{keyword}'...")
        matches = search_in_transcript(transcript, keyword)
        print(f"[{video_id}] Search complete for '{title}'. Found {len(matches)} matches.")

        if matches:
            # Format results for this video
            video_results.append(f"### [{title}](https://www.youtube.com/watch?v={video_id})\n")
            for segment in matches:
                 start_time = segment.get('start', 0)
                 minutes = int(start_time // 60)
                 seconds = int(start_time % 60)
                 # Bold the keyword in the segment text using case-insensitive regex substitution
                 pattern = re.compile(re.escape(keyword), re.IGNORECASE)
                 highlighted_text = pattern.sub(r'**\g<0>**', segment['text'])
                 video_results.append(f"- [{minutes:02d}:{seconds:02d}](https://www.youtube.com/watch?v={video_id}&t={int(start_time)}s): {highlighted_text}\n")
            video_results.append("\n---\n")
        
        return video_results # Return formatted results list for this video

    except Exception as e:
        # Catch errors for this specific video and return a formatted warning string list
        print(f"[{video_id}] Error processing '{title}': {e}", file=sys.stderr)
        return [f"⚠️ Skipping video [{title}](https://www.youtube.com/watch?v={video_id}): `{e}`\n"]

def process_channel_search(
    channel_url_or_id: str,
    start_date_input: str,
    end_date_input: str,
    keyword: str,
    max_videos: int
) -> Generator[str, None, None]: # Updated return type
    """
    Process channel search synchronously.
    Yields status updates and returns results as a formatted Markdown string.
    """
    # Yield initial status
    yield "⏳ Searching... Please wait."

    found_matches = False
    results = []

    # 1. Validate Inputs (remains the same)
    if not keyword:
        yield "❌ Error: Please provide a keyword to search for."
        return
    if not channel_url_or_id:
        yield "❌ Error: Please provide a Channel URL or ID."
        return

    start_date = parse_date(start_date_input)
    end_date = parse_date(end_date_input)

    # Adjust end_date to be inclusive (end of the day)
    if end_date:
         end_date = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)


    if not start_date or not end_date:
        yield f"❌ Error: Invalid date format. Please use YYYY-MM-DD format. Start: {start_date_input}, End: {end_date_input}"
        return
    if start_date > end_date:
        yield f"❌ Error: Start Date ({start_date.date()}) must be before or the same as End Date ({end_date.date()})."
        return
    print(f"Date Range: {start_date.isoformat()} to {end_date.isoformat()}")


    try:
        # 2. Get Playlist ID
        channel_id = _extract_channel_id(channel_url_or_id, YT_API_KEY)
        if not channel_id:
            yield f"❌ Error: Could not extract or resolve a valid YouTube Channel ID from the input: '{channel_url_or_id}'. Please check the URL or ID."
            return
        if not YT_API_KEY: raise ValueError("YT_API_KEY is not set in environment variables.")
        playlist_id = fetch_playlist_id(channel_id, YT_API_KEY)

        # 3. Fetch Video Details using the new helper
        all_video_details = fetch_all_video_details(playlist_id, YT_API_KEY, int(max_videos))
        if not all_video_details:
            yield "ℹ️ No videos found for this channel in the specified timeframe or limit."
            return

        # 4. Filter Videos by Date
        filtered_videos = []
        warnings = []
        for video_id, pub_date_str, title in all_video_details:
            try:
                pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                if start_date <= pub_date <= end_date:
                    filtered_videos.append((video_id, pub_date_str, title))
            except ValueError:
                warnings.append(f"⚠️ Warning: Could not parse publish date '{pub_date_str}' for video {video_id}. Skipping.")
            except Exception as e:
                warnings.append(f"⚠️ Warning: Error processing date for video {video_id}: {e}. Skipping.")

        results.extend(warnings)
        if not filtered_videos:
            yield f"ℹ️ No videos found within the date range: {start_date.date()} to {end_date.date()}."
            return

        total_videos_to_process = len(filtered_videos)
        print(f"Processing {total_videos_to_process} videos sequentially after date filtering.")

        # 5. Process Filtered Videos
        processed_count = 0
        found_matches_overall = False
        for video_id, pub_date_str, title in filtered_videos:
            processed_count += 1
            
            # Call the helper to process this video
            single_video_results = _process_single_video(video_id, title, pub_date_str, keyword)
            
            # Add the results (or warning) from the helper to the main results list
            results.extend(single_video_results)
            
            # Check if the results were actual matches (not just warnings)
            if single_video_results and not single_video_results[0].startswith("⚠️"): 
                found_matches_overall = True
            
        # 6. Finalize
        if not found_matches_overall:
            results.append("\n**ℹ️ No matches found for the keyword...**")

    except ValueError as e:
        yield f"❌ Configuration Error: {e}"
        return
    except YouTubeChannelError as e:
        yield f"❌ YouTube API Error: {e}"
        return
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield f"❌ An unexpected error occurred: {e}"
        return

    # Yield final result
    yield "\n".join(results)
    return

# --- Streamlit UI and Processing Logic ---

st.set_page_config(layout="wide")
st.title("▶️ YouTube Channel Keyword Search")
st.markdown("Find videos from a YouTube channel where a specific keyword is mentioned in the transcript.")

# --- Input Section ---
with st.sidebar:
    st.header("⚙️ Configuration")

    # Check for API Key early
    if not YT_API_KEY:
        st.error("Error: YouTube API key (YT_API_KEY) not found.")
        st.info("Please set the YT_API_KEY environment variable. If running locally, you can create a `.env` file in the project root with `YT_API_KEY=YOUR_KEY_HERE`. If deploying on Streamlit Cloud, set it in the secrets manager.")
        st.stop() # Stop execution if no key
    else:
        st.success("YouTube API Key loaded.")

    channel_url_or_id_input = st.text_input(
        "📺 YouTube Channel URL or ID",
        placeholder="e.g., https://www.youtube.com/@MrBeast or UCX6OQ3DkcsbYNE6H8uQQuVA"
    )
    keyword_input = st.text_input(
        "🔑 Keyword to Search",
        placeholder="e.g., challenge"
    )

    col1, col2 = st.columns(2)
    with col1:
        start_date_input = st.date_input("🗓️ Start Date (Optional)", value=None, format="DD-MM-YYYY")
    with col2:
        end_date_input = st.date_input("🗓️ End Date (Optional)", value=None, format="DD-MM-YYYY")

    max_videos_input = st.number_input(
        "🔢 Max Videos to Scan",
        min_value=1,
        value=10,
        step=5,
        help="Maximum number of most recent videos to analyze."
    )

    search_button = st.button("🔍 Search Videos", type="primary", use_container_width=True)

# --- Output Section ---
results_container = st.container()

if search_button:
    # Validate inputs
    if not channel_url_or_id_input:
        st.warning("Please enter a YouTube Channel URL or ID.")
        st.stop()
    if not keyword_input:
        st.warning("Please enter a keyword to search for.")
        st.stop()

    start_date = parse_date(start_date_input)
    end_date = parse_date(end_date_input)

    # Use a status indicator for the whole process
    with st.spinner("Starting search process..."):
        try:
            # 1. Resolve Channel ID
            channel_id = _extract_channel_id(channel_url_or_id_input, YT_API_KEY)
            if not channel_id:
                st.error(f"Could not determine a valid YouTube Channel ID from '{channel_url_or_id_input}'. Please check the input.")
                st.stop()

            # 2. Fetch Playlist ID
            uploads_playlist_id = fetch_playlist_id(channel_id, YT_API_KEY)

            # 3. Fetch Video Details (with progress)
            # Note: fetch_all_video_details now uses st.progress internally
            all_video_details = fetch_all_video_details(uploads_playlist_id, YT_API_KEY, max_videos_input)

            if not all_video_details:
                st.warning("No videos found for this channel.")
                st.stop()

            # 4. Filter by Date
            filtered_videos = []
            st.write("Filtering videos by date...")
            for video_id, pub_date_str, title in all_video_details:
                try:
                    pub_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00')) # Parse ISO 8601
                    if (not start_date or pub_date >= start_date) and \
                       (not end_date or pub_date <= end_date):
                        filtered_videos.append((video_id, title, pub_date)) # Keep pub_date as datetime
                except ValueError:
                    st.warning(f"Could not parse date for video {video_id}: {pub_date_str}") # Handle potential parsing errors

            if not filtered_videos:
                st.warning("No videos found within the specified date range.")
                st.stop()

            st.write(f"Found {len(filtered_videos)} videos within date range (out of {len(all_video_details)} scanned). Analyzing transcripts...")

            # 5. Process Videos (Fetch Transcripts and Search)
            found_matches_count = 0
            match_details = [] # Store results: (title, url, timestamp, context_snippet)

            # Progress for transcript processing
            transcript_progress_bar = st.progress(0)
            transcript_status_text = st.empty()

            for i, (video_id, title, pub_date) in enumerate(filtered_videos):
                progress = (i + 1) / len(filtered_videos)
                transcript_status_text.text(f"Processing video {i+1}/{len(filtered_videos)}: {title[:50]}...")
                transcript_progress_bar.progress(progress)

                try:
                    transcript = fetch_transcript(video_id)
                    matches = search_in_transcript(transcript, keyword_input)

                    if matches:
                        found_matches_count += 1
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        for match in matches:
                            timestamp_seconds = int(match['start'])
                            timestamp_str = time.strftime('%H:%M:%S', time.gmtime(timestamp_seconds))
                            context = f"...{match['context_before']} **{match['text']}** {match['context_after']}..."
                            match_details.append({
                                "title": title,
                                "date": pub_date.strftime("%Y-%m-%d"),
                                "url": f"{video_url}&t={timestamp_seconds}s",
                                "timestamp": timestamp_str,
                                "context": context
                            })
                        # Clear cache if memory becomes an issue, but keep for now
                        # _transcript_cache.pop(video_id, None)

                except TranscriptFetchError as e:
                    st.warning(f"Skipping video '{title}' ({video_id}): {e}")
                except Exception as e:
                    st.error(f"Unexpected error processing video '{title}' ({video_id}): {e}")

            transcript_status_text.text(f"Finished processing {len(filtered_videos)} videos.")
            time.sleep(1)
            transcript_status_text.empty()
            transcript_progress_bar.empty()

        except YouTubeChannelError as e:
            st.error(f"YouTube API Error: {e}")
            st.stop()
        except ValueError as e: # Catch API key errors specifically if fetch_* raises them
             st.error(f"Configuration Error: {e}")
             st.stop()
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")
            import traceback
            st.error(traceback.format_exc()) # Show full traceback for debugging
            st.stop()

    # --- Display Results ---
    results_container.header(f"Results: Found '{keyword_input}' in {found_matches_count} video(s)")

    if not match_details:
        results_container.info("No matches found for the keyword in the analyzed video transcripts.")
    else:
        # Sort results by date descending (most recent first)
        match_details.sort(key=lambda x: datetime.strptime(x['date'], '%Y-%m-%d'), reverse=True)

        for detail in match_details:
             with results_container.expander(f"🎬 **{detail['title']}** ({detail['date']}) - Match at {detail['timestamp']}"):
                 st.markdown(f"**Timestamp:** [{detail['timestamp']}]({detail['url']})")
                 st.markdown(f"**Context:** {detail['context']}")
                 st.caption(f"[Watch full video]({detail['url'].split('&t=')[0]})")

# Streamlit apps run top-to-bottom automatically, no main guard needed for simple scripts
# If you need complex state or callbacks, explore st.session_state

# --- Removed Gradio interface function ---
# def create_gradio_interface():
#     # ... Gradio code removed ...
#     pass

# --- Removed Gradio launch block ---
# if __name__ == "__main__":
#    # ... Gradio launch code removed ...
#    pass

# Streamlit apps run top-to-bottom automatically, no main guard needed for simple scripts
# If you need complex state or callbacks, explore st.session_state

# Streamlit apps run top-to-bottom automatically, no main guard needed for simple scripts
# If you need complex state or callbacks, explore st.session_state 
