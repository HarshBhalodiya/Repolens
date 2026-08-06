"""
RepoLens - Main Application

FastAPI application serving the Git repository analysis dashboard.
Supports both local Git repositories and remote GitHub URLs.
"""

import os
import shutil
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .ai_engine import generate_standup_summary
from .db_client import get_cached_analysis, save_analysis_cache
from .git_parser import extract_repo_metrics
from .utils import (
    clone_github_repo,
    get_latest_commit_hash,
    is_github_url,
    validate_git_repo,
)

# Initialize FastAPI application
app = FastAPI(title="RepoLens", description="AI-powered local Git repository analyzer")

# Repo root derived from this file's own location. Root cause of the
# original bug: "static" / "static/index.html" were resolved against the
# process's current working directory, so `uvicorn app.main:app` only
# worked when launched from the exact repo root and crashed with
# RuntimeError: Directory 'static' does not exist from anywhere else.
_BASE_DIR = Path(__file__).resolve().parent.parent

# --- CORS middleware ---
# `allow_origins=["*"]` combined with `allow_credentials=True` is an invalid
# combination per the CORS spec (browsers reject credentialed requests to a
# wildcard origin) and, on top of that, needlessly widens who can call this
# API. This app doesn't use cookies/sessions, so credentials aren't needed.
# Origins are restricted to a configurable allowlist (defaults to common
# local-dev origins) instead of "*".
_allowed_origins = [
    origin.strip()
    for origin in os.getenv("REPOLENS_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
] or ["http://localhost:8000", "http://127.0.0.1:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Optional API-key auth ---
# `/api/analyze` lets a caller point the server at any local filesystem path
# and read out its full git history. With no auth, anyone who can reach this
# service (e.g. if it's ever exposed beyond localhost) can use it to probe
# arbitrary paths on the host. Setting REPOLENS_API_KEY turns on a simple
# bearer-token check; if it's unset, the app keeps working as a local-only
# tool (matching its original single-user design intent) but a startup log
# line makes that tradeoff visible instead of silent.
REPOLENS_API_KEY = (os.getenv("REPOLENS_API_KEY") or "").strip()

if not REPOLENS_API_KEY:
    import logging

    logging.getLogger(__name__).warning(
        "REPOLENS_API_KEY is not set. /api/analyze is unauthenticated and can "
        "read any local filesystem path reachable by this process. Set "
        "REPOLENS_API_KEY if this service is reachable by anyone other than you."
    )


async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    """Validate the Authorization header when REPOLENS_API_KEY is configured."""
    if not REPOLENS_API_KEY:
        return  # Auth disabled: local-only usage, as before.
    expected = f"Bearer {REPOLENS_API_KEY}"
    if not authorization or authorization != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")


# Pydantic model for analysis request
class AnalysisRequest(BaseModel):
    repo_path: str
    force_refresh: bool = False


# Pydantic model for AI feature requests (standup summary / codebase index)
class RepoPathRequest(BaseModel):
    repo_path: str


def _is_valid_cached_payload(payload: dict) -> bool:
    """
    Return True only if a payload represents a completed, meaningful analysis.

    Guards against serving or persisting empty/errored results (e.g. a git log
    timeout that returned `_empty_metrics`), which would otherwise poison the
    cache and leave the dashboard permanently blank.
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("_error"):
        return False
    summary = payload.get("summary")
    return isinstance(summary, dict) and summary.get("total_commits", 0) > 0


# POST endpoint for repository analysis
@app.post("/api/analyze", response_model=dict, dependencies=[Depends(require_api_key)])
async def analyze_repository(request: AnalysisRequest):
    """
    Analyze a Git repository and return commit metrics.

    Accepts either:
    - A local file system path to a Git repository
    - A GitHub URL (https://github.com/owner/repo or git@github.com:owner/repo)

    For remote URLs, the repo is cloned to a temporary directory,
    analyzed, and then cleaned up automatically.

    Results are cached by the HEAD commit hash in Supabase (with a local
    JSON file fallback). A cache hit returns instantly; set `force_refresh`
    to true to bypass the cache and recompute.

    Response shape: {"cached": bool, "data": {<metrics>}}
    """
    # Validate input
    if not request.repo_path or not request.repo_path.strip():
        raise HTTPException(
            status_code=400,
            detail="Repository path cannot be empty.",
        )

    repo_input = request.repo_path.strip()
    temp_cleanup_path = None

    try:
        # --- Handle GitHub URLs ---
        if is_github_url(repo_input):
            cloned_path, repo_name = clone_github_repo(repo_input)
            temp_cleanup_path = cloned_path
            real_path = cloned_path
            source_label = f"remote (github.com/{repo_name})"
        else:
            # --- Handle local paths ---
            is_valid, message = validate_git_repo(repo_input)
            if not is_valid:
                raise HTTPException(status_code=400, detail=message)
            real_path = repo_input
            source_label = "local"

        # Cache key: the HEAD commit of the repository
        commit_hash = get_latest_commit_hash(real_path)

        # --- Try the cache first (unless force refresh) ---
        if commit_hash and not request.force_refresh:
            cached = get_cached_analysis(commit_hash)
            # Auto-heal: ignore (and implicitly overwrite) stale empty/errored
            # entries so a single bad run can't blank the dashboard forever.
            if cached is not None and _is_valid_cached_payload(cached):
                # Attach per-request metadata to the cached payload
                cached["_source"] = source_label
                cached["_input"] = repo_input
                return {"cached": True, "data": cached}

        # --- Fresh analysis ---
        metrics = extract_repo_metrics(real_path)

        # A non-empty `_error` key means extraction did not complete (e.g.
        # git log timed out, git missing). Previously this was returned as
        # HTTP 200 with all-zero metrics, so API consumers had no reliable
        # way to detect failure without inspecting the payload body. Return
        # a non-2xx status instead; the error detail carries the reason.
        if metrics.get("_error"):
            raise HTTPException(status_code=500, detail=metrics["_error"])

        # Add metadata about the source
        metrics["_source"] = source_label
        metrics["_input"] = repo_input

        # Persist to cache only if the analysis is meaningful - never cache
        # empty/errored results. Use the user-provided input as the recorded
        # path so remote clones don't store dead temp-dir paths.
        if commit_hash and _is_valid_cached_payload(metrics):
            cache_payload = {
                k: v for k, v in metrics.items() if not k.startswith("_")
            }
            save_analysis_cache(repo_input, commit_hash, cache_payload)

        return {"cached": False, "data": metrics}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}",
        )
    finally:
        # Clean up temporary cloned repo if any
        if temp_cleanup_path and os.path.exists(temp_cleanup_path):
            parent = os.path.dirname(temp_cleanup_path)
            shutil.rmtree(parent, ignore_errors=True)


# POST endpoint for AI standup summaries
@app.post(
    "/api/summarize", response_model=dict, dependencies=[Depends(require_api_key)]
)
def summarize_standup(request: RepoPathRequest):
    """
    Generate an AI standup summary for a repository using a local Ollama model.

    Accepts JSON: {"repo_path": str}

    Response shape: {"summary": str, "status": "success" | "error"}

    Note: intentionally a sync `def` endpoint so the (CPU/IO-heavy)
    LLM call runs in FastAPI's threadpool instead of blocking the event
    loop like `async def` would.
    """
    if not request.repo_path or not request.repo_path.strip():
        raise HTTPException(
            status_code=400,
            detail="Repository path cannot be empty.",
        )
    
    repo_input = request.repo_path.strip()
    temp_cleanup_path = None
    try:
        if is_github_url(repo_input):
            cloned_path, _ = clone_github_repo(repo_input)
            temp_cleanup_path = cloned_path
            real_path = cloned_path
        else:
            real_path = repo_input

        return generate_standup_summary(real_path)
    except Exception as e:
        return {
            "summary": f"Failed to generate standup summary: {str(e)}",
            "status": "error",
        }
    finally:
        if temp_cleanup_path and os.path.exists(temp_cleanup_path):
            parent = os.path.dirname(temp_cleanup_path)
            shutil.rmtree(parent, ignore_errors=True)


# Mount static files directory (resolved from __file__ so the app starts
# regardless of the CWD uvicorn was launched from).
app.mount(
    "/static",
    StaticFiles(directory=str(_BASE_DIR / "static")),
    name="static",
)


# Root endpoint serves the main HTML page
@app.get("/")
async def read_root():
    """Serve the main HTML page."""
    return FileResponse(_BASE_DIR / "static" / "index.html")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy", "service": "RepoLens"}


# Information endpoint
@app.get("/info")
async def get_info():
    """Get information about the RepoLens service."""
    return {
        "name": "RepoLens",
        "version": "1.0.0",
        "description": "AI-powered local Git repository analyzer",
        "github_urls": "Supported",
        "endpoints": {
            "analyze": "/api/analyze",
            "summarize": "/api/summarize",
            "health": "/health",
            "info": "/info",
            "docs": "/docs",
        },
    }
