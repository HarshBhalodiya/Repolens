"""
AI GitHub Repo Analyzer - Flask Backend
Run: python run.py
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import json
from dotenv import load_dotenv

load_dotenv()

from github_fetcher import fetch_repo
from parser import parse_imports
from dependency_graph import build_graph
from complexity import analyze_complexity
from embeddings import build_embeddings, search_chunks
from chat_engine import chat_with_repo, explain_file_content, generate_readme

# Define the path to the frontend folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_FOLDER = os.path.join(BASE_DIR, "frontend")

app = Flask(__name__, static_folder=FRONTEND_FOLDER, static_url_path="")
CORS(app)

# ─────────────────────────────────────────
# Serve Frontend
# ─────────────────────────────────────────
@app.route("/")
def serve_index():
    return app.send_static_file("index.html")

@app.route("/<path:path>")
def serve_static(path):
    if os.path.exists(os.path.join(FRONTEND_FOLDER, path)):
        return app.send_static_file(path)
    return app.send_static_file("index.html")


REPO_STORE_PATH = os.path.join(os.path.dirname(__file__), "repo_store.json")


def _load_repo_store() -> dict:
    if not os.path.exists(REPO_STORE_PATH):
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


# Persisted in-memory store for development stability.
repo_store = _load_repo_store()


# ─────────────────────────────────────────
# POST /api/analyze
# Body: { "repo_url": "https://github.com/..." }
# ─────────────────────────────────────────
@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    repo_url = data.get("repo_url", "").strip()

    if not repo_url or "github.com" not in repo_url:
        return jsonify({"error": "Invalid GitHub URL"}), 400

    try:
        # 1. Fetch repo files from GitHub API
        print(f"[analyze] Fetching: {repo_url}")
        repo_data = fetch_repo(repo_url)

        # 2. Parse import relationships
        print("[analyze] Parsing imports...")
        deps = parse_imports(repo_data["files"])

        # 3. Build dependency graph
        print("[analyze] Building graph...")
        graph = build_graph(deps, repo_data["files"])

        # 4. Analyze complexity
        print("[analyze] Calculating complexity...")
        complexity = analyze_complexity(repo_data["files"])

        # 5. Build vector embeddings for chat
        print("[analyze] Building embeddings for RAG...")
        collection_id = build_embeddings(repo_url, repo_data["files"])

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
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# GET /api/graph?repo=owner/name
# ─────────────────────────────────────────
@app.route("/api/graph", methods=["GET"])
def get_graph():
    repo_key = request.args.get("repo", "")
    data = repo_store.get(repo_key)
    if not data:
        return jsonify({"error": "Repo not found. Run /api/analyze first."}), 404
    return jsonify(data["graph"])


# ─────────────────────────────────────────
# GET /api/complexity?repo=owner/name
# ─────────────────────────────────────────
@app.route("/api/complexity", methods=["GET"])
def get_complexity():
    repo_key = request.args.get("repo", "")
    data = repo_store.get(repo_key)
    if not data:
        return jsonify({"error": "Repo not found. Run /api/analyze first."}), 404
    return jsonify(data["complexity"])


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
# POST /api/chat
# Body: { "repo_key": "...", "message": "...", "history": [...] }
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
        # RAG: find relevant code chunks
        context_chunks = search_chunks(repo["collection_id"], message, n_results=5)

        # Generate response with Claude
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
# Body: { "repo_key": "...", "filename": "..." }
# ─────────────────────────────────────────
@app.route("/api/explain-file", methods=["POST"])
def explain_file():
    data = request.json
    repo_key = data.get("repo_key", "")
    filename = data.get("filename", "")

    repo = repo_store.get(repo_key)
    if not repo:
        return jsonify({"error": "Repo not found"}), 404

    # Find the file
    file_data = next((f for f in repo["files"] if f["name"] == filename or f["path"] == filename), None)
    if not file_data:
        return jsonify({"error": f"File '{filename}' not found"}), 404

    try:
        explanation = explain_file_content(file_data, repo["meta"])
        return jsonify({"explanation": explanation, "file": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────
# POST /api/readme
# Body: { "repo_key": "..." }
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
# Health check
# ─────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "github_token": bool(os.getenv("GITHUB_TOKEN")),
        "anthropic_key": bool(os.getenv("ANTHROPIC_API_KEY")),
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
