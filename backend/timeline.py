"""
timeline.py — Git Commit Timeline for RepoLens

Fetches the last 100 commits via GitHub API and returns:
  - Commit frequency data (by day/week)
  - Most-changed files list
  - Contributor activity breakdown
  - Advanced metrics: commit types, day-of-week patterns, volatility, multi-timeframe analysis
"""

import os
import re
import requests
import statistics
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
    Returns enriched data with commit types, frequency patterns, volatility, and multi-timeframe analysis.
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
            "commit_types": {},
            "day_of_week": {},
            "frequency_buckets": {},
            "volatility": {},
            "timeframe_comparison": {},
        }

    # Parse commits into clean format
    commits = []
    daily_counts = Counter()
    commits_with_dates = []
    commit_types = Counter()
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

        # Categorize commit type
        commit_type = _categorize_commit_type(message)
        commit_types[commit_type] += 1

        commits.append({
            "sha": sha,
            "message": message[:120],
            "author": author_name,
            "date": date_key,
            "timestamp": date_str,
            "type": commit_type,
        })

        # Daily frequency
        if date_key:
            daily_counts[date_key] += 1
            commits_with_dates.append((date_key, commit_type))

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

    # Advanced metrics
    commit_types_breakdown = {
        "feature": commit_types.get("feature", 0),
        "bugfix": commit_types.get("bugfix", 0),
        "refactor": commit_types.get("refactor", 0),
        "docs": commit_types.get("docs", 0),
        "chore": commit_types.get("chore", 0),
        "other": commit_types.get("other", 0),
    }

    day_of_week_analysis = _get_day_of_week_distribution(commits_with_dates)
    frequency_buckets = _categorize_frequency_level(daily_counts)
    volatility = _calculate_volatility(daily_counts)
    timeframe_comparison = _get_multi_timeframe_view(daily_counts, len(commits))

    return {
        "commits": commits[:100],
        "frequency": dict(daily_counts),
        "weekly": weekly,
        "contributors": contributor_list[:20],
        "most_changed_files": most_changed,
        "summary": summary,
        "commit_types": commit_types_breakdown,
        "day_of_week": day_of_week_analysis,
        "frequency_buckets": frequency_buckets,
        "volatility": volatility,
        "timeframe_comparison": timeframe_comparison,
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


def _categorize_commit_type(message: str) -> str:
    """Classify commit message into type: feature, bugfix, refactor, docs, chore, other."""
    message_lower = message.lower()
    
    patterns = {
        "feature": r"^(feat|feature|add|new|implement|addition)",
        "bugfix": r"^(fix|bug|resolve|patch|hotfix)",
        "refactor": r"^(refactor|clean|improve|optimize|simplify)",
        "docs": r"^(doc|docs|documentation|readme|comment)",
        "chore": r"^(chore|build|ci|deps|dependency|update|upgrade|bump)",
    }
    
    for commit_type, pattern in patterns.items():
        if re.match(pattern, message_lower):
            return commit_type
    
    return "other"


def _categorize_frequency_level(daily_counts: Counter) -> dict:
    """Categorize days into intensity buckets: intense/normal/quiet/inactive."""
    if not daily_counts:
        return {"intense_days": 0, "normal_days": 0, "quiet_days": 0, "inactive_days": 0}
    
    counts_list = list(daily_counts.values())
    avg = statistics.mean(counts_list) if counts_list else 0
    
    intense = sum(1 for c in counts_list if c >= max(10, avg * 1.5))
    normal = sum(1 for c in counts_list if avg * 0.7 <= c < max(10, avg * 1.5))
    quiet = sum(1 for c in counts_list if 1 <= c < avg * 0.7)
    
    return {
        "intense_days": intense,
        "normal_days": normal,
        "quiet_days": quiet,
        "average_daily": round(avg, 1)
    }


def _calculate_volatility(daily_counts: Counter) -> dict:
    """Calculate commit frequency volatility (consistency score)."""
    if not daily_counts or len(daily_counts) < 2:
        return {"volatility": 0.0, "consistency": "stable", "std_dev": 0.0}
    
    counts_list = list(daily_counts.values())
    mean = statistics.mean(counts_list)
    std_dev = statistics.stdev(counts_list) if len(counts_list) > 1 else 0
    
    # Normalize volatility to 0-1 scale
    volatility = min(std_dev / max(mean, 1), 1.0)
    
    if volatility < 0.3:
        consistency = "very_stable"
    elif volatility < 0.5:
        consistency = "stable"
    elif volatility < 0.75:
        consistency = "moderate"
    else:
        consistency = "erratic"
    
    return {
        "volatility": round(volatility, 2),
        "consistency": consistency,
        "std_dev": round(std_dev, 1)
    }


def _get_day_of_week_distribution(commits_with_dates: list[tuple]) -> dict:
    """Analyze commit distribution by day of week."""
    day_counts = Counter()
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    for date_str, _ in commits_with_dates:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            day_name = days_order[dt.weekday()]
            day_counts[day_name] += 1
        except (ValueError, IndexError):
            continue
    
    total = sum(day_counts.values())
    distribution = {}
    for day in days_order:
        count = day_counts.get(day, 0)
        distribution[day] = {
            "commits": count,
            "percentage": round((count / total * 100) if total else 0, 1)
        }
    
    most_active = max(day_counts.items(), key=lambda x: x[1]) if day_counts else ("Unknown", 0)
    least_active = min(day_counts.items(), key=lambda x: x[1]) if day_counts else ("Unknown", 0)
    
    return {
        "distribution": distribution,
        "most_active_day": most_active[0],
        "least_active_day": least_active[0],
        "weekend_vs_weekday": {
            "weekday": sum(day_counts.get(d, 0) for d in days_order[:5]),
            "weekend": sum(day_counts.get(d, 0) for d in days_order[5:])
        }
    }


def _get_multi_timeframe_view(daily_counts: Counter, total_commits: int) -> dict:
    """Generate commit stats for multiple timeframes."""
    today = datetime.now()
    timeframes = {
        "last_7_days": 7,
        "last_30_days": 30,
        "last_90_days": 90
    }
    
    results = {"all_time": {"commits": total_commits}}
    
    for frame_name, days in timeframes.items():
        cutoff_date = today - timedelta(days=days)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        frame_commits = sum(count for date, count in daily_counts.items() if date >= cutoff_str)
        frame_days = len([count for date, count in daily_counts.items() if date >= cutoff_str])
        
        results[frame_name] = {
            "commits": frame_commits,
            "active_days": frame_days,
            "avg_per_day": round(frame_commits / max(frame_days, 1), 1)
        }
    
    return results
