"""
RepoLens - Git Parser Module

Extracts and analyzes commit metrics from local Git repositories
using subprocess and Pandas for data processing.
"""

import subprocess
from io import StringIO

import pandas as pd


def extract_repo_metrics(repo_path: str) -> dict:
    """
    Extract comprehensive metrics from a Git repository.

    Uses `git log` to retrieve commit history, then processes the data
    with Pandas to compute various metrics including hourly distribution,
    top authors, and average message length.

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        dict: Dictionary containing:
            - summary: Total commits, total authors, first/last commit dates
            - hourly_distribution: Commits grouped by hour of day (0-23)
            - top_authors: Authors ranked by commit count
            - avg_message_length: Mean commit message length
    """
    # --- Subprocess Extraction ---
    try:
        result = subprocess.run(
            [
                "git", "log",
                "--pretty=format:%h|%an|%ad|%s",
                "--date=iso",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        stdout = result.stdout
    except subprocess.TimeoutExpired:
        return _empty_metrics("Git log command timed out.")
    except FileNotFoundError:
        return _empty_metrics("Git is not installed or not found in system PATH.")
    except Exception as e:
        return _empty_metrics(f"Error running git log: {str(e)}")

    # --- Zero-Commit Handling ---
    if not stdout.strip():
        return _empty_metrics()

    # --- Pandas Processing ---
    try:
        # Load text stream into DataFrame
        df = pd.read_csv(
            StringIO(stdout),
            sep="|",
            header=None,
            names=["hash", "author", "date", "subject"],
            dtype={"hash": str, "author": str, "subject": str},
        )
    except Exception as e:
        return _empty_metrics(f"Error parsing git log output: {str(e)}")

    # Drop any rows with missing critical data
    df = df.dropna(subset=["date", "author"])

    if df.empty:
        return _empty_metrics()

    # Parse date column
    df["date"] = pd.to_datetime(df["date"], utc=True)

    # Extract hour from commit date (UTC)
    df["hour"] = df["date"].dt.hour

    # --- Compute 24-Hour Distribution ---
    hourly_counts = (
        df.groupby("hour")
        .size()
        .reindex(range(24), fill_value=0)
        .reset_index(name="commits")
    )
    hourly_distribution = hourly_counts.to_dict(orient="records")

    # --- Compute Summary ---
    total_commits = len(df)
    total_authors = df["author"].nunique()
    first_commit = df["date"].min()
    last_commit = df["date"].max()

    # Format dates as ISO strings for JSON serialization
    first_commit_str = first_commit.isoformat() if pd.notna(first_commit) else None
    last_commit_str = last_commit.isoformat() if pd.notna(last_commit) else None

    # --- Compute Top Authors ---
    # value_counts() returns Series(index=author_name, values=count)
    # reset_index() gives DataFrame columns=["author", "count"]
    author_counts = (
        df["author"]
        .value_counts()
        .reset_index()
        .rename(columns={"count": "commits"})
        .head(20)
    )
    top_authors = author_counts.to_dict(orient="records")

    # --- Compute Average Message Length ---
    avg_message_length = round(float(df["subject"].str.len().mean()), 1)

    return {
        "summary": {
            "total_commits": total_commits,
            "total_authors": total_authors,
            "first_commit": first_commit_str,
            "last_commit": last_commit_str,
        },
        "hourly_distribution": hourly_distribution,
        "top_authors": top_authors,
        "avg_message_length": avg_message_length,
    }


def _empty_metrics(reason: str = "") -> dict:
    """
    Return an empty metrics payload, typically for repositories with no commits.

    Args:
        reason (str): Optional reason string (not included in output)

    Returns:
        dict: Skeleton metrics structure with all zeros/empty values
    """
    return {
        "summary": {
            "total_commits": 0,
            "total_authors": 0,
            "first_commit": None,
            "last_commit": None,
        },
        "hourly_distribution": [{"hour": h, "commits": 0} for h in range(24)],
        "top_authors": [],
        "avg_message_length": 0,
    }
