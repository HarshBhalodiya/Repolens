"""
RepoLens - AI Engine Module

Generates AI standup summaries from recent Git commit history using a
local Ollama LLM wrapped through LangChain.

Optional runtime dependencies (only needed for /api/summarize):

    pip install langchain langchain-ollama

They are imported lazily inside the function so the rest of RepoLens
keeps working even when the AI features are not installed, and so a
missing/broken AI stack can never prevent the app from booting.
"""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# Number of most-recent commit subjects fed to the model.
COMMIT_LIMIT = 30

# Model + endpoint for the local Ollama service. Overridable via env vars;
# defaults match a stock local Ollama install.
OLLAMA_BASE_URL = os.getenv("REPOLENS_OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("REPOLENS_OLLAMA_MODEL", "mistral")

PROMPT_TEMPLATE = """You are an expert technical lead. Analyze the following 30 recent git commit messages and summarize developer progress into EXACTLY 3 clear, actionable bullet points highlighting major features, refactors, or fixes.
Commits:
{commits}

Provide ONLY the 3 bullet points."""

OLLAMA_UNAVAILABLE_MESSAGE = (
    "Ollama service unavailable. Please make sure Ollama is running locally."
)

# Prompt used by the RAG codebase chat (/api/chat). The model is told to
# answer strictly from the retrieved context and to cite file paths.
RAG_PROMPT_TEMPLATE = """You are an expert codebase assistant. Answer the user question based strictly on the following code context. Cite file paths when possible.

Context:
{context}

Question:
{query}"""

# Maximum number of context chunks retrieved per question.
RAG_TOP_K = 4


def _get_recent_commits(repo_path: str) -> list[str]:
    """
    Run `git log` and return the last `COMMIT_LIMIT` commit subjects.

    Each subject is prefixed with "- " and suffixed with its short hash,
    matching the format that is interpolated into the prompt.

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        list[str]: Formatted commit lines, or [] when git fails/no commits.
    """
    try:
        result = subprocess.run(
            [
                "git", "log", "-n", str(COMMIT_LIMIT),
                '--pretty=format:- %s (%h)',
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning("git log timed out for %s", repo_path)
        return []
    except FileNotFoundError:
        logger.warning("Git is not installed or not found in system PATH.")
        return []
    except Exception as e:
        logger.warning("Error running git log for %s: %s", repo_path, e)
        return []

    return [line for line in result.stdout.splitlines() if line.strip()]


def generate_standup_summary(repo_path: str) -> dict:
    """
    Generate a 3-bullet standup summary from the last 30 commits via Ollama.

    Args:
        repo_path (str): Path to the local Git repository

    Returns:
        dict: On success {"summary": str, "status": "success"}.
            On Ollama failure {"summary": str, "status": "error"}.
            When there is nothing to summarize, a plain
            {"summary": "No recent commits available to summarize."}
            payload (no status key, so the UI treats it as informational).
    """
    if not os.path.isdir(repo_path):
        return {
            "summary": "Repository path does not exist or is not a directory.",
            "status": "error",
        }

    commits = _get_recent_commits(repo_path)

    if not commits:
        return {"summary": "No recent commits available to summarize."}

    commits_text = "\n".join(commits)

    # Lazy import: keep the app bootable without the optional AI packages.
    try:
        from langchain_core.prompts import PromptTemplate
        from langchain_ollama import OllamaLLM
    except ImportError:
        logger.warning(
            "LangChain AI packages are not installed; /api/summarize unavailable."
        )
        return {
            "summary": (
                "AI dependencies are not installed. Run: "
                "pip install langchain langchain-ollama"
            ),
            "status": "error",
        }

    # Wrap the Ollama call so a down/unreachable service degrades to a
    # friendly error instead of a 500.
    try:
        llm = OllamaLLM(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL)
        prompt = PromptTemplate(
            template=PROMPT_TEMPLATE,
            input_variables=["commits"],
        )
        chain = prompt | llm
        response_text = chain.invoke({"commits": commits_text})
    except Exception as e:
        logger.warning("Ollama call failed for %s: %s", repo_path, e)
        return {"summary": OLLAMA_UNAVAILABLE_MESSAGE, "status": "error"}

    return {"summary": str(response_text).strip(), "status": "success"}


def answer_codebase_question(repo_path: str, query: str) -> dict:
    """
    Answer a question about an indexed codebase using RAG + local Ollama.

    Retrieves the top `RAG_TOP_K` chunks from the persistent ChromaDB
    collection (`repolens_codebase` in `./chroma_db`, populated by
    rag_indexer.index_codebase) that best match `query`, then asks the
    local Ollama model to answer strictly from that context.

    Args:
        repo_path (str): Path to the repository the question is about
        query (str): The user's question

    Returns:
        dict: {"answer": str, "sources": [str], "status": "success"}
            on success; on failure {"answer": str, "sources": [],
            "status": "error"} with a human-readable answer explaining
            what went wrong (e.g. the codebase has not been indexed).
    """
    if not query or not query.strip():
        return {
            "answer": "Query cannot be empty.",
            "sources": [],
            "status": "error",
        }

    # Lazy imports: the RAG stack (and rag_indexer's shared helpers) are
    # optional, so a missing install degrades to a clear message instead of
    # breaking the rest of RepoLens.
    try:
        import chromadb
        from langchain_core.prompts import PromptTemplate
        from langchain_ollama import OllamaLLM

        from . import rag_indexer
    except ImportError:
        return {
            "answer": (
                "RAG dependencies are not installed. Run: pip install "
                "langchain langchain-ollama langchain-huggingface "
                "langchain-text-splitters chromadb sentence-transformers"
            ),
            "sources": [],
            "status": "error",
        }

    # Open the vector store and check the collection exists BEFORE loading
    # the (slow) embedding model, so the common "not indexed yet" case
    # fails fast without a model download.
    try:
        client = chromadb.PersistentClient(path=rag_indexer.CHROMA_DIR)
        try:
            collection = client.get_collection(name=rag_indexer.COLLECTION_NAME)
        except Exception:
            return {
                "answer": "Please index the codebase first.",
                "sources": [],
                "status": "error",
            }
    except Exception as e:
        logger.warning("Failed to open vector store: %s", e)
        return {
            "answer": f"Failed to open the vector store: {e}",
            "sources": [],
            "status": "error",
        }

    # Retrieve the top-k chunks for THIS repo only (the collection may
    # hold several repositories' chunks).
    try:
        embeddings = rag_indexer._load_embeddings()
        results = collection.query(
            query_embeddings=embeddings.embed_query(query.strip()),
            n_results=RAG_TOP_K,
            where={"repo_path": repo_path},
        )
    except ImportError:
        return {
            "answer": (
                "RAG dependencies are not installed. Run: pip install "
                "langchain langchain-ollama langchain-huggingface "
                "langchain-text-splitters chromadb sentence-transformers"
            ),
            "sources": [],
            "status": "error",
        }
    except Exception as e:
        logger.warning("Retrieval failed for %s: %s", repo_path, e)
        return {
            "answer": "Failed to retrieve context from the index.",
            "sources": [],
            "status": "error",
        }

    documents = (results.get("documents") or [[]])[0]
    metadatas = (results.get("metadatas") or [[]])[0]

    if not documents:
        return {
            "answer": "Please index the codebase first.",
            "sources": [],
            "status": "error",
        }

    # Build the context block, keeping track of which files were cited so
    # the response can surface them as source chips in the UI.
    sources: list[str] = []
    blocks = []
    for doc, meta in zip(documents, metadatas):
        file_path = (meta or {}).get("file_path", "unknown")
        if file_path not in sources:
            sources.append(file_path)
        blocks.append(f"[{file_path}]\n{doc}")
    context = "\n\n---\n\n".join(blocks)

    try:
        llm = OllamaLLM(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL)
        prompt = PromptTemplate(
            template=RAG_PROMPT_TEMPLATE,
            input_variables=["context", "query"],
        )
        chain = prompt | llm
        answer = chain.invoke({"context": context, "query": query.strip()})
    except Exception as e:
        logger.warning("Ollama call failed: %s", e)
        return {
            "answer": OLLAMA_UNAVAILABLE_MESSAGE,
            "sources": sources,
            "status": "error",
        }

    return {
        "answer": str(answer).strip(),
        "sources": sources,
        "status": "success",
    }
