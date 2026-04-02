"""
embeddings.py
Splits code files into chunks, embeds them with sentence-transformers,
and stores in ChromaDB for semantic search (RAG).
"""

import os
import re
import hashlib
from pathlib import Path

# ChromaDB
import chromadb
from chromadb.config import Settings

# Sentence Transformers for local embeddings (free, no API key needed)
from sentence_transformers import SentenceTransformer

# ─────────────────────────────────────────
# Config
# ─────────────────────────────────────────

CHUNK_SIZE = 400        # characters per chunk
CHUNK_OVERLAP = 80      # overlap between chunks
EMBED_MODEL = "all-MiniLM-L6-v2"   # fast + good quality, ~80MB

# Singleton model and client
_model = None
_chroma_client = None
_collections = {}


def get_model():
    global _model
    if _model is None:
        print("[embeddings] Loading sentence-transformer model...")
        _model = SentenceTransformer(EMBED_MODEL)
        print("[embeddings] Model loaded.")
    return _model


def get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        # Store in ./chroma_db relative to backend/
        persist_dir = os.path.join(os.path.dirname(__file__), "..", "chroma_db")
        os.makedirs(persist_dir, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=persist_dir)
    return _chroma_client


# ─────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────

def chunk_code(content: str, file_path: str, lang: str) -> list[dict]:
    """
    Split code into overlapping chunks with metadata.
    Strategy: try to split at function/class boundaries first, then by size.
    """
    chunks = []
    lines = content.splitlines()
    total_lines = len(lines)

    # Split at natural boundaries (function/class definitions)
    boundary_pattern = None
    if lang == "python":
        boundary_pattern = re.compile(r"^(?:def |class |async def )", re.MULTILINE)
    elif lang in ("javascript", "typescript"):
        boundary_pattern = re.compile(r"^(?:function |class |const \w+ = |export (?:default )?(?:function|class))", re.MULTILINE)
    elif lang in ("java", "csharp"):
        boundary_pattern = re.compile(r"^\s*(?:public|private|protected|static)\s+\w+", re.MULTILINE)

    segments = []
    if boundary_pattern:
        matches = list(boundary_pattern.finditer(content))
        if len(matches) > 1:
            for i, match in enumerate(matches):
                start = match.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
                segment = content[start:end].strip()
                if segment:
                    segments.append(segment)
        
    # Fallback: fixed-size chunks with overlap
    if not segments:
        i = 0
        while i < len(content):
            chunk = content[i:i + CHUNK_SIZE]
            if chunk.strip():
                segments.append(chunk)
            i += CHUNK_SIZE - CHUNK_OVERLAP

    # Filter tiny segments first so metadata stays consistent.
    valid_segments = [segment for segment in segments if len(segment.strip()) >= 30]

    # Build chunk dicts
    for idx, segment in enumerate(valid_segments):
        chunks.append({
            "id": f"{file_path}::chunk_{idx}",
            "text": f"# File: {file_path}\n\n{segment[:CHUNK_SIZE]}",
            "metadata": {
                "file": file_path,
                "file_name": Path(file_path).name,
                "lang": lang,
                "chunk_index": idx,
                "total_chunks": len(valid_segments),
            }
        })

    return chunks


# ─────────────────────────────────────────
# Build embeddings
# ─────────────────────────────────────────

def build_embeddings(repo_url: str, files: list[dict]) -> str:
    """
    Chunk all files, embed them, and store in ChromaDB.
    Returns collection_id (based on repo URL hash).
    """
    collection_id = "repo_" + hashlib.md5(repo_url.encode()).hexdigest()[:12]
    model = get_model()
    client = get_chroma_client()

    # Delete existing collection if re-analyzing
    try:
        client.delete_collection(collection_id)
    except:
        pass

    collection = client.create_collection(
        name=collection_id,
        metadata={"repo_url": repo_url}
    )

    all_chunks = []
    for f in files:
        content = f.get("content", "")
        lang = f.get("lang", "")
        path = f.get("path", f["name"])

        if not content or len(content.strip()) < 50:
            continue

        chunks = chunk_code(content, path, lang)
        all_chunks.extend(chunks)

    if not all_chunks:
        print("[embeddings] No chunks to embed")
        _collections[collection_id] = collection
        return collection_id

    print(f"[embeddings] Embedding {len(all_chunks)} chunks...")

    # Batch embedding
    BATCH_SIZE = 64
    all_ids = [c["id"] for c in all_chunks]
    all_texts = [c["text"] for c in all_chunks]
    all_metas = [c["metadata"] for c in all_chunks]

    for i in range(0, len(all_chunks), BATCH_SIZE):
        batch_texts = all_texts[i:i + BATCH_SIZE]
        batch_ids = all_ids[i:i + BATCH_SIZE]
        batch_metas = all_metas[i:i + BATCH_SIZE]

        embeddings = model.encode(batch_texts, show_progress_bar=False).tolist()
        collection.add(
            ids=batch_ids,
            embeddings=embeddings,
            documents=batch_texts,
            metadatas=batch_metas,
        )

    print(f"[embeddings] Stored {len(all_chunks)} chunks in ChromaDB collection: {collection_id}")
    _collections[collection_id] = collection
    return collection_id


# ─────────────────────────────────────────
# Search (RAG retrieval)
# ─────────────────────────────────────────

def search_chunks(collection_id: str, query: str, n_results: int = 5) -> list[dict]:
    """
    Semantic search over the embedded code chunks.
    Returns top-k most relevant code chunks.
    """
    model = get_model()
    client = get_chroma_client()

    # Get or reload collection
    if collection_id not in _collections:
        try:
            collection = client.get_collection(collection_id)
            _collections[collection_id] = collection
        except Exception as e:
            print(f"[search] Collection not found: {e}")
            return []

    collection = _collections[collection_id]

    query_embedding = model.encode([query], show_progress_bar=False).tolist()

    result_count = collection.count()
    if result_count == 0:
        return []

    try:
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=max(1, min(n_results, result_count)),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        print(f"[search] Query error: {e}")
        return []

    chunks = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for doc, meta, dist in zip(docs, metas, distances):
        chunks.append({
            "text": doc,
            "file": meta.get("file", ""),
            "file_name": meta.get("file_name", ""),
            "lang": meta.get("lang", ""),
            "relevance_score": round(1 - dist, 3),
        })

    return chunks
