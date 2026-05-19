import html
import re
import unicodedata
from typing import Any, Dict, List, Optional

from googleapiclient.discovery import build
from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled, YouTubeTranscriptApi

YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"

# Caches resolved channel IDs to keep YT API quota down when the same handle
# is hit repeatedly (e.g. /api/index/transcript per-video on a fresh channel).
_RESOLVE_NAME_CACHE: Dict[str, str] = {}
SUPPORTED_TRANSCRIPT_LANGUAGES = ("en", "hi", "fr", "es", "pt")
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
DEVANAGARI_TOKEN_RE = re.compile(r"[\u0900-\u097F]+")
LATIN_WORD_RE = re.compile(r"[A-Za-z0-9]")
LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
MIXED_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u0900-\u097F]+")
DEVANAGARI_VIRAMA = "्"

DEVANAGARI_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "f", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "ळ": "l", "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f",
}

DEVANAGARI_INDEPENDENT_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऋ": "ri",
}

DEVANAGARI_MATRAS = {
    "ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ृ": "ri",
}


def normalize_language_code(language_code: Optional[str]) -> str:
    code = (language_code or "").strip().lower()
    if not code:
        return ""
    return code.split("-", 1)[0]


def language_label_for_code(language_code: str, fallback: Optional[str] = None) -> str:
    labels = {
        "en": "English",
        "hi": "Hindi",
        "fr": "French",
        "es": "Spanish",
        "pt": "Portuguese",
    }
    return labels.get(language_code, fallback or language_code.upper() or "Unknown")


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(text or ""))
    normalized = normalized.replace("\u200c", "").replace("\u200d", "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _strip_diacritics(text: str) -> str:
    # Decompose then drop combining marks so "M\u00e9xico" -> "Mexico", "caf\u00e9" ->
    # "cafe". Applied only to latin-script matching paths; Devanagari uses
    # matras (combining marks) for vowels so stripping there would corrupt the
    # script. Keep this off the Hindi branch in _keyword_matches.
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _is_devanagari_text(text: str) -> bool:
    return bool(DEVANAGARI_RE.search(text or ""))


def _contains_latin_text(text: str) -> bool:
    return bool(LATIN_WORD_RE.search(text or ""))


def _romanize_devanagari(text: str) -> str:
    normalized = _normalize_text(text)
    output: List[str] = []
    i = 0

    while i < len(normalized):
        char = normalized[i]

        if char in DEVANAGARI_INDEPENDENT_VOWELS:
            output.append(DEVANAGARI_INDEPENDENT_VOWELS[char])
            i += 1
            continue

        if char in DEVANAGARI_CONSONANTS:
            base = DEVANAGARI_CONSONANTS[char]
            next_char = normalized[i + 1] if i + 1 < len(normalized) else ""

            if next_char in DEVANAGARI_MATRAS:
                output.append(base + DEVANAGARI_MATRAS[next_char])
                i += 2
                continue

            if next_char == DEVANAGARI_VIRAMA:
                output.append(base)
                i += 2
                continue

            output.append(base + "a")
            i += 1
            continue

        if char == "ं" or char == "ँ":
            output.append("n")
        elif char == "ः":
            output.append("h")
        else:
            output.append(char)
        i += 1

    return "".join(output)


def _cross_script_phonetic_match(text: str, keyword: str) -> bool:
    text_has_devanagari    = _is_devanagari_text(text)
    keyword_has_latin      = _contains_latin_text(keyword)
    text_has_latin         = _contains_latin_text(text)
    keyword_has_devanagari = _is_devanagari_text(keyword)

    if keyword_has_latin and text_has_devanagari:
        for token in DEVANAGARI_TOKEN_RE.findall(_normalize_text(text)):
            if _romanized_forms_similar(keyword, _romanize_devanagari(token)):
                return True
        return False

    if keyword_has_devanagari and text_has_latin:
        romanized_kw = _romanize_devanagari(keyword)
        for token in LATIN_TOKEN_RE.findall(_normalize_text(text)):
            # Args swapped: token is the "keyword", romanized_kw is the "token".
            # Devanagari romanizations are longer than their Latin originals, so
            # the min-length guard (len(tok) >= 0.9*len(kw)) must see the longer
            # form as tok and the shorter Latin word as kw.
            if _romanized_forms_similar(token, romanized_kw):
                return True
        return False

    return False


def human_script_variants(keyword: str) -> List[str]:
    normalized = _normalize_text(keyword)
    variants = [normalized] if normalized else []

    if _is_devanagari_text(normalized):
        romanized = _romanize_devanagari(normalized)
        if romanized:
            variants.append(romanized)

    deduped: List[str] = []
    seen = set()
    for variant in variants:
        key = variant.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def _dedupe_terms(terms: List[str]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for term in terms:
        normalized = _normalize_text(term)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


_LONG_VOWEL_RE = re.compile(r"([aeiou])\1+")
# Excludes y because Hindi -ya endings (kiya, maya, gaya) keep their final a.
_TRAILING_SCHWA_RE = re.compile(r"([bcdfghjklmnpqrstvwxz])a$")


def _collapse_long_vowels(text: str) -> str:
    return _LONG_VOWEL_RE.sub(r"\1", text)


def _drop_trailing_schwa(text: str) -> str:
    return _TRAILING_SCHWA_RE.sub(r"\1", text)


def _phonetic_key(token: str) -> str:
    """Pronunciation key: same value for "startup" and "स्टार्टअप".
    Romanize Devanagari, then collapse long vowels and drop the trailing schwa.
    """
    if _is_devanagari_text(token):
        token = _romanize_devanagari(token)
    s = token.casefold()
    s = _collapse_long_vowels(s)
    s = _drop_trailing_schwa(s)
    return s


def _limited_edit_distance(left: str, right: str, max_distance: int) -> Optional[int]:
    if abs(len(left) - len(right)) > max_distance:
        return None

    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        row_min = current[0]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current[j - 1] + 1
            delete_cost = previous[j] + 1
            replace_cost = previous[j - 1] + (left_char != right_char)
            value = min(insert_cost, delete_cost, replace_cost)
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return None
        previous = current

    distance = previous[-1]
    return distance if distance <= max_distance else None


def _romanized_forms_similar(latin_keyword: str, romanized_token: str, threshold: float = 0.45) -> bool:
    """
    True if romanized_token is a plausible phonetic borrowing of latin_keyword.

    Uses prefix-anchored comparison: the token may carry a suffix not in the
    keyword (e.g. Hindi "-shana" for the English "-tion" ending), so we compare
    the keyword against the first len(keyword) characters of the token.

    Guards:
    - First chars must match (quick reject).
    - Token must be at least max(4, 0.9 * len(keyword)) chars to prevent short
      tokens from passing via prefix truncation alone (e.g. rejects "milate" for
      "meditate": 6 < max(4,7)).
    - Normalized edit distance (edit_dist / len(keyword)) must be <= threshold.
      Note: max_dist uses int() truncation, so the effective ratio is at most
      `threshold` but may be slightly lower for short keywords.

    Threshold 0.45 for keywords >6 chars: for "startup" (len 7), allows int(7*0.45)=3
    edits, accepting "startup"→"staartaapa" (distance 3). For keywords ≤6 chars the
    threshold drops to 0.25 (max 1 edit), preventing short native Hindi words from
    false-matching short English keywords (e.g. "lekina" must not match "lemon").
    """
    if not latin_keyword or not romanized_token:
        return False

    kw = latin_keyword.casefold()
    tok = romanized_token.casefold()

    # Try literal first (existing behavior — covers "namaste"-style direct
    # romanizations). If that fails, retry on phonetic-key forms so loanwords
    # like "startup" ↔ "staartaapa" line up after collapsing doubled vowels
    # and dropping the trailing schwa.
    if _forms_within_threshold(kw, tok, threshold):
        return True
    kw_key = _drop_trailing_schwa(_collapse_long_vowels(kw))
    tok_key = _drop_trailing_schwa(_collapse_long_vowels(tok))
    if kw_key != kw or tok_key != tok:
        return _forms_within_threshold(kw_key, tok_key, threshold)
    return False


def _forms_within_threshold(kw: str, tok: str, threshold: float) -> bool:
    if not kw or not tok or kw[0] != tok[0]:
        return False
    if len(tok) < max(4, int(len(kw) * 0.9)):
        return False
    cmp_len = len(kw)
    tok_prefix = tok[:cmp_len]
    effective_threshold = threshold if cmp_len > 6 else min(threshold, 0.25)
    max_dist = max(1, int(cmp_len * effective_threshold))
    return _limited_edit_distance(kw, tok_prefix, max_dist) is not None


def _extract_devanagari_tokens(transcript: List[Dict[str, Any]]) -> List[str]:
    tokens: List[str] = []
    seen = set()

    for segment in transcript:
        for token in DEVANAGARI_TOKEN_RE.findall(_normalize_text(segment.get("text", ""))):
            if len(token) < 3:
                continue
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)

    return tokens


def _keyword_matches(text: str, keyword: str, language_code: str) -> bool:
    normalized_text = _normalize_text(text)
    normalized_keyword = _normalize_text(keyword)
    if not normalized_text or not normalized_keyword:
        return False

    if (language_code == "hi" or _is_devanagari_text(normalized_keyword)) and normalized_keyword in normalized_text:
        return True

    if LATIN_WORD_RE.search(normalized_keyword):
        # Strip diacritics so French/Spanish/Portuguese accented forms match
        # unaccented user queries ("mexico" -> "México", "futbol" -> "fútbol").
        escaped = re.escape(_strip_diacritics(normalized_keyword.casefold()))
        lowered_text = _strip_diacritics(normalized_text.casefold())
        if bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", lowered_text)):
            return True

    if _cross_script_phonetic_match(normalized_text, normalized_keyword):
        return True

    # Only fall back to bare substring for non-Latin keywords — for Latin text the
    # word-boundary check above is authoritative and prevents partial matches like
    # "cred" matching inside "incredible".
    if not LATIN_WORD_RE.search(normalized_keyword):
        if normalized_keyword.casefold() in normalized_text.casefold():
            return True

    # Compound-word fallback: "PostHog" matches "post hog" in transcripts
    if len(normalized_keyword) >= 5:
        kw_lower = normalized_keyword.casefold()
        words = normalized_text.casefold().split()
        for i in range(len(words)):
            for window in range(2, 4):
                if i + window > len(words):
                    break
                if "".join(words[i : i + window]) == kw_lower:
                    return True

    return False


def _segment_to_raw_data(segments: Any) -> List[Dict[str, Any]]:
    if hasattr(segments, "to_raw_data"):
        return segments.to_raw_data()
    if isinstance(segments, list):
        return segments
    return list(segments)


class YouTubeService:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.youtube = build(YOUTUBE_API_SERVICE_NAME, YOUTUBE_API_VERSION, developerKey=api_key)

    def resolve_channel_id(self, channel_url_or_id: str) -> Optional[str]:
        if not channel_url_or_id:
            return None

        if re.match(r"^UC[a-zA-Z0-9_-]{22}$", channel_url_or_id):
            return channel_url_or_id

        match = re.search(r"youtube\.com/channel/(UC[a-zA-Z0-9_-]{22})", channel_url_or_id)
        if match:
            return match.group(1)

        match = re.search(r"(?:youtube\.com/)?@([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            return self._resolve_name_to_channel_id(match.group(1))

        match = re.search(r"youtube\.com/(?:c|user)/([a-zA-Z0-9_.-]+)", channel_url_or_id)
        if match:
            return self._resolve_name_to_channel_id(match.group(1))

        return self._resolve_name_to_channel_id(channel_url_or_id)

    def _resolve_name_to_channel_id(self, name_or_handle: str) -> Optional[str]:
        cached = _RESOLVE_NAME_CACHE.get(name_or_handle)
        if cached is not None:
            return cached
        try:
            search_response = self.youtube.search().list(
                part="snippet",
                q=name_or_handle,
                type="channel",
                maxResults=1,
            ).execute()

            if search_response.get("items"):
                channel_id = search_response["items"][0]["snippet"]["channelId"]
                _RESOLVE_NAME_CACHE[name_or_handle] = channel_id
                return channel_id
            return None
        except Exception:
            return None

    def fetch_uploads_playlist_id(self, channel_id: str) -> str:
        response = self.youtube.channels().list(
            part="contentDetails",
            id=channel_id,
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
                pageToken=next_page_token,
            ).execute()

            for item in response.get("items", []):
                snippet = item.get("snippet", {})
                content_details = item.get("contentDetails", {})
                videos.append({
                    "id": content_details.get("videoId"),
                    "title": snippet.get("title"),
                    "publishedAt": snippet.get("publishedAt"),
                    "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url"),
                })

            next_page_token = response.get("nextPageToken")
            if not next_page_token:
                break

        if exclude_shorts and videos:
            videos = self._filter_out_shorts(videos)

        return videos

    def _filter_out_shorts(self, videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        video_ids = [v["id"] for v in videos if v["id"]]

        video_meta = {}
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            response = self.youtube.videos().list(
                part="contentDetails,snippet",
                id=",".join(batch),
            ).execute()
            for item in response.get("items", []):
                duration_str = item.get("contentDetails", {}).get("duration", "PT0S")
                total_seconds = 0
                for value, unit in re.findall(r"(\d+)([DHMS])", duration_str):
                    if unit == "D":
                        total_seconds += int(value) * 86400
                    elif unit == "H":
                        total_seconds += int(value) * 3600
                    elif unit == "M":
                        total_seconds += int(value) * 60
                    elif unit == "S":
                        total_seconds += int(value)

                snippet = item.get("snippet", {})
                tags = [t.lower() for t in snippet.get("tags", [])]
                title = snippet.get("title", "").lower()
                description = snippet.get("description", "").lower()
                has_shorts_tag = (
                    "#shorts" in tags
                    or "#shorts" in title
                    or "#shorts" in description
                )

                # ≤60s → always a Short; 61–180s → Short only if tagged; >180s → never a Short
                if total_seconds <= 60:
                    is_short = True
                elif total_seconds <= 180:
                    is_short = has_shorts_tag
                else:
                    is_short = False

                video_meta[item["id"]] = is_short

        # default False keeps videos whose IDs weren't returned by the API
        filtered = [v for v in videos if not video_meta.get(v["id"], False)]
        return filtered

    def get_transcript(self, video_id: str, preferred_languages: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        languages = self._normalize_preferred_languages(preferred_languages)
        return self._get_transcript_from_api(video_id, languages)

    def _normalize_preferred_languages(self, preferred_languages: Optional[List[str]]) -> List[str]:
        languages = [normalize_language_code(code) for code in (preferred_languages or [])]
        languages = [code for code in languages if code in SUPPORTED_TRANSCRIPT_LANGUAGES]
        for code in SUPPORTED_TRANSCRIPT_LANGUAGES:
            if code not in languages:
                languages.append(code)
        return languages

    def _get_transcript_from_api(self, video_id: str, preferred_languages: List[str]) -> Optional[Dict[str, Any]]:
        try:
            ytt_api = YouTubeTranscriptApi()
            transcript_list = self._list_transcripts(ytt_api, video_id)
            transcript = self._select_local_transcript(transcript_list, preferred_languages)
            if not transcript:
                return None
            segments = _segment_to_raw_data(transcript.fetch())
            language_code = normalize_language_code(getattr(transcript, "language_code", ""))
            return {
                "language_code": language_code,
                "language_label": language_label_for_code(language_code, getattr(transcript, "language", None)),
                "is_generated": bool(getattr(transcript, "is_generated", False)),
                "segments": segments,
            }
        except (TranscriptsDisabled, NoTranscriptFound):
            return None
        except Exception:
            raise

    def _list_transcripts(self, ytt_api: Any, video_id: str) -> Any:
        if hasattr(ytt_api, "list"):
            return ytt_api.list(video_id)
        if hasattr(ytt_api, "list_transcripts"):
            return ytt_api.list_transcripts(video_id)
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            return YouTubeTranscriptApi.list_transcripts(video_id)
        raise RuntimeError("youtube-transcript-api does not support listing transcripts in this environment")

    def _select_local_transcript(self, transcript_list: Any, preferred_languages: List[str]) -> Optional[Any]:
        transcripts = list(transcript_list)
        for language in preferred_languages:
            manual = next(
                (
                    transcript for transcript in transcripts
                    if normalize_language_code(getattr(transcript, "language_code", "")) == language
                    and not bool(getattr(transcript, "is_generated", False))
                ),
                None,
            )
            if manual:
                return manual

            generated = next(
                (
                    transcript for transcript in transcripts
                    if normalize_language_code(getattr(transcript, "language_code", "")) == language
                ),
                None,
            )
            if generated:
                return generated
        return None

    def expand_search_terms_for_transcript(
        self,
        keywords: List[str],
        transcript: List[Dict[str, Any]],
        transcript_language: str,
    ) -> List[str]:
        base_terms = _dedupe_terms(keywords)
        if transcript_language != "hi":
            return base_terms

        transcript_tokens = _extract_devanagari_tokens(transcript)
        if not transcript_tokens:
            return base_terms

        additions: List[str] = []
        for keyword in base_terms:
            if _is_devanagari_text(keyword) or not _contains_latin_text(keyword):
                continue

            for token in transcript_tokens:
                if _romanized_forms_similar(keyword, _romanize_devanagari(token)):
                    additions.append(token)

        return _dedupe_terms(base_terms + additions)

    def search_in_transcript(
        self,
        transcript: List[Dict[str, Any]],
        keywords: List[str],
        transcript_language: str,
    ) -> List[Dict[str, Any]]:
        usable_keywords = [_normalize_text(keyword) for keyword in keywords if _normalize_text(keyword)]
        if not usable_keywords:
            return []

        single_keywords = [kw for kw in usable_keywords if " " not in kw]
        phrase_keywords = [kw for kw in usable_keywords if " " in kw]
        WINDOW = 3
        n = len(transcript)

        # Single-word keywords stay per-segment (cheap, exact).
        single_hit_anchors: set = set()
        if single_keywords:
            for i, segment in enumerate(transcript):
                if any(
                    _keyword_matches(segment["text"], kw, transcript_language)
                    for kw in single_keywords
                ):
                    single_hit_anchors.add(i)

        # Multi-word phrases use a sliding WINDOW because YouTube splits
        # captions into 2-5 word segments. We slide forward and only emit at
        # the LAST anchor whose window still matches — that anchor is the
        # segment that contains the head of the phrase, so the timestamp
        # lands on the actual phrase start, not the preceding context.
        phrase_hit_anchors: set = set()
        if phrase_keywords:
            prev_hits: set = set()
            for i in range(n + 1):
                if i < n:
                    window_text = " ".join(
                        transcript[k].get("text", "") for k in range(i, min(i + WINDOW, n))
                    )
                    cur_hits = {
                        kw for kw in phrase_keywords
                        if _keyword_matches(window_text, kw, transcript_language)
                    }
                else:
                    cur_hits = set()
                if prev_hits - cur_hits:
                    phrase_hit_anchors.add(i - 1)
                prev_hits = cur_hits

        anchors = sorted(single_hit_anchors | phrase_hit_anchors)
        seen_starts = set()
        matches: List[Dict[str, Any]] = []
        for i in anchors:
            segment = transcript[i]
            if segment["start"] in seen_starts:
                continue
            seen_starts.add(segment["start"])
            matches.append({
                "start": segment["start"],
                "text": segment["text"],
                "context_before": transcript[i - 1]["text"] if i > 0 else "",
                "context_after": transcript[i + 1]["text"] if i < n - 1 else "",
            })
        return matches
