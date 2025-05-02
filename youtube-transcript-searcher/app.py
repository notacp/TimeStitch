import os
from dotenv import load_dotenv
import sys
import re
import time # Added for sleep in retries
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
# from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type # Removed tenacity
from typing import List, Tuple, Optional, Dict, Any, Union # Removed AsyncGenerator
from datetime import datetime, date, timezone
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import gradio as gr

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
YT_API_KEY = os.getenv("YT_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY") # Optional

# Validate essential API keys
if not YT_API_KEY:
    print("Error: YouTube API key (YT_API_KEY) not found in environment variables.", file=sys.stderr)
    print("Please create a .env file in the root directory and add YT_API_KEY=<your_key>", file=sys.stderr)
    # In a real deployment (like Hugging Face Spaces), secrets would be set in the environment.
    # For local development, ensure the .env file is correctly set up.
    # sys.exit(1) # Exit if the key is crucial for the app to run at all.
    # We might allow the app to load but show an error in the UI later.

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
    print(f"Attempting to resolve '{name_or_handle}' to a channel ID...")
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
            print(f"Resolved '{name_or_handle}' to Channel ID: {channel_id} (Title: {channel_title})")
            return channel_id
        else:
            # If no items are returned, the handle/name likely doesn't exist or isn't searchable this way
            print(f"Could not resolve '{name_or_handle}' to a channel ID via search.")
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
        print("Input appears to be a direct Channel ID.")
        return channel_url_or_id

    # 2. Standard Channel URL (/channel/UC...)
    match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", channel_url_or_id)
    if match:
        print("Found standard /channel/ URL.")
        return match.group(1)

    # 3. Handle URL (/@handle)
    match = re.search(r"youtube\.com/@([a-zA-Z0-9_.-]+)", channel_url_or_id)
    if match:
        handle = match.group(1)
        print(f"Found handle URL: @{handle}. Attempting resolution...")
        return _resolve_name_to_channel_id_sync(handle, api_key)

    # 4. Custom/Vanity URL (/c/name or /user/name)
    match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_.-]+)", channel_url_or_id)
    if match:
        name = match.group(1)
        print(f"Found custom/user URL: {name}. Attempting resolution...")
        return _resolve_name_to_channel_id_sync(name, api_key)

    # If none of the patterns match
    print(f"Warning: Could not extract or resolve channel ID from input: {channel_url_or_id}", file=sys.stderr)
    return None


def fetch_playlist_id(channel_id: str, api_key: str) -> str:
    """Synchronous function to fetch uploads playlist ID."""
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
            maxResults=50,
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
            # else: print(f"Skipping item due to missing data: {item.get('id')}")

        next_page_token = response.get('nextPageToken')
        # Return list of (id, date_str, title) tuples
        return video_details, next_page_token

    except HttpError as e:
        raise YouTubeChannelError(f"YouTube API error fetching video details page: {e.resp.status} {e.content.decode()}") from e
    except Exception as e:
        raise YouTubeChannelError(f"An unexpected error occurred fetching video details page: {e}") from e


def fetch_all_video_details(playlist_id: str, api_key: str, max_videos: int) -> List[Tuple[str, str, str]]:
    """Fetches all video details (ID, publishedAt, title) handling pagination and retries."""
    print(f"Fetching up to {max_videos} video details for playlist: {playlist_id}")
    all_details = []
    next_page_token = None
    fetch_attempt = 0
    max_fetch_attempts = RETRY_ATTEMPTS # Use constant

    while True:
        try:
            print(f"Fetching video details page... (token: {next_page_token})")
            details_page, next_page_token = _fetch_video_details_page(
                playlist_id, api_key, next_page_token
            )
            print(f"Fetched {len(details_page)} video details this page.")
            all_details.extend(details_page)

            if len(all_details) >= max_videos:
                print(f"Reached max_videos limit ({max_videos}).")
                break
            if not next_page_token:
                print("No more pages.")
                break
            fetch_attempt = 0 # Reset attempts on success
        except YouTubeChannelError as e:
            fetch_attempt += 1
            print(f"Error fetching video details page: {e}. Attempt {fetch_attempt}/{max_fetch_attempts}", file=sys.stderr)
            if fetch_attempt >= max_fetch_attempts:
                raise YouTubeChannelError(f"Failed to fetch video details after {max_fetch_attempts} attempts.") from e
            time.sleep(RETRY_WAIT_SECONDS) # Use constant
        except Exception as e:
            print(f"Unexpected error during video details fetch pagination: {e}", file=sys.stderr)
            raise # Reraise unexpected errors immediately

    # Truncate and return
    final_details = all_details[:max_videos]
    print(f"Finished fetching. Total video details collected: {len(final_details)}")
    return final_details


# --- Transcript Fetching ---

_transcript_cache: Dict[str, List[Dict[str, Any]]] = {}

# Custom exception for transcript errors
class TranscriptFetchError(Exception):
    pass

def fetch_transcript(video_id: str) -> List[Dict[str, Any]]:
    """Synchronous function to fetch a transcript for a given video ID."""
    print(f"Attempting synchronous transcript fetch for video ID: {video_id}")
    try:
        # Fetch the transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en', 'en-US']) # Prioritize English
        # Format the transcript for simpler searching (optional, but can be useful)
        # formatted_transcript = [{"text": t['text'], "start": t['start']} for t in transcript_list]
        # return formatted_transcript
        return transcript_list # Return the raw list of dicts for now
    except TranscriptsDisabled:
        raise TranscriptFetchError(f"Transcripts are disabled for video: {video_id}")
    except NoTranscriptFound:
        # It's possible no transcript exists, or not in the specified languages
        # Try fetching available transcripts to see if *any* exist
        try:
             available_transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
             # Log available languages if needed: print(f"Available transcript languages for {video_id}: {[t.language for t in available_transcripts]}")
             # Could attempt to fetch the first available one, e.g., available_transcripts.find_generated_transcript([...])
             raise TranscriptFetchError(f"No English transcript found for video: {video_id}. Available: {[t.language for t in available_transcripts]}")
        except Exception as inner_e:
             # If listing transcripts also fails (e.g., video deleted, private)
             raise TranscriptFetchError(f"Could not find or list transcripts for video: {video_id}. Reason: {inner_e}") from inner_e
    except Exception as e:
        # Catch any other unexpected errors from the library
        raise TranscriptFetchError(f"An unexpected error occurred fetching transcript for {video_id}: {e}") from e


# --- Transcript Searching ---

def search_in_transcript(transcript: List[Dict[str, Any]], keyword: str) -> List[Dict[str, Any]]:
    """
    Searches for a keyword within transcript segments using case-insensitive regex.

    Args:
        transcript: The list of transcript segments (dicts with 'text', 'start', etc.).
        keyword: The keyword to search for.

    Returns:
        A list of transcript segments where the keyword was found. Returns an empty list if no matches.
    """
    if not transcript or not keyword:
        return [] # Return early if no transcript or keyword provided

    matching_segments = []
    try:
        # Escape keyword for regex and compile for case-insensitive search
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    except re.error as e:
        print(f"Error compiling regex for keyword '{keyword}': {e}", file=sys.stderr)
        return [] # Return empty list if regex is invalid

    print(f"Searching for keyword '{keyword}' in {len(transcript)} transcript segments...")
    for segment in transcript:
        if 'text' in segment and pattern.search(segment['text']):
            matching_segments.append(segment)

    print(f"Found {len(matching_segments)} segments matching '{keyword}'.")
    return matching_segments


# --- Main Application Logic (to be added later) ---

# Updated test section

# ... rest of the application code (Gradio interface etc.) ... 

# --- Constants ---
MAX_CONCURRENT_TASKS = 5 # Semaphore limit

# --- Core Processing Logic ---

# Helper to parse date string - simplified to focus on YYYY-MM-DD format
def parse_date(date_input: Union[str, None]) -> Optional[datetime]:
    """
    Parses a date string in YYYY-MM-DD format into a timezone-aware datetime.
    Returns None if the input is invalid.
    """
    if not date_input:
        return None
        
    try:
        # First, handle direct YYYY-MM-DD format (our default)
        if isinstance(date_input, str) and len(date_input) >= 10:
            # Extract just the date portion if there's more (e.g., time components)
            date_part = date_input[:10]
            year, month, day = map(int, date_part.split('-'))
            # Create a datetime at midnight UTC for the specified date
            return datetime(year, month, day, tzinfo=timezone.utc)
    except (ValueError, TypeError, IndexError):
        # If any parsing fails, return None
        print(f"Warning: Could not parse date string: '{date_input}'", file=sys.stderr)
    
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
                 video_results.append(f"- [{minutes:02d}:{seconds:02d}](https://www.youtube.com/watch?v={video_id}&t={int(start_time)}s): {segment['text']}\n")
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
    max_videos: int,
    progress: gr.Progress = gr.Progress(track_tqdm=True)
) -> str:
    """
    Process channel search synchronously.
    Returns results as a formatted Markdown string.
    """
    progress(0, desc="Starting search...")
    found_matches = False
    results = []

    # 1. Validate Inputs (remains the same)
    if not keyword:
        return "❌ Error: Please provide a keyword to search for."
    if not channel_url_or_id:
        return "❌ Error: Please provide a Channel URL or ID."

    start_date = parse_date(start_date_input)
    end_date = parse_date(end_date_input)

    # Adjust end_date to be inclusive (end of the day)
    if end_date:
         end_date = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)


    if not start_date or not end_date:
        return f"❌ Error: Invalid date format. Please use YYYY-MM-DD format. Start: {start_date_input}, End: {end_date_input}"
    if start_date > end_date:
        return f"❌ Error: Start Date ({start_date.date()}) must be before or the same as End Date ({end_date.date()})."
    print(f"Date Range: {start_date.isoformat()} to {end_date.isoformat()}")


    try:
        # 2. Get Playlist ID
        progress(0.05, desc="Fetching channel info...")
        channel_id = _extract_channel_id(channel_url_or_id, YT_API_KEY)
        if not channel_id: return f"❌ Error: Could not extract or resolve a valid YouTube Channel ID from the input: '{channel_url_or_id}'. Please check the URL or ID."
        if not YT_API_KEY: raise ValueError("YT_API_KEY is not set in environment variables.")
        playlist_id = fetch_playlist_id(channel_id, YT_API_KEY)
        progress(0.1, desc=f"Found uploads playlist: {playlist_id}")

        # 3. Fetch Video Details using the new helper
        all_video_details = fetch_all_video_details(playlist_id, YT_API_KEY, int(max_videos))
        progress(0.2, desc=f"Found {len(all_video_details)} video details.")
        if not all_video_details: return "ℹ️ No videos found for this channel in the specified timeframe or limit."

        # 4. Filter Videos by Date
        progress(0.2, desc="Filtering videos by date...")
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
        if not filtered_videos: return f"ℹ️ No videos found within the date range: {start_date.date()} to {end_date.date()}."

        total_videos_to_process = len(filtered_videos)
        progress(0.3, desc=f"Filtered down to {total_videos_to_process} videos. Processing sequentially...")
        print(f"Processing {total_videos_to_process} videos sequentially after date filtering.")

        # 5. Process Filtered Videos
        processed_count = 0
        found_matches_overall = False
        for video_id, pub_date_str, title in filtered_videos:
            processed_count += 1
            progress(0.3 + (0.6 * processed_count / total_videos_to_process),
                     desc=f"Processing video {processed_count}/{total_videos_to_process} ('{title[:30]}...')...")
            
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
        progress(1.0, desc="Search complete!")

    except ValueError as e:
        return f"❌ Configuration Error: {e}"
    except YouTubeChannelError as e:
        return f"❌ YouTube API Error: {e}"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"❌ An unexpected error occurred: {e}"

    return "\n".join(results)

# --- Gradio Interface ---

def create_gradio_interface():
    """Creates and returns the Gradio Interface."""
    with gr.Blocks(theme=gr.themes.Soft()) as iface:
        gr.Markdown(
            """
            # YouTube Channel Transcript Searcher 🔎
            Enter a YouTube Channel URL, date range, keyword, and max videos to search.
            The app will fetch video transcripts within the date range and find segments containing the keyword.
            Results are streamed as they are found.
            """
        )

        with gr.Row():
            with gr.Column(scale=2):
                channel_input = gr.Textbox(
                    label="YouTube Channel URL",
                    placeholder="e.g., https://www.youtube.com/@ycombinator",
                    info="Enter the full URL along with the Channel Name eg. https://www.youtube.com/@ycombinator OR https://www.youtube.com/@NBA. Go to the channel page and copy the URL.",
                )
                keyword_input = gr.Textbox(label="Keyword", placeholder="e.g., Gradio, AI, TensorFlow")
            with gr.Column(scale=1):
                # Use gr.Accordion for Advanced Options
                with gr.Accordion("Advanced Options", open=False): # Accordion closed by default
                    # Default dates (e.g., last year)
                    today = date.today()
                    one_month_ago = date(today.year, today.month - 1, today.day)
                    # Format dates as YYYY-MM-DD strings
                    today_str = today.strftime("%Y-%m-%d")
                    one_month_ago_str = one_month_ago.strftime("%Y-%m-%d")
                    
                    # Use standard Textbox with pattern instructions instead of Date component
                    start_date_input = gr.DateTime(
                        label="Start Date",
                        value=one_month_ago_str,
                        include_time=False,
                        type="string"
                    )
                    end_date_input = gr.DateTime(
                        label="End Date",
                        value=today_str,
                        include_time=False,
                        type="string"
                    )
                    max_videos_input = gr.Slider(
                        minimum=10,
                        maximum=50, # Adjust max as needed, consider API quota
                        value=10,
                        step=5,
                        label="Max Videos to Check",
                        info="Maximum number of *latest* videos to fetch before date filtering.",
                    )

        submit_button = gr.Button("Search Channel Transcripts", variant="primary")
        output_markdown = gr.Markdown(label="Results")

        # Connect components to the processing function
        submit_button.click(
            fn=process_channel_search,
            inputs=[
                channel_input,
                start_date_input,
                end_date_input,
                keyword_input,
                max_videos_input,
            ],
            outputs=output_markdown,
            api_name="search_transcripts" # Optional API name for programmatic access
        )

    return iface

# --- Main Execution ---

if __name__ == "__main__":
    if not YT_API_KEY:
         print("--------------------------------------------------------------------------", file=sys.stderr)
         print("ERROR: YT_API_KEY not found in environment variables or .env file.", file=sys.stderr)
         print("The application requires a YouTube Data API Key to function.", file=sys.stderr)
         print("Please create a .env file with YT_API_KEY=<your_key> or set the environment variable.", file=sys.stderr)
         print("You can obtain an API key from the Google Cloud Console:", file=sys.stderr)
         print("https://developers.google.com/youtube/v3/getting-started", file=sys.stderr)
         print("--------------------------------------------------------------------------", file=sys.stderr)
         # Optionally, exit or show an error in Gradio itself
         # sys.exit(1)

    # Create and launch the interface
    app_iface = create_gradio_interface()

    # Launch the server - no need for queue() with non-streaming version
    # Set share=True to create a public link (useful for HF Spaces)
    # Set debug=True for more detailed logs during development
    app_iface.launch(debug=False) # Set debug=True locally if needed 