import json
import os
import threading
from datetime import datetime

# Reuse the same cache file path and lock as db_client
from .db_client import CACHE_FILE, _CACHE_FILE_LOCK


def _load_cache() -> dict:
    """Load the entire cache file safely.

    Returns an empty dict if the file does not exist or is corrupted.
    """
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        # If the file cannot be read, treat it as empty.
        return {}


def _write_cache(cache: dict) -> None:
    """Atomically write the cache dict back to the JSON file.

    Uses a temporary file and os.replace to avoid corruption.
    """
    tmp_file = f"{CACHE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp_file, CACHE_FILE)


def clear_cache_except(repo_path: str) -> None:
    """Remove all cached entries that belong to a different repository.

    After a fresh analysis of ``repo_path`` we keep only the entries whose
    ``repo_path`` matches the supplied value. This ensures the UI shows only
    the current repository's information.
    """
    if not repo_path:
        return
    with _CACHE_FILE_LOCK:
        cache = _load_cache()
        # Keep entries where the stored repo_path matches the target.
        filtered = {
            commit_hash: entry
            for commit_hash, entry in cache.items()
            if entry.get("repo_path") == repo_path
        }
        _write_cache(filtered)


def purge_cache() -> None:
    """Delete the entire cache file.

    Useful for a full reset (e.g., when the user wants a completely fresh
    analysis). The function is safe even if the file does not exist.
    """
    with _CACHE_FILE_LOCK:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
