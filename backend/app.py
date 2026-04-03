"""
RepoLens — Flask Backend (MVP)
Run: python run.py
"""

from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
import os
import json
import time
import queue
import threading
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level up from backend/)
_project_root = Path(__file__).resolve().parent.parent
load_dotenv(_project_root / ".env")

from github_fetcher import fetch_repo
from parser import parse_imports
from dependency_graph import build_graph
from complexity import analyze_complexity
from embeddings import build_embeddings, search_chunks
from chat_engine import (
    chat_with_repo, explain_file_content, generate_readme,
    active_engine, check_ollama_health, check_claude_health,
)

# ─────────────────────────────────────────
# App setup
# ─────────────────────────────────────────
FRONTEND_FOLDER = str(_project_root / "frontend")

app = Flask(__name__, static_folder=FRONTEND_FOLDER, static_url_path="")
CORS(app)

REPO_STORE_PATH = Path(__file__).resolve().parent / "repo_store.json"

# SSE progress queues — keyed by a unique analysis-id
_progress_queues: dict[str, queue.Queue] = {}


def _load_repo_store() -> dict:
    if not REPO_STORE_PATH.exists():
        return {}
    try:
        with open(REPO_STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[repo_store] Failed to load persisted store: {e}")
        return {}


def _save_repo_store() -> None:
    try:
        with open(REPO_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(repo_store, f)
    except Exception as e:
        print(f"[repo_store] Failed to save store: {e}")


repo_store = _load_repo_store()


# ─────────────────────────────────────────
# Serve Frontend (SPA)
# ─────────────────────────────────────────
@app.route("/")
def serve_index():
    return app.send_static_file("index.html")


@app.route("/<path:path>")
def serve_static(path):
    full = os.path.join(FRONTEND_FOLDER, path)
    if os.path.exists(full):
        return app.send_static_file(path)
    return app.send_static_file("index.html")


# ─────────────────────────────────────────
# SSE Progress Stream
# ─────────────────────────────────────────
def _send_progress(analysis_id: str, step: str, pct: int, detail: str = ""):
    q = _progress_queues.get(analysis_id)
    if q:
        q.put({"step": step, "pct": pct, "detail": detail})


@app.route("/api/progress/<analysis_id>")
def progress_stream(analysis_id):
    """SSE endpoint — streams real-time analysis progress."""
    q = queue.Queue()
    _progress_queues[analysis_id] = q

    def generate():
        try:
            while True:
                try:
                    msg = q.get(timeout=120)
                except queue.Empty:
                    yield "event: timeout\ndata: {}\n\n"
                    break
                yield f"data: {json.dumps(msg)}\n\n"
                if msg.get("pct", 0) >= 100:
                    break
        finally:
            _progress_queues.pop(analysis_id, None)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ─────────────────────────────────────────
# POST /api/analyze
# ─────────────────────────────────────────
@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    repo_url = data.get("repo_url", "").strip()
    analysis_id = data.get("analysis_id", "")

    if not repo_url or "github.com" not in repo_url:
        return jsonify({"error": "Invalid GitHub URL"}), 400

    try:
        # 1. Fetch repo files from GitHub API
        _send_progress(analysis_id, "Fetching repository structure…", 8, "GITHUB API")
        print(f"[analyze] Fetching: {repo_url}")
        repo_data = fetch_repo(repo_url)

        # 2. Parse import relationships
        _send_progress(analysis_id, "Parsing import declarations…", 25, "AST PARSER")
        print("[analyze] Parsing imports...")
        deps = parse_imports(repo_data["files"])

        # 3. Build dependency graph
        _send_progress(analysis_id, "Building dependency graph…", 40, "NETWORKX")
        print("[analyze] Building graph...")
        graph = build_graph(deps, repo_data["files"])

        # 4. Analyze complexity
        _send_progress(analysis_id, "Calculating cyclomatic complexity…", 55, "RADON")
        print("[analyze] Calculating complexity...")
        complexity = analyze_complexity(repo_data["files"])

        # 5. Build vector embeddings for chat
        _send_progress(analysis_id, "Loading embedding model…", 70, "SENTENCE-TRANSFORMERS")
        print("[analyze] Building embeddings for RAG...")
        collection_id = build_embeddings(repo_url, repo_data["files"])

        _send_progress(analysis_id, "Storing in vector database…", 90, "CHROMADB")

        # Store everything
        repo_key = repo_data["full_name"]
        repo_store[repo_key] = {
            "meta": repo_data["meta"],
            "files": repo_data["files"],
            "file_tree": repo_data["file_tree"],
            "deps": deps,
            "graph": graph,
            "complexity": complexity,
            "collection_id": collection_id,
            "full_name": repo_data["full_name"],
        }

        analyzed_files = [f for f in repo_data["files"] if "complexity" in f]
        avg_complexity = round(
            sum(f["complexity"] for f in analyzed_files) / max(len(analyzed_files), 1), 1
        )

        _save_repo_store()
        _send_progress(analysis_id, "Analysis complete!", 100, "DONE")

        return jsonify({
            "repo_key": repo_key,
            "meta": repo_data["meta"],
            "file_tree": repo_data["file_tree"],
            "complexity": complexity,
            "graph": graph,
            "stats": {
                "total_files": len(repo_data["files"]),
                "total_lines": sum(f.get("lines", 0) for f in repo_data["files"]),
                "total_functions": sum(f.get("functions", 0) for f in repo_data["files"]),
                "avg_complexity": avg_complexity,
            }
        })

    except Exception as e:
        print(f"[analyze] Error: {e}")
        import traceback; traceback.print_exc()
        _send_progress(analysis_id, f"Error: {e}", -1, "FAILED")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# GET /api/repo?repo=owner/name
# ─────────────────────────────────────────
@app.route("/api/repo", methods=["GET"])
def get_repo_payload():
    repo_key = request.args.get("repo", "")
    data = repo_store.get(repo_key)
    if not data:
        return jsonify({"error": "Repo not found. Run /api/analyze first."}), 404

    files = data.get("files", [])
    analyzed_files = [f for f in files if "complexity" in f]
    avg_complexity = round(
        sum(f["complexity"] for f in analyzed_files) / max(len(analyzed_files), 1), 1
    )
    return jsonify({
        "repo_key": repo_key,
        "meta": data["meta"],
        "file_tree": data.get("file_tree", []),
        "complexity": data["complexity"],
        "graph": data["graph"],
        "stats": {
            "total_files": len(files),
            "total_lines": sum(f.get("lines", 0) for f in files),
            "total_functions": sum(f.get("functions", 0) for f in files),
            "avg_complexity": avg_complexity,
        }
    })


# ─────────────────────────────────────────
# GET /api/file-content?repo=owner/name&path=src/app.py
# ─────────────────────────────────────────
@app.route("/api/file-content", methods=["GET"])
def get_file_content():
    repo_key = request.args.get("repo", "")
    file_path = request.args.get("path", "")
    data = repo_store.get(repo_key)
    if not data:
        return jsonify({"error": "Repo not found"}), 404

    file_data = next(
        (f for f in data["files"] if f.get("path") == file_path or f.get("name") == file_path),
        None,
    )
    if not file_data:
        return jsonify({"error": f"File '{file_path}' not found"}), 404

    return jsonify({
        "path": file_data.get("path", ""),
        "name": file_data.get("name", ""),
        "lang": file_data.get("lang", ""),
        "content": file_data.get("content", ""),
        "lines": file_data.get("lines", 0),
        "complexity": file_data.get("complexity", 1),
        "functions": file_data.get("functions", 0),
    })


# ─────────────────────────────────────────
# POST /api/chat
# ─────────────────────────────────────────
@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    repo_key = data.get("repo_key", "")
    message = data.get("message", "").strip()
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "Empty message"}), 400

    repo = repo_store.get(repo_key)
    if not repo:
        return jsonify({"error": "Repo not found. Run /api/analyze first."}), 404

    try:
        context_chunks = search_chunks(repo["collection_id"], message, n_results=5)
        reply = chat_with_repo(
            message=message,
            history=history,
            repo_meta=repo["meta"],
            context_chunks=context_chunks,
            complexity=repo["complexity"],
        )
        return jsonify({"reply": reply})
    except Exception as e:
        print(f"[chat] Error: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# POST /api/explain-file
# ─────────────────────────────────────────
@app.route("/api/explain-file", methods=["POST"])
def explain_file():
    data = request.json
    repo_key = data.get("repo_key", "")
    filename = data.get("filename", "")

    repo = repo_store.get(repo_key)
    if not repo:
        return jsonify({"error": "Repo not found"}), 404

    file_data = next(
        (f for f in repo["files"] if f["name"] == filename or f["path"] == filename),
        None,
    )
    if not file_data:
        return jsonify({"error": f"File '{filename}' not found"}), 404

    try:
        explanation = explain_file_content(file_data, repo["meta"])
        return jsonify({"explanation": explanation, "file": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# POST /api/readme
# ─────────────────────────────────────────
@app.route("/api/readme", methods=["POST"])
def get_readme():
    data = request.json
    repo_key = data.get("repo_key", "")

    repo = repo_store.get(repo_key)
    if not repo:
        return jsonify({"error": "Repo not found"}), 404

    try:
        readme = generate_readme(repo["meta"], repo["files"], repo["complexity"])
        return jsonify({"readme": readme})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# GET /api/health — comprehensive health check
# ─────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    ollama = check_ollama_health()
    github_ok = bool(os.getenv("GITHUB_TOKEN"))

    # Claude check is expensive (API call) — only run if requested
    deep = request.args.get("deep", "false").lower() == "true"
    claude_info = check_claude_health() if deep else {
        "configured": bool(os.getenv("ANTHROPIC_API_KEY")),
    }

    return jsonify({
        "status": "ok",
        "engine": active_engine(),
        "ollama": ollama,
        "claude": claude_info,
        "github_token": github_ok,
        "repos_loaded": len(repo_store),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
