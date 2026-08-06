"""
RepoLens - RAG Codebase Indexer

Walks a repository, chunks supported source files, embeds them locally
with sentence-transformers (all-MiniLM-L6-v2), and stores the vectors
in a persistent ChromaDB collection for retrieval-augmented search.

Optional runtime dependencies (only needed for /api/index_codebase):

    pip install langchain langchain-community langchain-huggingface \
        langchain-text-splitters chromadb sentence-transformers

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

# Persistent ChromaDB storage location + collection name.
CHROMA_DIR = os.getenv("REPOLENS_CHROMA_DIR", "./chroma_db")
COLLECTION_NAME = "repolens_codebase"

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


def index_codebase(repo_path: str) -> dict:
    """
    Index a repository's source files into the persistent ChromaDB store.

    Re-indexing the same repo_path clears that repo's previous documents
    first, so the collection never accumulates stale chunks.

    Args:
        repo_path (str): Path to the repository to index

    Returns:
        dict: {"indexed_files": int, "total_chunks": int, "status": "completed"}
            on success, or {"status": "error", "message": str} on failure.
    """
    if not os.path.isdir(repo_path):
        return {
            "status": "error",
            "message": "Repository path does not exist or is not a directory.",
        }

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
                "chromadb sentence-transformers"
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
                    "repo_path": repo_path,
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

    # --- 2. Chunk, embed & upsert into ChromaDB -------------------------
    try:
        import chromadb

        splitter = _load_text_splitter()
        chunks = splitter.split_documents(documents)
        embeddings = _load_embeddings()
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
    except ImportError:
        return {
            "status": "error",
            "message": (
                "RAG dependencies are not installed. Run: "
                "pip install langchain langchain-community "
                "langchain-huggingface langchain-text-splitters "
                "chromadb sentence-transformers"
            ),
        }
    except Exception as e:
        logger.warning("Failed to initialize vector store: %s", e)
        return {
            "status": "error",
            "message": f"Failed to initialize the vector store: {e}",
        }

    # Clear stale documents for this repo before re-indexing.
    try:
        collection.delete(where={"repo_path": repo_path})
    except Exception as e:
        logger.warning(
            "Could not clear previous index for %s: %s", repo_path, e
        )

    # ChromaDB ids must be unique across the whole collection.
    ids = [
        hashlib.sha256(f"{repo_path}::{i}".encode("utf-8")).hexdigest()
        for i in range(len(chunks))
    ]
    metadatas = [chunk.metadata for chunk in chunks]
    texts = [chunk.page_content for chunk in chunks]

    try:
        collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings.embed_documents(texts),
        )
    except Exception as e:
        logger.warning("Embedding/indexing failed for %s: %s", repo_path, e)
        return {
            "status": "error",
            "message": f"Failed to embed/index the codebase: {e}",
        }

    return {
        "indexed_files": indexed_files,
        "total_chunks": len(chunks),
        "status": "completed",
    }
