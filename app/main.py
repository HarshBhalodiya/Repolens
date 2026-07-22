"""
RepoLens - Main Application

FastAPI application serving the Git repository analysis dashboard.
Supports both local Git repositories and remote GitHub URLs.
"""

import os
import shutil

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .git_parser import extract_repo_metrics
from .utils import clone_github_repo, is_github_url, validate_git_repo

# Initialize FastAPI application
app = FastAPI(title="RepoLens", description="AI-powered local Git repository analyzer")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic model for analysis request
class AnalysisRequest(BaseModel):
    repo_path: str


# POST endpoint for repository analysis
@app.post("/api/analyze", response_model=dict)
async def analyze_repository(request: AnalysisRequest):
    """
    Analyze a Git repository and return commit metrics.

    Accepts either:
    - A local file system path to a Git repository
    - A GitHub URL (https://github.com/owner/repo or git@github.com:owner/repo)

    For remote URLs, the repo is cloned to a temporary directory,
    analyzed, and then cleaned up automatically.
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

        # Extract metrics
        metrics = extract_repo_metrics(real_path)

        # Add metadata about the source
        metrics["_source"] = source_label
        metrics["_input"] = repo_input

        return metrics

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


# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")


# Root endpoint serves the main HTML page
@app.get("/")
async def read_root():
    """Serve the main HTML page."""
    return FileResponse("static/index.html")


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
            "health": "/health",
            "info": "/info",
            "docs": "/docs",
        },
    }
