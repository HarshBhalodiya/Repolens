"""
RepoLens - Git Parser Module

Extracts and analyzes commit metrics from local Git repositories
using subprocess and Pandas for data processing.
"""

import re
import subprocess
from collections import Counter
from io import StringIO

import pandas as pd


def extract_repo_metrics(repo_path: str) -> dict:
    """
    Extract comprehensive metrics from a Git repository.

    Uses `git log` to retrieve commit history, then processes the data
    with Pandas to compute various metrics including hourly distribution,
    top authors, code churn (additions/deletions), file hotspots,
    and average message length.

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        dict: Dictionary containing:
            - summary: Total commits, total authors, first/last commit dates
            - hourly_distribution: Commits grouped by hour of day (0-23)
            - top_authors: Authors ranked by commit count
            - code_churn: Daily additions/deletions over time
            - hotspots: Top 10 most frequently changed files
            - avg_message_length: Mean commit message length
    """
    # --- Subprocess Extraction (Basic Log) ---
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

    # --- Code Churn: Parse insertions/deletions from --shortstat ---
    code_churn = _parse_code_churn(repo_path)

    # --- File Hotspots: Detect most frequently changed files ---
    hotspots = _parse_file_hotspots(repo_path)

    return {
        "summary": {
            "total_commits": total_commits,
            "total_authors": total_authors,
            "first_commit": first_commit_str,
            "last_commit": last_commit_str,
        },
        "hourly_distribution": hourly_distribution,
        "top_authors": top_authors,
        "code_churn": code_churn,
        "hotspots": hotspots,
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
        "code_churn": [],
        "hotspots": [],
        "avg_message_length": 0,
    }


def _parse_code_churn(repo_path: str) -> list[dict]:
    """
    Parse code churn (additions/deletions) from git log --shortstat.

    Groups insertions and deletions by day and returns a time-ordered
    list of daily aggregates.

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        list[dict]: Array of {"date": "YYYY-MM-DD", "insertions": N, "deletions": M}
    """
    try:
        result = subprocess.run(
            [
                "git", "log",
                "--shortstat",
                "--pretty=format:COMMIT:%h|%an|%ad|%s",
                "--date=iso",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        output = result.stdout
    except Exception:
        return []

    if not output.strip():
        return []

    # Parse commits and their shortstat lines
    commits = []
    current_date = None

    for line in output.splitlines():
        line = line.strip()
        if line.startswith("COMMIT:"):
            # Extract date from the commit header
            parts = line.split("|")
            if len(parts) >= 3:
                try:
                    dt = pd.to_datetime(parts[2], utc=True)
                    current_date = dt.strftime("%Y-%m-%d")
                except Exception:
                    current_date = None
        elif line and current_date:
            # Parse shortstat: " 3 files changed, 45 insertions(+), 12 deletions(-)"
            insertions = 0
            deletions = 0

            # Extract insertions
            if "insertion" in line:
                match = re.search(r"(\d+)\s+insertion", line)
                if match:
                    insertions = int(match.group(1))

            # Extract deletions
            if "deletion" in line:
                match = re.search(r"(\d+)\s+deletion", line)
                if match:
                    deletions = int(match.group(1))

            commits.append({
                "date": current_date,
                "insertions": insertions,
                "deletions": deletions,
            })

    if not commits:
        return []

    # Group by date and aggregate
    churn_df = pd.DataFrame(commits)
    churn_df["date"] = pd.to_datetime(churn_df["date"])

    daily = (
        churn_df.groupby(churn_df["date"].dt.date)
        .agg({"insertions": "sum", "deletions": "sum"})
        .reset_index()
    )
    daily.columns = ["date", "insertions", "deletions"]
    daily["date"] = daily["date"].astype(str)
    daily = daily.sort_values("date")

    return daily.to_dict(orient="records")


def _parse_file_hotspots(repo_path: str) -> list[dict]:
    """
    Parse file hotspots by counting how many commits touched each file.

    Uses `git log --name-only` to list files changed per commit, then
    counts frequencies and returns the top 10.

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        list[dict]: Array of {"file_path": "src/api.py", "changes": 42}
    """
    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        output = result.stdout
    except Exception:
        return []

    if not output.strip():
        return []

    # Files/patterns to filter out as noise
    noise_patterns = {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        ".DS_Store",
        "npm-shrinkwrap.json",
        "composer.lock",
        "Gemfile.lock",
        "Cargo.lock",
        "poetry.lock",
        "Pipfile.lock",
    }

    counter: Counter = Counter()

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip noise files
        if line in noise_patterns:
            continue
        counter[line] += 1

    # Get top 10 most frequently changed files
    top_10 = counter.most_common(10)

    return [
        {"file_path": file_path, "changes": count}
        for file_path, count in top_10
    ]
