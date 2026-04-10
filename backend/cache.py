"""
cache.py — SQLite Caching Layer for RepoLens

Caches analysis results keyed by (repo_url + latest commit SHA).
Also caches per-file embeddings by content hash to skip re-embedding
unchanged files on re-analysis.

Schema:
  repo_cache: repo_url, commit_sha, data_json, created_at
  file_embed_cache: content_hash, collection_id, embedded_at
"""

import os
import json
import sqlite3
import hashlib
import time
import requests
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────
# Database path
# ─────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent / "repolens_cache.db"

_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    """Get or create a thread-local SQLite connection."""
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _init_tables(_conn)
    return _conn


def _init_tables(conn: sqlite3.Connection):
    """Create cache tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS repo_cache (
            repo_url     TEXT NOT NULL,
            commit_sha   TEXT NOT NULL,
            data_json    TEXT NOT NULL,
            created_at   REAL NOT NULL,
            PRIMARY KEY (repo_url, commit_sha)
        );

        CREATE TABLE IF NOT EXISTS file_embed_cache (
            content_hash   TEXT PRIMARY KEY,
            collection_id  TEXT NOT NULL,
            chunk_ids      TEXT NOT NULL,  -- JSON array of chunk IDs
            embedded_at    REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_repo_url ON repo_cache(repo_url);
        CREATE INDEX IF NOT EXISTS idx_embed_collection ON file_embed_cache(collection_id);
    """)
    conn.commit()


# ─────────────────────────────────────────
# GitHub SHA fetching
# ─────────────────────────────────────────

def get_latest_commit_sha(repo_url: str) -> Optional[str]:
    """Fetch the latest commit SHA for a repo from GitHub API."""
    import re
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", repo_url.strip().rstrip("/"))
    if not match:
        return None

    owner, repo = match.group(1), match.group(2)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits?per_page=1",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            commits = resp.json()
            if commits and len(commits) > 0:
                return commits[0].get("sha", "")
    except Exception as e:
        print(f"[cache] Failed to fetch latest SHA: {e}")

    return None


# ─────────────────────────────────────────
# Repo-level cache
# ─────────────────────────────────────────

def get_cached_repo(repo_url: str, commit_sha: str) -> Optional[dict]:
    """Look up cached analysis result for repo+SHA."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT data_json FROM repo_cache WHERE repo_url = ? AND commit_sha = ?",
        (repo_url, commit_sha),
    ).fetchone()

    if row:
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None
    return None


def save_repo_cache(repo_url: str, commit_sha: str, data: dict):
    """Store analysis result in cache."""
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO repo_cache (repo_url, commit_sha, data_json, created_at)
           VALUES (?, ?, ?, ?)""",
        (repo_url, commit_sha, json.dumps(data), time.time()),
    )
    conn.commit()


def invalidate_repo_cache(repo_url: str):
    """Remove all cached entries for a given repo URL."""
    conn = _get_conn()
    conn.execute("DELETE FROM repo_cache WHERE repo_url = ?", (repo_url,))
    conn.commit()
    print(f"[cache] Invalidated cache for {repo_url}")


# ─────────────────────────────────────────
# File-level embedding cache
# ─────────────────────────────────────────

def file_content_hash(content: str) -> str:
    """Generate a SHA-256 hash of file content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def is_file_embedded(content_hash: str, collection_id: str) -> bool:
    """Check if a file (by content hash) is already embedded in a collection."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM file_embed_cache WHERE content_hash = ? AND collection_id = ?",
        (content_hash, collection_id),
    ).fetchone()
    return row is not None


def save_file_embed(content_hash: str, collection_id: str, chunk_ids: list[str]):
    """Record that a file has been embedded."""
    conn = _get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO file_embed_cache (content_hash, collection_id, chunk_ids, embedded_at)
           VALUES (?, ?, ?, ?)""",
        (content_hash, collection_id, json.dumps(chunk_ids), time.time()),
    )
    conn.commit()


def get_cached_chunk_ids(content_hash: str, collection_id: str) -> Optional[list[str]]:
    """Get chunk IDs for a previously embedded file."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT chunk_ids FROM file_embed_cache WHERE content_hash = ? AND collection_id = ?",
        (content_hash, collection_id),
    ).fetchone()
    if row:
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None
    return None


def clear_collection_embeds(collection_id: str):
    """Clear all file embed entries for a collection (on re-analysis)."""
    conn = _get_conn()
    conn.execute("DELETE FROM file_embed_cache WHERE collection_id = ?", (collection_id,))
    conn.commit()


# ─────────────────────────────────────────
# Cache stats (for health/debug)
# ─────────────────────────────────────────

def cache_stats() -> dict:
    """Return cache statistics."""
    conn = _get_conn()
    repo_count = conn.execute("SELECT COUNT(*) FROM repo_cache").fetchone()[0]
    embed_count = conn.execute("SELECT COUNT(*) FROM file_embed_cache").fetchone()[0]
    return {
        "cached_repos": repo_count,
        "cached_file_embeds": embed_count,
        "db_path": str(DB_PATH),
    }
