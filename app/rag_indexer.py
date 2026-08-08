"""
RepoLens - RAG Codebase Indexer

Walks a repository, chunks supported source files, embeds them locally
with sentence-transformers (all-MiniLM-L6-v2), and stores the vectors
in Supabase (pgvector) for retrieval-augmented search.

Optional runtime dependencies (only needed for /api/index_codebase):

    pip install langchain langchain-community langchain-huggingface \
        langchain-text-splitters sentence-transformers

All heavy imports happen lazily so the rest of RepoLens keeps working
when the RAG stack is not installed.
"""

import hashlib
import logging
import os

logger = logging.getLogger(__name__)

# Directories that are never walked into.
IGNORED_DIRS = {".git", "node_modules", "venv", "__pycache__", "dist", "build"}

# File extensions that get indexed.
SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".html", ".css", ".json", ".md"}

# Files larger than this are skipped (typically vendored or generated
# bundles that would produce low-quality, high-cost chunks).
MAX_FILE_BYTES = 1_000_000

# Constants for RAG process.

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def _collect_source_files(repo_path: str) -> list[str]:
    """
    Walk `repo_path` and return the absolute paths of supported files.

    Ignored directories are pruned in-place so os.walk never descends
    into them, and oversized files are excluded.

    Args:
        repo_path (str): Path to the repository to index

    Returns:
        list[str]: Absolute paths of indexable files
    """
    files: list[str] = []
    for root, dirs, names in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in names:
            if os.path.splitext(name)[1].lower() not in SUPPORTED_EXTENSIONS:
                continue
            full_path = os.path.join(root, name)
            try:
                if os.path.getsize(full_path) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(full_path)
    return files


def _read_file_text(full_path: str) -> str:
    """
    Read a text file as UTF-8, returning "" for unreadable/binary content.

    Binary detection is a simple NUL-byte check; files that can't be
    decoded (or contain NUL bytes) are skipped rather than fatal.
    """
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError as e:
        logger.debug("Skipping unreadable file %s: %s", full_path, e)
        return ""
    if "\x00" in text:
        return ""
    return text


def _load_text_splitter():
    """Return a RecursiveCharacterTextSplitter (handles both import paths)."""
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except ImportError:
        from langchain.text_splitter import RecursiveCharacterTextSplitter
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )


def _load_embeddings():
    """
    Return a HuggingFaceEmbeddings instance.

    `HuggingFaceEmbeddings` lives in langchain-huggingface these days but
    was historically re-exported from langchain-community; try the new
    home first and fall back so either install works.
    """
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        from langchain_community.embeddings import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def index_codebase(repo_path: str, repo_id: str | None = None) -> dict:
    """
    Index a repository's source files into Supabase (pgvector).

    Re-indexing the same repository clears previous documents for that
    repo_id first, so the database never accumulates stale chunks.

    Args:
        repo_path (str): Local path to the repository directory
        repo_id (str | None): Unique repository identifier (e.g. GitHub URL or local path).
                              If None, defaults to repo_path.

    Returns:
        dict: {"indexed_files": int, "total_chunks": int, "status": "completed"}
            on success, or {"status": "error", "message": str} on failure.
    """
    if not os.path.isdir(repo_path):
        return {
            "status": "error",
            "message": "Repository path does not exist or is not a directory.",
        }

    db_repo_path = repo_id if repo_id is not None else repo_path

    # --- 1. Traverse & read supported files into documents -------------
    documents = []
    indexed_files = 0

    try:
        from langchain_core.documents import Document
    except ImportError:
        return {
            "status": "error",
            "message": (
                "RAG dependencies are not installed. Run: "
                "pip install langchain langchain-community "
                "langchain-huggingface langchain-text-splitters "
                "sentence-transformers"
            ),
        }

    for full_path in _collect_source_files(repo_path):
        text = _read_file_text(full_path)
        if not text.strip():
            continue
        documents.append(
            Document(
                page_content=text,
                metadata={
                    "file_path": os.path.relpath(full_path, repo_path),
                    "repo_path": db_repo_path,
                },
            )
        )
        indexed_files += 1

    if not documents:
        return {
            "indexed_files": 0,
            "total_chunks": 0,
            "status": "completed",
            "message": "No supported source files found to index.",
        }

    # --- 2. Chunk, embed & upsert into Supabase -------------------------
    from .db_client import _get_http_client, SUPABASE_ENABLED

    if not SUPABASE_ENABLED:
        return {
            "status": "error",
            "message": "Supabase is not configured or enabled. Please set SUPABASE_URL and SUPABASE_KEY in .env.",
        }

    try:
        splitter = _load_text_splitter()
        chunks = splitter.split_documents(documents)
        embeddings = _load_embeddings()
    except Exception as e:
        logger.warning("Failed to initialize text splitter or embeddings: %s", e)
        return {
            "status": "error",
            "message": f"Failed to initialize embeddings: {e}",
        }

    # Clear stale documents for this repo in Supabase.
    try:
        client = _get_http_client()
        delete_resp = client.delete("code_embeddings", params={"repo_path": f"eq.{db_repo_path}"})
        delete_resp.raise_for_status()
    except Exception as e:
        logger.warning(
            "Could not clear previous index for %s in Supabase: %s", db_repo_path, e
        )

    # Embed chunks.
    texts = [chunk.page_content for chunk in chunks]
    try:
        embedded_vectors = embeddings.embed_documents(texts)
    except Exception as e:
        logger.warning("Embedding generation failed: %s", e)
        return {
            "status": "error",
            "message": f"Failed to embed document chunks: {e}",
        }

    # Prepare payload.
    payload = []
    for chunk, embedding in zip(chunks, embedded_vectors):
        payload.append({
            "repo_path": db_repo_path,
            "file_path": chunk.metadata["file_path"],
            "content": chunk.page_content,
            "embedding": embedding,
        })

    # Upsert to Supabase code_embeddings table in batches of 100 to avoid payload size limit issues.
    BATCH_SIZE = 100
    try:
        for i in range(0, len(payload), BATCH_SIZE):
            batch = payload[i : i + BATCH_SIZE]
            upload_resp = client.post("code_embeddings", json=batch)
            upload_resp.raise_for_status()
    except Exception as e:
        logger.warning("Upload of embeddings to Supabase failed: %s", e)
        return {
            "status": "error",
            "message": f"Failed to upload embeddings to Supabase: {e}",
        }

    return {
        "indexed_files": indexed_files,
        "total_chunks": len(chunks),
        "status": "completed",
    }
