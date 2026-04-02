"""
github_fetcher.py
Fetches repository structure and file contents via GitHub REST API.
Uses GITHUB_TOKEN from .env for higher rate limits (5000 req/hr vs 60).
"""

import os
import re
import base64
import requests
from pathlib import Path

def _github_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

# File extensions we analyze
SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".vue": "vue",
    ".svelte": "svelte",
    ".dart": "dart",
    ".scala": "scala",
    ".html": "html",
    ".css": "css",
    ".sh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
}

TEXT_EXTENSIONS = {".md", ".txt", ".rst", ".json", ".yaml", ".yml", ".toml", ".env.example", ".sh"}

MAX_FILES = 300          # Max files to fetch content for
MAX_FILE_SIZE = 300000   # Skip files > 300KB


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract owner and repo name from GitHub URL."""
    url = url.strip().rstrip("/")
    match = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?$", url)
    if not match:
        raise ValueError(f"Cannot parse GitHub URL: {url}")
    return match.group(1), match.group(2)


def github_get(url: str) -> dict | list:
    """Make a GitHub API request with error handling."""
    resp = requests.get(url, headers=_github_headers(), timeout=15)
    if resp.status_code == 403:
        raise Exception("GitHub API rate limit exceeded. Add a GITHUB_TOKEN to .env")
    if resp.status_code == 404:
        raise Exception(f"Repository not found: {url}")
    resp.raise_for_status()
    return resp.json()


def get_repo_tree(owner: str, repo: str) -> list[dict]:
    """Get the full file tree using the Git Trees API (recursive)."""
    # First get default branch
    repo_info = github_get(f"https://api.github.com/repos/{owner}/{repo}")
    default_branch = repo_info.get("default_branch", "main")

    # Get the tree recursively
    tree_data = github_get(
        f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    )
    return tree_data.get("tree", []), repo_info, default_branch


def fetch_file_content(owner: str, repo: str, path: str) -> str | None:
    """Fetch content of a single file via Contents API."""
    try:
        data = github_get(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}")
        if isinstance(data, dict) and data.get("encoding") == "base64":
            raw = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return raw
    except Exception as e:
        print(f"  [fetch_file] Skip {path}: {e}")
    return None


def build_file_tree(files: list[dict]) -> list[dict]:
    """Convert flat file list into nested tree structure for frontend."""
    root = {}

    for f in files:
        parts = f["path"].split("/")
        node = root
        for i, part in enumerate(parts[:-1]):
            node = node.setdefault(part, {"__type": "folder", "__children": {}})["__children"]
        fname = parts[-1]
        node[fname] = {
            "__type": "file",
            "name": fname,
            "path": f["path"],
            "lang": f.get("lang", ""),
            "lines": f.get("lines", 0),
            "complexity": f.get("complexity", 1),
            "functions": f.get("functions", 0),
        }

    def to_list(d: dict) -> list:
        result = []
        for name, val in sorted(d.items()):
            if val.get("__type") == "folder":
                result.append({
                    "name": name,
                    "type": "folder",
                    "open": True,
                    "children": to_list(val["__children"]),
                })
            elif val.get("__type") == "file":
                result.append({
                    "name": val["name"],
                    "type": "file",
                    "path": val["path"],
                    "lang": val["lang"],
                    "lines": val["lines"],
                    "complexity": val["complexity"],
                    "functions": val["functions"],
                })
        return result

    return to_list(root)


def fetch_repo(repo_url: str) -> dict:
    """
    Main entry point. Fetches repo metadata + file contents.
    Returns dict with: meta, files, file_tree, full_name
    """
    owner, repo_name = parse_repo_url(repo_url)
    print(f"  [fetcher] Owner: {owner}, Repo: {repo_name}")

    tree_items, repo_info, default_branch = get_repo_tree(owner, repo_name)
    print(f"  [fetcher] Total tree items: {len(tree_items)}, branch: {default_branch}")

    # Filter to supported code files
    code_files = []
    for item in tree_items:
        if item["type"] != "blob":
            continue
        path = item["path"]
        ext = Path(path).suffix.lower()
        size = item.get("size", 0)

        if ext in SUPPORTED_EXTENSIONS and size < MAX_FILE_SIZE:
            code_files.append({
                "path": path,
                "name": Path(path).name,
                "lang": SUPPORTED_EXTENSIONS[ext],
                "ext": ext,
                "size": size,
            })

    # No priority (fetch all equally)
    code_files.sort(key=lambda f: f["path"])  # just alphabetical
    code_files = code_files[:MAX_FILES]
    print(f"  [fetcher] Fetching content for {len(code_files)} files...")

    # Fetch content for each file
    files_with_content = []
    for i, f in enumerate(code_files):
        print(f"  [fetcher] {i+1}/{len(code_files)}: {f['path']}")
        content = fetch_file_content(owner, repo_name, f["path"])
        if content is None:
            continue

        lines = content.splitlines()
        f["content"] = content
        f["lines"] = len(lines)
        files_with_content.append(f)

    # Also try to fetch README
    readme_content = None
    for readme_name in ["README.md", "README.rst", "readme.md"]:
        try:
            readme_content = fetch_file_content(owner, repo_name, readme_name)
            if readme_content:
                break
        except Exception:
            pass

    # Build metadata
    meta = {
        "full_name": f"{owner}/{repo_name}",
        "owner": owner,
        "name": repo_name,
        "description": repo_info.get("description") or "No description available.",
        "language": repo_info.get("language") or "Unknown",
        "stars": repo_info.get("stargazers_count", 0),
        "forks": repo_info.get("forks_count", 0),
        "open_issues": repo_info.get("open_issues_count", 0),
        "default_branch": default_branch,
        "url": repo_url,
        "existing_readme": readme_content,
        "topics": repo_info.get("topics", []),
        "license": (repo_info.get("license") or {}).get("name", ""),
    }

    file_tree = build_file_tree(files_with_content)

    return {
        "full_name": f"{owner}/{repo_name}",
        "meta": meta,
        "files": files_with_content,
        "file_tree": file_tree,
    }
