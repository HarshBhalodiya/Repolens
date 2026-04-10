"""
timeline.py — Git Commit Timeline for RepoLens

Fetches the last 100 commits via GitHub API and returns:
  - Commit frequency data (by day/week)
  - Most-changed files list
  - Contributor activity breakdown
"""

import os
import re
import requests
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from typing import Optional


def _github_headers() -> dict:
    """Build GitHub API request headers."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract owner and repo name from GitHub URL."""
    url = url.strip().rstrip("/")
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise ValueError(f"Cannot parse GitHub URL: {url}")
    return match.group(1), match.group(2)


def fetch_commits(repo_url: str, max_commits: int = 100) -> list[dict]:
    """
    Fetch the last N commits from GitHub API.
    Returns raw commit data list.
    """
    owner, repo = parse_repo_url(repo_url)
    headers = _github_headers()
    commits = []
    page = 1
    per_page = min(max_commits, 100)

    while len(commits) < max_commits:
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits",
                headers=headers,
                params={"per_page": per_page, "page": page},
                timeout=15,
            )
            if resp.status_code != 200:
                print(f"[timeline] GitHub API error {resp.status_code}: {resp.text[:200]}")
                break

            batch = resp.json()
            if not batch:
                break

            commits.extend(batch)
            if len(batch) < per_page:
                break
            page += 1

        except Exception as e:
            print(f"[timeline] Error fetching commits: {e}")
            break

    return commits[:max_commits]


def build_timeline(repo_url: str) -> dict:
    """
    Build a complete timeline view for the repository.
    Returns: {
        commits: [...],
        frequency: { date: count, ... },
        weekly: [{ week: ..., count: ... }, ...],
        contributors: [{ name, email, commits, last_active }, ...],
        most_changed_files: [{ file, changes }, ...],
        summary: { total_commits, active_days, most_active_day, ... }
    }
    """
    raw_commits = fetch_commits(repo_url)

    if not raw_commits:
        return {
            "commits": [],
            "frequency": {},
            "weekly": [],
            "contributors": [],
            "most_changed_files": [],
            "summary": {"total_commits": 0},
        }

    # Parse commits into clean format
    commits = []
    daily_counts = Counter()
    contributors = defaultdict(lambda: {"commits": 0, "last_active": None})
    file_changes = Counter()

    for c in raw_commits:
        sha = c.get("sha", "")[:7]
        commit_data = c.get("commit", {})
        author = commit_data.get("author", {})
        message = commit_data.get("message", "").split("\n")[0]  # first line only
        date_str = author.get("date", "")
        author_name = author.get("name", "Unknown")
        author_email = author.get("email", "")

        # Parse date
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            date_key = dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            dt = None
            date_key = ""

        commits.append({
            "sha": sha,
            "message": message[:120],
            "author": author_name,
            "date": date_key,
            "timestamp": date_str,
        })

        # Daily frequency
        if date_key:
            daily_counts[date_key] += 1

        # Contributors
        contributors[author_name]["commits"] += 1
        contributors[author_name]["email"] = author_email
        if dt and (contributors[author_name]["last_active"] is None or date_str > contributors[author_name]["last_active"]):
            contributors[author_name]["last_active"] = date_str

    # Build weekly aggregation
    weekly = _aggregate_weekly(daily_counts)

    # Fetch changed files for top commits (limited to avoid rate limits)
    owner, repo = parse_repo_url(repo_url)
    headers = _github_headers()
    for c in raw_commits[:20]:  # Only check first 20 commits for changed files
        sha = c.get("sha", "")
        try:
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                detail = resp.json()
                for f in detail.get("files", []):
                    fname = f.get("filename", "")
                    changes = f.get("changes", 0)
                    file_changes[fname] += changes
        except Exception:
            continue

    # Sort contributors
    contributor_list = sorted(
        [
            {
                "name": name,
                "email": info["email"],
                "commits": info["commits"],
                "last_active": info["last_active"],
            }
            for name, info in contributors.items()
        ],
        key=lambda x: x["commits"],
        reverse=True,
    )

    # Most changed files
    most_changed = [
        {"file": fname, "changes": count}
        for fname, count in file_changes.most_common(15)
    ]

    # Summary
    dates = sorted(daily_counts.keys())
    summary = {
        "total_commits": len(commits),
        "active_days": len(daily_counts),
        "date_range": f"{dates[0]} to {dates[-1]}" if dates else "",
        "most_active_day": daily_counts.most_common(1)[0] if daily_counts else ("", 0),
        "total_contributors": len(contributors),
        "avg_commits_per_day": round(len(commits) / max(len(daily_counts), 1), 1),
    }

    return {
        "commits": commits[:100],
        "frequency": dict(daily_counts),
        "weekly": weekly,
        "contributors": contributor_list[:20],
        "most_changed_files": most_changed,
        "summary": summary,
    }


def _aggregate_weekly(daily_counts: Counter) -> list[dict]:
    """Aggregate daily counts into weekly buckets."""
    if not daily_counts:
        return []

    weekly = defaultdict(int)
    for date_str, count in daily_counts.items():
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            # Week starts on Monday
            week_start = dt - timedelta(days=dt.weekday())
            week_key = week_start.strftime("%Y-%m-%d")
            weekly[week_key] += count
        except ValueError:
            continue

    return sorted(
        [{"week": week, "count": count} for week, count in weekly.items()],
        key=lambda x: x["week"],
    )
