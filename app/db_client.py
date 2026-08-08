"""
RepoLens - Database Cache Client

Persists analysis results to a Supabase Postgres table (JSONB column)
with a local JSON file fallback when Supabase credentials are missing
or the Supabase API is unreachable.

Environment variables (loaded from `.env` or the system environment):

    SUPABASE_URL          Project URL, e.g. https://xyz.supabase.co
    SUPABASE_KEY          Anon or service-role key. Aliases
                          SUPABASE_ANON_KEY / SUPABASE_SERVICE_ROLE_KEY
                          are also accepted.
    REPOLENS_CACHE_TABLE  Cache table name (default: repo_analysis)
    REPOLENS_CACHE_FILE   Fallback cache file (default: .repolens_cache.json)

Required table schema (see supabase_schema.sql):

    repo_analysis (
        repo_path     text not null,
        commit_hash   text not null unique,   -- enables on_conflict upsert
        analysis_data jsonb not null,         -- the full metrics payload
        cached_at     timestamptz not null default now()
    )
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

# Load .env file without overriding already-set environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# --- Configuration -------------------------------------------------------

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
if SUPABASE_URL.endswith("/rest/v1"):
    SUPABASE_URL = SUPABASE_URL[:-8].rstrip("/")
SUPABASE_KEY = (
    os.getenv("SUPABASE_KEY")
    or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    or os.getenv("SUPABASE_ANON_KEY")
    or ""
).strip()

CACHE_TABLE = (os.getenv("REPOLENS_CACHE_TABLE") or "repo_analysis").strip()
CACHE_FILE = (os.getenv("REPOLENS_CACHE_FILE") or ".repolens_cache.json").strip()

# Treat the .env.example placeholder as "not configured" so we skip the
# doomed DNS/HTTP attempt and go straight to the local fallback.
SUPABASE_ENABLED = bool(
    SUPABASE_URL
    and SUPABASE_KEY
    and "YOUR_PROJECT_REF" not in SUPABASE_URL
)

_CACHE_FILE_LOCK = threading.Lock()
_CLIENT_LOCK = threading.Lock()
_HTTP_CLIENT: httpx.Client | None = None


def _get_http_client() -> httpx.Client:
    """Return a lazily-created, thread-safe httpx client for Supabase PostgREST."""
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None:
        with _CLIENT_LOCK:
            if _HTTP_CLIENT is None:
                _HTTP_CLIENT = httpx.Client(
                    base_url=f"{SUPABASE_URL}/rest/v1",
                    headers={
                        "apikey": SUPABASE_KEY,
                        "Authorization": f"Bearer {SUPABASE_KEY}",
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )
    return _HTTP_CLIENT


# --- Public API ----------------------------------------------------------

def get_cached_analysis(commit_hash: str) -> dict | None:
    """
    Retrieve cached analysis data for a commit hash.

    Queries Supabase first; if Supabase is unavailable or the record
    is missing, falls back to the local JSON cache file.

    Args:
        commit_hash (str): Full SHA-1 of the analyzed commit

    Returns:
        dict | None: The cached `analysis_data` payload, or None on a miss.
    """
    if not commit_hash:
        return None

    # 1) Try Supabase
    if SUPABASE_ENABLED:
        try:
            data = _query_supabase(commit_hash)
            if data is not None:
                return data
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Supabase cache read failed (HTTP %s); using local cache.",
                e.response.status_code,
            )
        except Exception as e:  # noqa: BLE001 - fallback is intentional
            logger.debug("Supabase cache read unavailable (%s); using local cache.", e)

    # 2) Fallback: local JSON file
    return _query_local_file(commit_hash)


def save_analysis_cache(
    repo_path: str, commit_hash: str, analysis_data: dict
) -> bool:
    """
    Persist analysis data for a commit hash (upsert semantics).

    Attempts a Supabase upsert first. If Supabase is not configured or
    the write fails, writes to the local JSON cache file instead.

    Args:
        repo_path (str): Path of the analyzed repository
        commit_hash (str): Full SHA-1 of the analyzed commit
        analysis_data (dict): Metrics payload to cache

    Returns:
        bool: True if the data was persisted to at least one backend.
    """
    if not commit_hash:
        return False

    # 1) Try Supabase
    if SUPABASE_ENABLED:
        try:
            if _upsert_supabase(repo_path, commit_hash, analysis_data):
                return True
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Supabase cache write failed (HTTP %s); using local cache.",
                e.response.status_code,
            )
        except Exception as e:  # noqa: BLE001 - fallback is intentional
            logger.debug("Supabase cache write unavailable (%s); using local cache.", e)

    # 2) Fallback: local JSON file
    return _upsert_local_file(repo_path, commit_hash, analysis_data)


# --- Supabase (PostgREST) helpers -----------------------------------------

def _query_supabase(commit_hash: str) -> dict | None:
    """
    Query the Supabase `repo_analysis` table by commit hash.

    Raises on transport/HTTP errors so callers can fall back.
    """
    response = _get_http_client().get(
        f"{CACHE_TABLE}",
        params={
            "select": "analysis_data",
            "commit_hash": f"eq.{commit_hash}",
            "limit": 1,
        },
    )
    response.raise_for_status()
    rows = response.json()
    if not rows or not isinstance(rows, list):
        return None
    payload = rows[0].get("analysis_data")
    return payload if isinstance(payload, dict) else None


def _upsert_supabase(
    repo_path: str, commit_hash: str, analysis_data: dict
) -> bool:
    """
    Upsert a row into the Supabase `repo_analysis` table.

    Uses PostgREST's `on_conflict=commit_hash` + `merge-duplicates`
    semantics (requires a UNIQUE constraint on commit_hash).
    """
    response = _get_http_client().post(
        f"{CACHE_TABLE}",
        params={"on_conflict": "commit_hash"},
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        json=[
            {
                "repo_path": repo_path,
                "commit_hash": commit_hash,
                "analysis_data": analysis_data,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    )
    response.raise_for_status()
    return True


# --- Local JSON file fallback helpers --------------------------------------

def _load_cache_file() -> dict:
    """Load the local cache file contents (empty dict if missing/corrupt)."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        logger.warning("Local cache file %s is unreadable; treating as empty.", CACHE_FILE)
        return {}


def _query_local_file(commit_hash: str) -> dict | None:
    """Read a cached payload from the local JSON file."""
    with _CACHE_FILE_LOCK:
        cache = _load_cache_file()
    entry = cache.get(commit_hash)
    if isinstance(entry, dict) and isinstance(entry.get("analysis_data"), dict):
        return entry["analysis_data"]
    return None


def _upsert_local_file(
    repo_path: str, commit_hash: str, analysis_data: dict
) -> bool:
    """Write/update an entry in the local JSON file (atomic replace)."""
    try:
        with _CACHE_FILE_LOCK:
            cache = _load_cache_file()
            cache[commit_hash] = {
                "repo_path": repo_path,
                "analysis_data": analysis_data,
                "cached_at": datetime.now(timezone.utc).isoformat(),
            }
            # Write to a temp file then atomically replace to avoid corruption
            tmp_file = f"{CACHE_FILE}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
            os.replace(tmp_file, CACHE_FILE)
        return True
    except Exception as e:  # noqa: BLE001 - caching is best-effort
        logger.warning("Local cache write failed: %s", e)
        return False
