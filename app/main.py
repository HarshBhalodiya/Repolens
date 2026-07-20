from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Initialize FastAPI application
app = FastAPI(title="RepoLens", description="AI-powered local Git repository analyzer")

# CORS middleware for future frontend development
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


# Mock data for Chart.js consumption
def generate_mock_data() -> dict:
    """Generate mock data representing commit activity by hour of day."""
    # Simulate realistic commit patterns: low activity at night, peaks during work hours
    hourly_activity = [
        {"hour": 0, "commits": 2}, {"hour": 1, "commits": 1},
        {"hour": 2, "commits": 0}, {"hour": 3, "commits": 1},
        {"hour": 4, "commits": 0}, {"hour": 5, "commits": 0},
        {"hour": 6, "commits": 3}, {"hour": 7, "commits": 8},
        {"hour": 8, "commits": 15}, {"hour": 9, "commits": 22},
        {"hour": 10, "commits": 25}, {"hour": 11, "commits": 28},
        {"hour": 12, "commits": 30}, {"hour": 13, "commits": 27},
        {"hour": 14, "commits": 24}, {"hour": 15, "commits": 20},
        {"hour": 16, "commits": 18}, {"hour": 17, "commits": 15},
        {"hour": 18, "commits": 12}, {"hour": 19, "commits": 8},
        {"hour": 20, "commits": 6}, {"hour": 21, "commits": 4},
        {"hour": 22, "commits": 3}, {"hour": 23, "commits": 2}
    ]
    
    commit_counts = [item["commits"] for item in hourly_activity]
    
    return {
        "status": "success",
        "message": "Analysis completed successfully",
        "data": {
            "hourly_activity": hourly_activity,
            "summary": {
                "total_commits": sum(commit_counts),
                "peak_hour": hourly_activity[commit_counts.index(max(commit_counts))]["hour"],
                "average_commits": round(sum(commit_counts) / len(commit_counts), 2)
            }
        },
        "metadata": {
            "analysis_type": "hourly_activity",
            "generated_at": "2026-07-18T00:00:00Z",
            "version": "1.0.0"
        }
    }


# POST endpoint for repository analysis
@app.post("/api/analyze", response_model=dict)
async def analyze_repository(request: AnalysisRequest):
    """
    Analyze a local Git repository and return commit activity data.
    
    For Week 1, this returns mock data. Real analysis will be implemented
    in subsequent weeks.
    """
    try:
        # Validate input
        if not request.repo_path or not request.repo_path.strip():
            raise HTTPException(
                status_code=400,
                detail="Repository path cannot be empty"
            )
        
        # For now, return mock data
        # In future weeks, this will call git_parser.extract_repo_metrics()
        mock_response = generate_mock_data()
        mock_response["input_path"] = request.repo_path.strip()
        
        return mock_response
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception:
        # Handle unexpected errors without leaking internal details
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the request"
        )


# Mount static files directory
# This serves static assets at /static path
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
        "status": "Week 1 - Boilerplate",
        "endpoints": {
            "analyze": "/api/analyze",
            "health": "/health",
            "info": "/info",
            "docs": "/docs"
        }
    }