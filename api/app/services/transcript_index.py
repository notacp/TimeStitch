import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

from .youtube import (
    DEVANAGARI_TOKEN_RE,
    MIXED_TOKEN_RE,
    _normalize_text,
    _phonetic_key,
    _romanize_devanagari,
    normalize_language_code,
)


def _is_remote() -> bool:
    return bool(os.getenv("TURSO_DATABASE_URL"))


# ---------------------------------------------------------------------------
# Turso HTTP API v2 adapter
# Reads execute immediately; writes are batched and sent on commit().
# ---------------------------------------------------------------------------

def _encode_value(val: Any) -> dict:
    if val is None:
        return {"type": "null", "value": None}
    if isinstance(val, bool):
        return {"type": "integer", "value": str(int(val))}
    if isinstance(val, int):
        return {"type": "integer", "value": str(val)}
    if isinstance(val, float):
        return {"type": "float", "value": str(val)}
    return {"type": "text", "value": str(val)}


def _decode_value(cell: dict) -> Any:
    t = cell.get("type")
    v = cell.get("value")
    if t == "null" or v is None:
        return None
    if t == "integer":
        return int(v)
    if t in ("float", "real"):
        return float(v)
    return v


class _TursoCursor:
    def __init__(self, result: dict):
        cols = [col["name"] for col in result.get("cols", [])]
        self._rows = [
            {col: _decode_value(cell) for col, cell in zip(cols, row)}
            for row in result.get("rows", [])
        ]

    def fetchall(self) -> List[dict]:
        return self._rows

    def fetchone(self) -> Optional[dict]:
        return self._rows[0] if self._rows else None


class _TursoHTTPConnection:
    """Minimal sqlite3-compatible wrapper using Turso HTTP API v2."""

    def __init__(self, url: str, token: str):
        self._url = url.replace("libsql://", "https://") + "/v2/pipeline"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._write_queue: List[dict] = []

    def _send(self, requests: List[dict]) -> List[dict]:
        import httpx  # deferred — not needed in local-dev path
        with httpx.Client(timeout=30.0) as client:
            response = client.post(self._url, headers=self._headers, json={"requests": requests})
        response.raise_for_status()
        results = response.json().get("results", [])
        for r in results:
            if r.get("type") == "error":
                raise Exception(r.get("error", {}).get("message", "Turso error"))
        return [r for r in results if r.get("response", {}).get("type") == "execute"]

    def execute(self, sql: str, params=()) -> _TursoCursor:
        stripped = sql.strip().upper()
        stmt = {"sql": sql.strip(), "args": [_encode_value(p) for p in params]}
        if stripped.startswith(("SELECT", "PRAGMA", "WITH")):
            results = self._send([{"type": "execute", "stmt": stmt}, {"type": "close"}])
            raw = results[0]["response"]["result"] if results else {"cols": [], "rows": []}
            return _TursoCursor(raw)
        self._write_queue.append({"type": "execute", "stmt": stmt})
        return _TursoCursor({"cols": [], "rows": []})

    def commit(self) -> None:
        if not self._write_queue:
            return
        self._send(self._write_queue + [{"type": "close"}])
        self._write_queue.clear()

    def close(self) -> None:
        self._write_queue.clear()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_db_path() -> Path:
    project_root = Path(__file__).resolve().parents[3]
    configured = os.getenv("CLIPCHASE_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return project_root / ".data" / "clipchase_index.sqlite3"


def _build_search_text(text: str) -> str:
    """Pad transcript text with extra forms so the FTS index can match across
    scripts. For each token we add (a) a romanized form for Devanagari tokens
    and (b) a pronunciation key for both scripts. The key collapses long
    vowels and the trailing schwa, so "startup" and "स्टार्टअप" land on the
    same key and either query lights up the other.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return ""

    additions: List[str] = []
    seen = set()

    def add(value: str) -> None:
        if not value:
            return
        k = value.casefold()
        if k in seen:
            return
        seen.add(k)
        additions.append(value)

    for token in MIXED_TOKEN_RE.findall(normalized):
        if DEVANAGARI_TOKEN_RE.fullmatch(token):
            add(_romanize_devanagari(token))
        add(_phonetic_key(token))

    if not additions:
        return normalized

    return " ".join([normalized, *additions])


def _quote_fts_term(term: str) -> str:
    return '"' + (term or "").replace('"', '""') + '"'


class TranscriptIndexService:
    def __init__(self, db_path: Optional[str] = None):
        # Explicit db_path always uses local SQLite regardless of env vars.
        self._remote = db_path is None and _is_remote()
        self.db_path = Path(db_path).expanduser() if db_path else _default_db_path()
        if not self._remote:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def _connect(self):
        if self._remote:
            return _TursoHTTPConnection(
                url=os.environ["TURSO_DATABASE_URL"],
                token=os.getenv("TURSO_AUTH_TOKEN", ""),
            )
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    _SCHEMA_STATEMENTS = [
        """
        CREATE TABLE IF NOT EXISTS indexed_channels (
            channel_id TEXT PRIMARY KEY,
            source_url TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS indexed_videos (
            video_id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            title TEXT NOT NULL,
            published_at TEXT NOT NULL,
            thumbnail TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            FOREIGN KEY(channel_id) REFERENCES indexed_channels(channel_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_indexed_videos_channel_id
            ON indexed_videos(channel_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS indexed_transcripts (
            video_id TEXT NOT NULL,
            language_code TEXT NOT NULL,
            language_label TEXT NOT NULL,
            is_generated INTEGER NOT NULL,
            segment_count INTEGER NOT NULL,
            indexed_at TEXT NOT NULL,
            PRIMARY KEY (video_id, language_code),
            FOREIGN KEY(video_id) REFERENCES indexed_videos(video_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS transcript_segments USING fts5(
            video_id UNINDEXED,
            language_code UNINDEXED,
            segment_index UNINDEXED,
            start UNINDEXED,
            duration UNINDEXED,
            text,
            search_text
        )
        """,
    ]

    def ensure_schema(self) -> None:
        conn = self._connect()
        try:
            for stmt in self._SCHEMA_STATEMENTS:
                conn.execute(stmt)
            conn.commit()
        finally:
            conn.close()

    def upsert_channel(self, channel_id: str, source_url: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO indexed_channels (channel_id, source_url, indexed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(channel_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    indexed_at = excluded.indexed_at
                """,
                (channel_id, source_url, _utc_now_iso()),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_video(self, channel_id: str, video: Dict[str, Any]) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO indexed_videos (video_id, channel_id, title, published_at, thumbnail, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    title = excluded.title,
                    published_at = excluded.published_at,
                    thumbnail = excluded.thumbnail,
                    indexed_at = excluded.indexed_at
                """,
                (
                    video["id"],
                    channel_id,
                    video.get("title") or "",
                    video.get("publishedAt") or "",
                    video.get("thumbnail") or "",
                    _utc_now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def upsert_transcript(self, video_id: str, transcript: Dict[str, Any]) -> bool:
        language_code = normalize_language_code(transcript.get("language_code"))
        segments = transcript.get("segments") or []
        if not video_id or not language_code or not segments:
            return False

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO indexed_transcripts (
                    video_id,
                    language_code,
                    language_label,
                    is_generated,
                    segment_count,
                    indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, language_code) DO UPDATE SET
                    language_label = excluded.language_label,
                    is_generated = excluded.is_generated,
                    segment_count = excluded.segment_count,
                    indexed_at = excluded.indexed_at
                """,
                (
                    video_id,
                    language_code,
                    transcript.get("language_label") or language_code.upper(),
                    1 if transcript.get("is_generated") else 0,
                    len(segments),
                    _utc_now_iso(),
                ),
            )
            conn.execute(
                "DELETE FROM transcript_segments WHERE video_id = ? AND language_code = ?",
                (video_id, language_code),
            )

            for index, segment in enumerate(segments):
                text = _normalize_text(segment.get("text", ""))
                if not text:
                    continue
                conn.execute(
                    """
                    INSERT INTO transcript_segments (
                        video_id,
                        language_code,
                        segment_index,
                        start,
                        duration,
                        text,
                        search_text
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        video_id,
                        language_code,
                        index,
                        float(segment.get("start", 0)),
                        float(segment.get("duration", 0)),
                        text,
                        _build_search_text(text),
                    ),
                )

            conn.commit()
            return True
        finally:
            conn.close()

    def cache_video_transcripts(
        self,
        channel_id: str,
        source_url: str,
        video: Dict[str, Any],
        transcripts: Sequence[Dict[str, Any]],
    ) -> int:
        if not transcripts:
            return 0

        self.upsert_channel(channel_id, source_url)
        self.upsert_video(channel_id, video)

        stored = 0
        seen_languages = set()
        for transcript in transcripts:
            language_code = normalize_language_code(transcript.get("language_code"))
            if not language_code or language_code in seen_languages:
                continue
            seen_languages.add(language_code)
            if self.upsert_transcript(video["id"], transcript):
                stored += 1
        return stored

    def get_indexed_video_ids(self, channel_id: str, video_ids: Sequence[str]) -> Set[str]:
        if not channel_id or not video_ids:
            return set()

        placeholders = ",".join("?" for _ in video_ids)
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT video_id
                FROM indexed_videos
                WHERE channel_id = ? AND video_id IN ({placeholders})
                """,
                [channel_id, *video_ids],
            ).fetchall()
            return {row["video_id"] for row in rows}
        finally:
            conn.close()

    def has_any_indexed_videos(self, channel_id: str) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM indexed_videos WHERE channel_id = ? LIMIT 1",
                (channel_id,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_transcript(self, video_id: str, language_code: str) -> Optional[Dict[str, Any]]:
        normalized_language = normalize_language_code(language_code)
        if not video_id or not normalized_language:
            return None

        conn = self._connect()
        try:
            transcript_row = conn.execute(
                """
                SELECT video_id, language_code, language_label, is_generated, segment_count
                FROM indexed_transcripts
                WHERE video_id = ? AND language_code = ?
                """,
                (video_id, normalized_language),
            ).fetchone()
            if transcript_row is None:
                return None

            segments = conn.execute(
                """
                SELECT start, duration, text
                FROM transcript_segments
                WHERE video_id = ? AND language_code = ?
                ORDER BY CAST(segment_index AS INTEGER)
                """,
                (video_id, normalized_language),
            ).fetchall()

            return {
                "language_code": transcript_row["language_code"],
                "language_label": transcript_row["language_label"],
                "is_generated": bool(transcript_row["is_generated"]),
                "segments": [
                    {
                        "start": float(row["start"]),
                        "duration": float(row["duration"]),
                        "text": row["text"],
                    }
                    for row in segments
                ],
            }
        finally:
            conn.close()

    def get_indexed_languages(self, video_id: str) -> Set[str]:
        """Languages actually stored for a video, in ONE round-trip.

        _get_indexed_match used to brute-force get_transcript() across every
        (preferred-order x language) combination — up to ~25 calls per video,
        each a fresh Turso HTTP connection + 2 queries. Callers should resolve
        the stored language set first, then fetch only those.
        """
        if not video_id:
            return set()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT DISTINCT language_code FROM indexed_transcripts WHERE video_id = ?",
                (video_id,),
            ).fetchall()
            return {row["language_code"] for row in rows}
        finally:
            conn.close()

    def find_candidate_video_ids(self, video_ids: Sequence[str], search_terms: Sequence[str]) -> Set[str]:
        cleaned_terms = [_normalize_text(term) for term in search_terms if _normalize_text(term)]
        if not video_ids or not cleaned_terms:
            return set()

        # Expand each query term to its pronunciation key so the FTS pre-filter
        # mirrors what _build_search_text put into the index. Without this the
        # index has the bridge form but the query never asks for it.
        expanded: List[str] = []
        seen: Set[str] = set()
        for term in cleaned_terms:
            for candidate in (term, _phonetic_key(term)):
                if not candidate:
                    continue
                k = candidate.casefold()
                if k in seen:
                    continue
                seen.add(k)
                expanded.append(candidate)
            for token in MIXED_TOKEN_RE.findall(term):
                key = _phonetic_key(token)
                if not key:
                    continue
                k = key.casefold()
                if k in seen:
                    continue
                seen.add(k)
                expanded.append(key)

        placeholders = ",".join("?" for _ in video_ids)
        match_query = " OR ".join(_quote_fts_term(term) for term in expanded)

        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT DISTINCT video_id
                FROM transcript_segments
                WHERE transcript_segments MATCH ?
                  AND video_id IN ({placeholders})
                """,
                [match_query, *video_ids],
            ).fetchall()
            return {row["video_id"] for row in rows}
        finally:
            conn.close()

    def get_channel_stats(self, channel_id: str) -> Dict[str, int]:
        conn = self._connect()
        try:
            video_count = conn.execute(
                "SELECT COUNT(*) AS count FROM indexed_videos WHERE channel_id = ?",
                (channel_id,),
            ).fetchone()["count"]
            transcript_count = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM indexed_transcripts t
                JOIN indexed_videos v ON v.video_id = t.video_id
                WHERE v.channel_id = ?
                """,
                (channel_id,),
            ).fetchone()["count"]
            return {
                "videos": int(video_count or 0),
                "transcripts": int(transcript_count or 0),
            }
        finally:
            conn.close()
