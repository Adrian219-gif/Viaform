"""Two-layer cache for programme Requirements and Timeline snapshots."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional
from urllib.parse import unquote, urlsplit, urlunsplit


logger = logging.getLogger(__name__)

CacheKind = Literal["requirements", "timeline"]
CacheSource = Literal["live", "runtime_cache", "seed"]
CACHE_TTL = timedelta(days=7)
PROGRAMME_POOL_TTL = timedelta(days=180)
SCHEMA_VERSION = 1


def _normalize_text(value: Optional[str]) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold().replace("&", " and ")
    return re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE).strip()


def _normalize_programme_name(value: Optional[str]) -> str:
    normalized = _normalize_text(value)
    original = normalized
    qualification = (
        r"(?:msc|ms|ma|meng|mres|mphil|mba|llm|mfa|master of science|"
        r"master of arts|master of engineering|master of research|master of philosophy)"
    )
    normalized = re.sub(rf"^{qualification}(?:\s+(?:in|of))?\s+", "", normalized)
    normalized = re.sub(rf"\s+{qualification}$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or original


def _normalize_url(value: Optional[str]) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    hostname = (parsed.hostname or "").casefold()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = parsed.port
    netloc = hostname
    if port and not ((parsed.scheme.casefold() == "https" and port == 443) or (parsed.scheme.casefold() == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    path = re.sub(r"/+", "/", unquote(parsed.path or "/")).rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold() or "https", netloc, path, "", ""))


def normalized_programme_identity(
    *,
    university: str,
    programme: str,
    official_program_url: Optional[str],
    intended_entry_year: int,
    intended_entry_term: str,
) -> Dict[str, Any]:
    """Return the canonical identity shared by Requirements and Timeline."""
    return {
        "university": _normalize_text(university),
        "programme": _normalize_programme_name(programme),
        "official_program_url": _normalize_url(official_program_url),
        "intended_entry_year": int(intended_entry_year),
        "intended_entry_term": _normalize_text(intended_entry_term),
    }


def programme_cache_key(identity: Dict[str, Any]) -> str:
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def programme_semantic_cache_key(identity: Dict[str, Any]) -> str:
    """Narrow alias key: same institution, programme core name, and admission cycle."""
    semantic_identity = {
        "university": identity["university"],
        "programme": identity["programme"],
        "intended_entry_year": identity["intended_entry_year"],
        "intended_entry_term": identity["intended_entry_term"],
    }
    canonical = json.dumps(
        semantic_identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def university_cache_key(university: str, country: str) -> str:
    identity = {
        "university": _normalize_text(university),
        "country": _normalize_text(country),
    }
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_checked_at(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_fresh(checked_at: str, now: datetime) -> bool:
    try:
        age = now.astimezone(timezone.utc) - parse_checked_at(checked_at)
    except (TypeError, ValueError):
        return False
    return age < CACHE_TTL


@dataclass(frozen=True)
class CacheRecord:
    checked_at: str
    payload: Dict[str, Any]
    source: CacheSource


@dataclass(frozen=True)
class ProgrammePoolRecord:
    university_key: str
    university: str
    programme: str
    official_program_url: str
    degree_type: str
    relevance_reason: str
    first_seen_at: str
    last_seen_at: str
    source_metadata: Dict[str, Any]
    status: str
    discovery_order: int


@dataclass(frozen=True)
class ProgrammePoolSnapshot:
    programmes: list[ProgrammePoolRecord]
    last_refreshed_at: Optional[str]
    fresh: bool


class ProgrammeCache:
    """Read runtime SQLite first, then a tracked per-programme seed JSON."""

    def __init__(self, runtime_db: Path, seed_dir: Path) -> None:
        self.runtime_db = runtime_db
        self.seed_dir = seed_dir

    def _connect(self) -> sqlite3.Connection:
        self.runtime_db.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.runtime_db))
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS programme_cache (
                cache_kind TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                semantic_key TEXT,
                checked_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (cache_kind, cache_key)
            )
            """
        )
        cache_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(programme_cache)").fetchall()
        }
        if "semantic_key" not in cache_columns:
            connection.execute("ALTER TABLE programme_cache ADD COLUMN semantic_key TEXT")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_programme_cache_semantic "
            "ON programme_cache(cache_kind, semantic_key, checked_at)"
        )
        rows_without_semantic_key = connection.execute(
            "SELECT cache_kind, cache_key, payload_json FROM programme_cache "
            "WHERE semantic_key IS NULL"
        ).fetchall()
        for cache_kind, cache_key, payload_json in rows_without_semantic_key:
            if cache_kind != "requirements":
                continue
            try:
                payload = json.loads(payload_json)
                target = payload["target_program"]
                identity = normalized_programme_identity(
                    university=target["university"],
                    programme=target["program"],
                    official_program_url=target.get("official_program_url"),
                    intended_entry_year=target["intended_entry_year"],
                    intended_entry_term=target["intended_entry_term"],
                )
                semantic_key = programme_semantic_cache_key(identity)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            connection.execute(
                "UPDATE programme_cache SET semantic_key = ? "
                "WHERE cache_kind = ? AND cache_key = ?",
                (semantic_key, cache_kind, cache_key),
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS university_official_urls (
                university_key TEXT PRIMARY KEY,
                university TEXT NOT NULL,
                country TEXT NOT NULL,
                official_url TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                invalidated_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS school_programme_pool (
                university_key TEXT NOT NULL,
                programme_key TEXT NOT NULL,
                university TEXT NOT NULL,
                programme_name TEXT NOT NULL,
                official_program_url TEXT NOT NULL,
                degree_type TEXT NOT NULL DEFAULT '',
                relevance_reason TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                source_metadata_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                discovery_order INTEGER NOT NULL,
                PRIMARY KEY (university_key, programme_key)
            )
            """
        )
        pool_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(school_programme_pool)").fetchall()
        }
        if "discovery_order" not in pool_columns:
            connection.execute(
                "ALTER TABLE school_programme_pool "
                "ADD COLUMN discovery_order INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS school_programme_pool_state (
                university_key TEXT PRIMARY KEY,
                last_refreshed_at TEXT NOT NULL
            )
            """
        )
        return connection

    def read_university_official_url(self, university_key: str) -> Optional[str]:
        if not self.runtime_db.exists():
            return None
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT official_url FROM university_official_urls "
                    "WHERE university_key = ? AND status = 'active'",
                    (university_key,),
                ).fetchone()
            return str(row[0]) if row else None
        except (OSError, sqlite3.Error) as error:
            logger.warning("university_url_cache_read_failed key=%s error=%s", university_key, error)
            return None

    def write_university_official_url(
        self,
        university_key: str,
        university: str,
        country: str,
        official_url: str,
        *,
        checked_at: Optional[str] = None,
    ) -> None:
        timestamp = checked_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO university_official_urls (
                    university_key, university, country, official_url, checked_at, status, invalidated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', NULL)
                ON CONFLICT(university_key) DO UPDATE SET
                    university = excluded.university,
                    country = excluded.country,
                    official_url = excluded.official_url,
                    checked_at = excluded.checked_at,
                    status = 'active',
                    invalidated_at = NULL
                """,
                (university_key, university, country, official_url, timestamp),
            )

    def mark_university_official_url_invalid(
        self,
        university_key: str,
        *,
        invalidated_at: Optional[str] = None,
    ) -> None:
        timestamp = invalidated_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE university_official_urls SET status = 'invalid', invalidated_at = ? "
                "WHERE university_key = ?",
                (timestamp, university_key),
            )

    @staticmethod
    def _programme_key(programme: str) -> str:
        """Treat a stable programme name as identity so canonical URL changes update in place."""
        return hashlib.sha256(_normalize_text(programme).encode("utf-8")).hexdigest()

    def read_programme_pool(
        self,
        university_key: str,
        *,
        now: Optional[datetime] = None,
    ) -> ProgrammePoolSnapshot:
        if not self.runtime_db.exists():
            return ProgrammePoolSnapshot(programmes=[], last_refreshed_at=None, fresh=False)
        current = now or datetime.now(timezone.utc)
        try:
            with self._connect() as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    "SELECT * FROM school_programme_pool "
                    "WHERE university_key = ? AND status = 'active'",
                    (university_key,),
                ).fetchall()
                state = connection.execute(
                    "SELECT last_refreshed_at FROM school_programme_pool_state "
                    "WHERE university_key = ?",
                    (university_key,),
                ).fetchone()
            programmes = [
                ProgrammePoolRecord(
                    university_key=row["university_key"],
                    university=row["university"],
                    programme=row["programme_name"],
                    official_program_url=row["official_program_url"],
                    degree_type=row["degree_type"],
                    relevance_reason=row["relevance_reason"],
                    first_seen_at=row["first_seen_at"],
                    last_seen_at=row["last_seen_at"],
                    source_metadata=json.loads(row["source_metadata_json"]),
                    status=row["status"],
                    discovery_order=int(row["discovery_order"]),
                )
                for row in rows
            ]
            refreshed_at = str(state[0]) if state else None
            fresh = False
            if refreshed_at:
                age = current.astimezone(timezone.utc) - parse_checked_at(refreshed_at)
                fresh = age < PROGRAMME_POOL_TTL
            return ProgrammePoolSnapshot(
                programmes=programmes,
                last_refreshed_at=refreshed_at,
                fresh=fresh,
            )
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as error:
            logger.warning("programme_pool_read_failed key=%s error=%s", university_key, error)
            return ProgrammePoolSnapshot(programmes=[], last_refreshed_at=None, fresh=False)

    def merge_programme_pool(
        self,
        university_key: str,
        university: str,
        programmes: list[Dict[str, Any]],
        source_metadata: Dict[str, Any],
        *,
        refreshed_at: Optional[str] = None,
    ) -> None:
        timestamp = refreshed_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            next_order = int(
                connection.execute(
                    "SELECT COALESCE(MAX(discovery_order), -1) + 1 "
                    "FROM school_programme_pool WHERE university_key = ?",
                    (university_key,),
                ).fetchone()[0]
            )
            for programme in programmes:
                name = str(programme.get("program") or "").strip()
                url = str(programme.get("official_program_url") or "").strip()
                if not name or not url:
                    continue
                programme_key = self._programme_key(name)
                existing = connection.execute(
                    "SELECT first_seen_at, source_metadata_json, discovery_order "
                    "FROM school_programme_pool "
                    "WHERE university_key = ? AND programme_key = ?",
                    (university_key, programme_key),
                ).fetchone()
                first_seen_at = str(existing[0]) if existing else timestamp
                discovery_order = int(existing[2]) if existing else next_order
                if not existing:
                    next_order += 1
                metadata = dict(source_metadata)
                if existing:
                    previous = json.loads(existing[1])
                    previous_queries = previous.get("queries", []) if isinstance(previous, dict) else []
                    current_queries = metadata.get("queries", [])
                    metadata["queries"] = list(dict.fromkeys([*previous_queries, *current_queries]))
                connection.execute(
                    """
                    INSERT INTO school_programme_pool (
                        university_key, programme_key, university, programme_name,
                        official_program_url, degree_type, relevance_reason, first_seen_at,
                        last_seen_at, source_metadata_json, status, discovery_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                    ON CONFLICT(university_key, programme_key) DO UPDATE SET
                        university = excluded.university,
                        programme_name = excluded.programme_name,
                        official_program_url = excluded.official_program_url,
                        degree_type = excluded.degree_type,
                        relevance_reason = excluded.relevance_reason,
                        last_seen_at = excluded.last_seen_at,
                        source_metadata_json = excluded.source_metadata_json
                    """,
                    (
                        university_key,
                        programme_key,
                        university,
                        name,
                        url,
                        str(programme.get("degree_type") or ""),
                        str(programme.get("relevance_reason") or ""),
                        first_seen_at,
                        timestamp,
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        discovery_order,
                    ),
                )
            connection.execute(
                """
                INSERT INTO school_programme_pool_state (university_key, last_refreshed_at)
                VALUES (?, ?)
                ON CONFLICT(university_key) DO UPDATE SET
                    last_refreshed_at = excluded.last_refreshed_at
                """,
                (university_key, timestamp),
            )

    def read_runtime(
        self,
        kind: CacheKind,
        cache_key: str,
        *,
        semantic_key: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> Optional[CacheRecord]:
        if not self.runtime_db.exists():
            return None
        current = now or datetime.now(timezone.utc)
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT checked_at, payload_json FROM programme_cache "
                    "WHERE cache_kind = ? AND cache_key = ?",
                    (kind, cache_key),
                ).fetchone()
                if (not row or not is_fresh(row[0], current)) and semantic_key:
                    alias_rows = connection.execute(
                        "SELECT checked_at, payload_json FROM programme_cache "
                        "WHERE cache_kind = ? AND semantic_key = ? "
                        "ORDER BY checked_at DESC",
                        (kind, semantic_key),
                    ).fetchall()
                    row = next(
                        (candidate for candidate in alias_rows if is_fresh(candidate[0], current)),
                        None,
                    )
            if not row or not is_fresh(row[0], current):
                return None
            payload = json.loads(row[1])
            if not isinstance(payload, dict):
                return None
            return CacheRecord(checked_at=row[0], payload=payload, source="runtime_cache")
        except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError) as error:
            logger.warning("programme_cache_runtime_read_failed kind=%s error=%s", kind, error)
            return None

    def read_seed(
        self,
        kind: CacheKind,
        cache_key: str,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[CacheRecord]:
        path = self.seed_dir / f"{cache_key}.json"
        if not path.exists():
            return None
        current = now or datetime.now(timezone.utc)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("schema_version") != SCHEMA_VERSION:
                return None
            if document.get("cache_key") != cache_key:
                return None
            snapshot = document.get(kind)
            if not isinstance(snapshot, dict):
                return None
            checked_at = snapshot.get("checked_at")
            payload = snapshot.get("payload")
            if not isinstance(checked_at, str) or not isinstance(payload, dict):
                return None
            if not is_fresh(checked_at, current):
                return None
            return CacheRecord(checked_at=checked_at, payload=payload, source="seed")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            logger.warning("programme_cache_seed_read_failed kind=%s error=%s", kind, error)
            return None

    def write_runtime(
        self,
        kind: CacheKind,
        cache_key: str,
        checked_at: str,
        payload: Dict[str, Any],
        *,
        semantic_key: Optional[str] = None,
    ) -> None:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO programme_cache (
                    cache_kind, cache_key, semantic_key, checked_at, payload_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_kind, cache_key) DO UPDATE SET
                    semantic_key = excluded.semantic_key,
                    checked_at = excluded.checked_at,
                    payload_json = excluded.payload_json
                """,
                (kind, cache_key, semantic_key, checked_at, serialized),
            )

    def export_runtime_to_seed(
        self,
        kind: CacheKind,
        cache_key: str,
        identity: Dict[str, Any],
    ) -> Path:
        if not self.runtime_db.exists():
            raise LookupError("runtime cache database does not exist")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT checked_at, payload_json FROM programme_cache "
                "WHERE cache_kind = ? AND cache_key = ?",
                (kind, cache_key),
            ).fetchone()
        if not row:
            raise LookupError(f"no runtime {kind} snapshot for cache key {cache_key}")
        payload = json.loads(row[1])
        path = self.seed_dir / f"{cache_key}.json"
        self.seed_dir.mkdir(parents=True, exist_ok=True)
        document: Dict[str, Any] = {}
        if path.exists():
            document = json.loads(path.read_text(encoding="utf-8"))
        document.update(
            {
                "schema_version": SCHEMA_VERSION,
                "cache_key": cache_key,
                "identity": identity,
                kind: {"checked_at": row[0], "payload": payload},
            }
        )
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path
