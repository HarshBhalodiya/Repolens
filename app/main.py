"""
RepoLens - Main Application

FastAPI application serving the Git repository analysis dashboard.
Supports both local Git repositories and remote GitHub URLs.
"""
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .ai_engine import answer_codebase_question, generate_standup_summary
from .db_client import get_cached_analysis, save_analysis_cache
from .cache_manager import clear_cache_except  # New import for cache cleanup
from .rag_indexer import index_codebase

def index_and_cleanup(real_path: str, repo_id: str, temp_cleanup_path: str | None):
    """Run codebase indexing in the background, then clean up temp clone folders if needed."""
    import logging
    try:
        result = index_codebase(real_path, repo_id)
        if result.get("status") == "error":
            # index_codebase() reports failure via return value, not exceptions.
            # That was being silently discarded before - log it so failures are
            # actually visible instead of leaving chat permanently broken.
            logging.getLogger(__name__).warning(
                "Background indexing failed for %s: %s", repo_id, result.get("message")
            )
    except Exception as e:
        logging.getLogger(__name__).warning("Background indexing failed for %s: %s", repo_id, e)
    finally:
        if temp_cleanup_path and os.path.exists(temp_cleanup_path):
            parent = os.path.dirname(temp_cleanup_path)
            shutil.rmtree(parent, ignore_errors=True)
from .dependency_parser import build_dependency_graph
from .git_parser import extract_repo_metrics
from .utils import (
    clone_github_repo,
    get_latest_commit_hash,
    is_github_url,
    validate_git_repo,
)

# Initialize FastAPI application
app = FastAPI(title="RepoLens", description="AI-powered local Git repository analyzer")

@app.on_event("startup")
def _warm_embeddings_model():
    """Pre-load the embedding model at server startup instead of on the
    first indexing/chat request, so users aren't hit with a multi-minute
    first-request delay while the model loads."""
    try:
        from .rag_indexer import _load_embeddings
        _load_embeddings()
        logging.getLogger(__name__).info("Embedding model pre-loaded.")
    except Exception as e:
        logging.getLogger(__name__).warning("Embedding model pre-load failed: %s", e)


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


# Pydantic model for the RAG codebase chat request
class ChatRequest(BaseModel):
    repo_path: str
    query: str


def _resolve_repo_path(repo_input: str) -> tuple:
    """
    Resolve a repo input to a local path, cloning remote URLs on demand.

    Returns (real_path, cleanup_dir) where cleanup_dir is the temporary
    clone directory to remove afterwards, or None for local paths.
    """
    if is_github_url(repo_input):
        cloned_path, _ = clone_github_repo(repo_input)
        return cloned_path, cloned_path
    return repo_input, None


def _cleanup_temp_repo(temp_path: str | None) -> None:
    """Remove a temporary cloned repo directory (no-op for local paths)."""
    if temp_path and os.path.exists(temp_path):
        parent = os.path.dirname(temp_path)
        shutil.rmtree(parent, ignore_errors=True)




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
async def analyze_repository(request: AnalysisRequest, background_tasks: BackgroundTasks):
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
    indexing_delegated = False

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
                # Ensure the cached response has languages and daily_distribution (handles migration for older cache entries)
                needs_update = False
                if "daily_distribution" not in cached:
                    fresh_metrics = extract_repo_metrics(real_path)
                    if fresh_metrics and not fresh_metrics.get("_error"):
                        cached = fresh_metrics
                        needs_update = True

                if "languages" not in cached and not needs_update:
                    from .git_parser import get_language_distribution
                    cached["languages"] = get_language_distribution(real_path)
                    needs_update = True

                if needs_update:
                    cache_payload = {
                        k: v for k, v in cached.items() if not k.startswith("_")
                    }
                    save_analysis_cache(repo_input, commit_hash, cache_payload)
                # Attach per-request metadata to the cached payload
                cached["_source"] = source_label
                cached["_input"] = repo_input

                # Only re-index when the commit actually changed since the
                # last successful index. `rag_indexed_commit` is stamped
                # into the cache payload after a successful index (see
                # below) - if it already matches the current commit_hash,
                # the codebase content hasn't changed, so re-embedding and
                # re-uploading to Supabase would just redo identical work
                # every time the same repo is analyzed again.
                if cached.get("rag_indexed_commit") != commit_hash:
                    index_result = index_codebase(real_path, repo_input)
                    if index_result.get("status") == "error":
                        logging.getLogger(__name__).warning(
                            "Indexing failed for %s: %s", repo_input, index_result.get("message")
                        )
                    else:
                        cached["rag_indexed_commit"] = commit_hash
                        cache_payload = {
                            k: v for k, v in cached.items() if not k.startswith("_")
                        }
                        save_analysis_cache(repo_input, commit_hash, cache_payload)
                clear_cache_except(repo_input)
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

        # Index first so a successful stamp can be included in the same
        # cache write below - avoids caching a payload that claims to be
        # indexed when indexing actually failed.
        index_result = index_codebase(real_path, repo_input)
        if index_result.get("status") == "error":
            logging.getLogger(__name__).warning(
                "Indexing failed for %s: %s", repo_input, index_result.get("message")
            )
        elif commit_hash:
            metrics["rag_indexed_commit"] = commit_hash

        # Persist to cache only if the analysis is meaningful - never cache
        # empty/errored results. Use the user-provided input as the recorded
        # path so remote clones don't store dead temp-dir paths.
        if commit_hash and _is_valid_cached_payload(metrics):
            cache_payload = {
                k: v for k, v in metrics.items() if not k.startswith("_")
            }
            save_analysis_cache(repo_input, commit_hash, cache_payload)

        clear_cache_except(repo_input)
        return {"cached": False, "data": metrics}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}",
        )
    finally:
        # Clean up temporary cloned repo immediately only if indexing wasn't delegated
        if not indexing_delegated and temp_cleanup_path and os.path.exists(temp_cleanup_path):
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
        real_path, temp_cleanup_path = _resolve_repo_path(repo_input)
        return generate_standup_summary(real_path)
    except Exception as e:
        return {
            "summary": f"Failed to generate standup summary: {str(e)}",
            "status": "error",
        }
    finally:
        _cleanup_temp_repo(temp_cleanup_path)


# POST endpoint to manually (re)index a repo for RAG chat, synchronously,
# so failures are returned to the caller instead of vanishing into a
# background task.
@app.post(
    "/api/index", response_model=dict, dependencies=[Depends(require_api_key)]
)
def index_repo(request: RepoPathRequest):
    """
    (Re)build the RAG index for a repository and report success/failure directly.

    Accepts JSON: {"repo_path": str}

    Response shape:
        {"indexed_files": int, "total_chunks": int, "status": "completed"}
        or {"status": "error", "message": str}
    """
    if not request.repo_path or not request.repo_path.strip():
        raise HTTPException(
            status_code=400,
            detail="Repository path cannot be empty.",
        )

    repo_input = request.repo_path.strip()
    temp_cleanup_path = None
    try:
        real_path, temp_cleanup_path = _resolve_repo_path(repo_input)
        return index_codebase(real_path, repo_input)
    except Exception as e:
        return {"status": "error", "message": f"Failed to index repository: {str(e)}"}
    finally:
        _cleanup_temp_repo(temp_cleanup_path)


# POST endpoint for RAG codebase chat
@app.post(
    "/api/chat", response_model=dict, dependencies=[Depends(require_api_key)]
)
def chat_with_codebase(request: ChatRequest):
    """
    Answer a question about an indexed codebase using RAG + local Ollama.

    Accepts JSON: {"repo_path": str, "query": str}

    Response shape:
        {"answer": str, "sources": [str], "status": "success" | "error"}

    Note: intentionally a sync `def` endpoint so the (CPU/IO-heavy)
    embedding retrieval + LLM call run in FastAPI's threadpool.
    """
    if not request.repo_path or not request.repo_path.strip():
        raise HTTPException(
            status_code=400,
            detail="Repository path cannot be empty.",
        )
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    repo_input = request.repo_path.strip()
    try:
        # Directly query using the repo identifier. No cloning required!
        return answer_codebase_question(repo_input, request.query.strip())
    except Exception as e:
        return {
            "answer": f"Failed to answer the question: {str(e)}",
            "sources": [],
            "status": "error",
        }


# POST endpoint for the Tree-sitter dependency graph
@app.post(
    "/api/dependencies",
    response_model=dict,
    dependencies=[Depends(require_api_key)],
)
def dependency_graph(request: RepoPathRequest):
    """
    Build a file-level dependency knowledge graph for a repository.

    Accepts JSON: {"repo_path": str}

    Response shape:
        {"nodes": [{"id", "label"}], "edges": [{"source", "target"}],
         "status": "completed"}
        or {"status": "error", "message": str, "nodes": [], "edges": []}.

    Note: intentionally a sync `def` endpoint so the (CPU-heavy)
    Tree-sitter parsing runs in FastAPI's threadpool.
    """
    if not request.repo_path or not request.repo_path.strip():
        raise HTTPException(
            status_code=400,
            detail="Repository path cannot be empty.",
        )

    repo_input = request.repo_path.strip()
    temp_cleanup_path = None
    try:
        real_path, temp_cleanup_path = _resolve_repo_path(repo_input)
        return build_dependency_graph(real_path)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to build dependency graph: {str(e)}",
            "nodes": [],
            "edges": [],
        }
    finally:
        _cleanup_temp_repo(temp_cleanup_path)


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
            "index": "/api/index",
            "chat": "/api/chat",
            "dependencies": "/api/dependencies",
            "health": "/health",
            "info": "/info",
            "docs": "/docs",
        },
    }
