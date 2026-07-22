"""
RepoLens - Validation Utilities

Helper functions for validating repository paths, detecting remote URLs,
and cloning remote repositories for analysis.
"""

import os
import re
import shutil
import subprocess
import tempfile

# Regex patterns for supported remote Git repository URLs
GITHUB_HTTPS_PATTERN = re.compile(
    r"^https://(?:www\.)?github\.com/([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?/?$"
)
GITHUB_SSH_PATTERN = re.compile(
    r"^git@github\.com:([a-zA-Z0-9_.-]+)/([a-zA-Z0-9_.-]+?)(?:\.git)?$"
)


def is_github_url(path: str) -> bool:
    """
    Check if the given string is a GitHub repository URL.

    Supports both HTTPS and SSH formats:
    - https://github.com/owner/repo
    - https://github.com/owner/repo.git
    - git@github.com:owner/repo
    - git@github.com:owner/repo.git

    Args:
        path (str): String to check

    Returns:
        bool: True if the string matches a GitHub URL pattern
    """
    if not path or not isinstance(path, str):
        return False
    stripped = path.strip()
    return bool(
        GITHUB_HTTPS_PATTERN.match(stripped)
        or GITHUB_SSH_PATTERN.match(stripped)
    )


def extract_repo_info(url: str) -> tuple[str, str]:
    """
    Extract the owner and repository name from a GitHub URL.

    Args:
        url (str): GitHub repository URL

    Returns:
        tuple[str, str]: (owner, repo_name)

    Raises:
        ValueError: If the URL format is not recognized
    """
    stripped = url.strip()
    match = GITHUB_HTTPS_PATTERN.match(stripped) or GITHUB_SSH_PATTERN.match(stripped)
    if not match:
        raise ValueError(f"Unrecognized GitHub URL format: {url}")
    owner = match.group(1)
    repo_name = match.group(2)
    # repo_name from regex already excludes .git suffix
    return (owner, repo_name)


def clone_github_repo(url: str, timeout: int = 120) -> tuple[str, str]:
    """
    Clone a GitHub repository to a temporary directory.

    Args:
        url (str): GitHub repository URL
        timeout (int): Maximum clone time in seconds (default 120)

    Returns:
        tuple[str, str]: (path_to_cloned_repo, repo_name)

    Raises:
        ValueError: If the URL is not a valid GitHub URL
        RuntimeError: If the clone fails
    """
    if not is_github_url(url):
        raise ValueError(f"Not a valid GitHub URL: {url}")

    _, repo_name = extract_repo_info(url)

    # Create a temporary directory
    temp_dir = tempfile.mkdtemp(prefix="repolens_")
    clone_target = os.path.join(temp_dir, repo_name)

    try:
        result = subprocess.run(
            ["git", "clone", url.strip(), clone_target],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            # Clean up on failure
            shutil.rmtree(temp_dir, ignore_errors=True)
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"Failed to clone repository: {stderr or 'Unknown error'}"
            )
    except subprocess.TimeoutExpired:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(
            "Clone timed out. The repository may be too large."
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to clone repository: {str(e)}")

    return (clone_target, repo_name)


def validate_git_repo(path: str) -> tuple[bool, str]:
    """
    Validate that the given path is a valid Git repository.

    Checks:
    1. Path exists and is a directory
    2. Path is inside a valid Git working tree (via git rev-parse)

    Args:
        path (str): Path to check

    Returns:
        tuple[bool, str]: (is_valid, message)
            - (True, "Valid") if the path is a valid Git repository
            - (False, error_description) if validation fails
    """
    # Check if path exists and is a directory
    if not os.path.exists(path):
        return (False, "Path does not exist or is not a directory.")
    if not os.path.isdir(path):
        return (False, "Path does not exist or is not a directory.")

    # Check if the directory is inside a valid Git working tree
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return (False, "Directory is not a valid Git repository.")
    except FileNotFoundError:
        return (False, "Git is not installed or not found in system PATH.")
    except subprocess.TimeoutExpired:
        return (False, "Git command timed out. The repository may be too large or inaccessible.")
    except Exception as e:
        return (False, f"Error checking Git repository: {str(e)}")

    return (True, "Valid")
