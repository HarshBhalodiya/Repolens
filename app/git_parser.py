"""
RepoLens - Git Parser Module

Extracts and analyzes commit metrics from local Git repositories
using subprocess and Pandas for data processing.
"""

import os
import re
import subprocess
from collections import Counter
from pathlib import Path

import pandas as pd

# ASCII Unit Separator (0x1F). Effectively never appears in commit metadata,
# unlike "|" which regularly shows up in commit subjects (e.g. conventional
# commit scopes, piped shell examples, markdown tables). Using it as the
# field delimiter means we can split on a fixed byte instead of running the
# output through a CSV parser, which sidesteps quoting/escaping edge cases
# (an unbalanced `"` in a commit message used to corrupt column alignment)
# entirely.
FIELD_SEP = "\x1f"


def extract_repo_metrics(repo_path: str) -> dict:
    """
    Extract comprehensive metrics from a Git repository.

    Uses `git log` to retrieve commit history, then processes the data
    with Pandas to compute various metrics including daily distribution,
    top authors, code churn (additions/deletions), file hotspots,
    and average message length.

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        dict: Dictionary containing:
            - summary: Total commits, total authors, first/last commit dates
            - daily_distribution: Commits grouped by date (YYYY-MM-DD)
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
                f"--pretty=format:%h{FIELD_SEP}%an{FIELD_SEP}%ae{FIELD_SEP}%ad{FIELD_SEP}%s",
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

    # --- Manual Row Parsing ---
    # Split on FIELD_SEP ourselves rather than pd.read_csv: commit subjects
    # are free-form text and must never be mistaken for CSV syntax (quotes,
    # embedded delimiters, etc). maxsplit=4 keeps the subject intact even if
    # it happens to contain FIELD_SEP-adjacent bytes.
    rows = []
    for line in stdout.split("\n"):
        if not line:
            continue
        parts = line.split(FIELD_SEP, 4)
        if len(parts) != 5:
            # Malformed line (should not happen, but skip rather than crash
            # the whole analysis over a single bad row).
            continue
        commit_hash, author, author_email, date, subject = parts
        rows.append(
            {
                "hash": commit_hash,
                "author": author,
                "author_email": author_email,
                "date": date,
                # Keep empty subjects as "" (not NaN) so they still count
                # toward total_commits and don't silently disappear from
                # avg_message_length.
                "subject": subject,
            }
        )

    if not rows:
        return _empty_metrics()

    df = pd.DataFrame(rows)

    # Drop any rows with missing critical data
    df = df.dropna(subset=["date", "author"])

    if df.empty:
        return _empty_metrics()

    # Parse date column
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    df = df.dropna(subset=["date"])

    if df.empty:
        return _empty_metrics()
    # --- Compute Daily Distribution ---
    df["day"] = df["date"].dt.strftime("%Y-%m-%d")
    daily_counts = (
        df.groupby("day")
        .size()
        .reset_index(name="commits")
    )
    daily_counts = daily_counts.sort_values("day")


    daily_distribution = daily_counts.to_dict(orient="records")


    # --- Compute Summary ---
    total_commits = len(df)
    # Identity = author email when present (a person's display name can
    # change across commits, e.g. "J. Smith" vs "Jane Smith"; the email is
    # the far more reliable, git-standard identity key). Fall back to name
    # for the rare commit with no configured email.
    identity_key = df["author_email"].where(
        df["author_email"].astype(bool), df["author"]
    )
    total_authors = identity_key.nunique()
    first_commit = df["date"].min()
    last_commit = df["date"].max()

    # Format dates as ISO strings for JSON serialization
    first_commit_str = first_commit.isoformat() if pd.notna(first_commit) else None
    last_commit_str = last_commit.isoformat() if pd.notna(last_commit) else None

    # --- Compute Top Authors ---
    # Group by identity (email) so the same person under slightly different
    # display names is counted once, then show their most-used display name.
    df["_identity"] = identity_key
    grouped = df.groupby("_identity")
    author_counts = (
        grouped.size()
        .reset_index(name="commits")
        .sort_values("commits", ascending=False)
        .head(20)
    )
    # Attach the most frequently used display name for each identity
    display_names = (
        df.groupby("_identity")["author"]
        .agg(lambda s: s.value_counts().idxmax())
    )
    author_counts["author"] = author_counts["_identity"].map(display_names)
    top_authors = author_counts[["author", "commits"]].to_dict(orient="records")

    # --- Compute Average Message Length ---
    avg_message_length = round(float(df["subject"].fillna("").str.len().mean()), 1)

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
        "daily_distribution": daily_distribution,
        "top_authors": top_authors,
        "code_churn": code_churn,
        "hotspots": hotspots,
        "languages": get_language_distribution(repo_path),
        "avg_message_length": avg_message_length,
    }


def get_language_distribution(repo_path: str) -> list:
    """
    Compute programming language distribution based on file size.
    """
    ignored = {
        ".git", "node_modules", "venv", "__pycache__", "dist", "build",
        ".venv", "env", ".env", "chroma_db", ".pytest_cache", ".idea", ".vscode"
    }
    lang_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".html": "HTML",
        ".css": "CSS",
        ".json": "JSON",
        ".md": "Markdown",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".c": "C",
        ".cpp": "C++",
        ".h": "C/C++ Header",
        ".cs": "C#",
        ".sql": "SQL",
        ".sh": "Shell",
        ".yml": "YAML",
        ".yaml": "YAML",
    }
    sizes = {}
    total_size = 0

    ignored_files = {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "composer.lock",
        "poetry.lock",
        "Gemfile.lock",
        "Cargo.lock",
    }

    for root, dirs, names in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in ignored]
        for name in names:
            if name in ignored_files:
                continue
            ext = Path(name).suffix.lower()
            if ext in lang_map:
                lang = lang_map[ext]
                full_path = os.path.join(root, name)
                try:
                    if os.path.islink(full_path):
                        continue
                    sz = os.path.getsize(full_path)
                    if sz > 1_000_000:
                        continue
                    sizes[lang] = sizes.get(lang, 0) + sz
                    total_size += sz
                except OSError:
                    continue

    if total_size == 0:
        return []

    dist = []
    for lang, sz in sizes.items():
        percentage = round((sz / total_size) * 100, 1)
        if percentage >= 0.1:
            dist.append({"language": lang, "percentage": percentage, "size": sz})

    dist.sort(key=lambda x: x["size"], reverse=True)
    return dist


def _empty_metrics(reason: str = "") -> dict:
    """
    Return an empty metrics payload, typically for repositories with no commits.

    Args:
        reason (str): Optional reason string. When provided it is included
            as the `_error` key so callers can surface why analysis failed
            instead of showing a silently blank dashboard.

    Returns:
        dict: Skeleton metrics structure with all zeros/empty values
    """
    metrics = {
        "summary": {
            "total_commits": 0,
            "total_authors": 0,
            "first_commit": None,
            "last_commit": None,
        },
        "daily_distribution": [],
        "top_authors": [],
        "code_churn": [],
        "hotspots": [],
        "languages": [],
        "avg_message_length": 0,
    }
    if reason:
        metrics["_error"] = reason
    return metrics


def _parse_code_churn(repo_path: str) -> list[dict]:
    """
    Parse code churn (additions/deletions) from git log --shortstat.

    Groups insertions and deletions by day and returns a time-ordered
    list of daily aggregates.

    Note: by default `git log` does not print a diffstat for merge commits
    (it only shows the combined diff with `-m`/`-c`), so merge commits
    contribute 0 insertions/deletions here even though they are counted in
    `summary.total_commits`. This matches standard `git log` / `git show`
    behavior and is intentional, not a parsing bug.

    Binary file changes also contribute 0 insertions/deletions (git prints
    no `N insertions`/`N deletions` tokens for them), so churn statistics
    already exclude binary content without extra filtering.

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
                f"--pretty=format:COMMIT:%h{FIELD_SEP}%an{FIELD_SEP}%ad{FIELD_SEP}%s",
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
            parts = line[len("COMMIT:"):].split(FIELD_SEP)
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

    Uses `git log --numstat` to list files changed per commit, then
    counts frequencies and returns the top 10. Binary file changes are
    excluded (git prints `-\t-` instead of a numeric diff for them).

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        list[dict]: Array of {"file_path": "src/api.py", "changes": 42}
    """
    try:
        result = subprocess.run(
            ["git", "log", "--numstat", "--pretty=format:"],
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

    # --numstat emits one line per changed file: "added\tdeleted\tpath".
    # Binary files appear as "-\t-\tpath" and are skipped so binary assets
    # (images, archives, compiled artifacts) never pollute the hotspot
    # ranking with noise.
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, deleted, file_path = parts
        if added == "-" and deleted == "-":
            continue  # binary file change — excluded from hotspot stats
        # Skip noise files
        if file_path in noise_patterns:
            continue
        counter[file_path] += 1

    # Get top 10 most frequently changed files
    top_10 = counter.most_common(10)

    return [
        {"file_path": file_path, "changes": count}
        for file_path, count in top_10
    ]
