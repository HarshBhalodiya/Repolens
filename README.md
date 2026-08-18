# RepoLens 🔍

RepoLens is an AI-powered local Git repository analyzer and dashboard. It provides detailed commit analytics (code churn, hotspots, daily commit distribution), generates AI standup summaries via local LLMs, indexes codebases for RAG (Retrieval-Augmented Generation) Q&A, and builds interactive file-level dependency knowledge graphs.

---

## Key Features

1. **Commit Extraction & Git Analytics**
   * Computes daily code churn (insertions vs. deletions) and detects most frequently changed files (hotspots) via Git subprocess logs and Pandas.
   * Visualizes author commit distributions, daily commit activity, and programming language ratios.
   * Utilizes field separator tokens (`\x1f`) to avoid CSV syntax corruption in free-form commit messages.

2. **Local LLM Integration**
   * Powered by LangChain and local **Ollama** models (e.g. `deepseek-coder:1.3b`, `mistral`).
   * Automatically generates a concise 3-bullet daily developer progress summary based on recent commit subjects.
   * CPU/IO-bound model executions are offloaded to FastAPI's background thread pool to keep the event loop non-blocking.

3. **RAG Codebase Q&A**
   * Codebase indexing via local HuggingFace embeddings (`all-MiniLM-L6-v2`) and **Supabase (pgvector)** vector storage.
   * Similarity search over indexed repository files to answer codebase-wide technical questions with citations.
   * Implements embeddings warming at server startup to avoid first-request loading delays.

4. **Dependency Knowledge Graph**
   * Builds file-level imports and module graphs using **Tree-sitter** AST parsers.
   * Supports Python (`.py`), JavaScript (`.js`, `.jsx`), and TypeScript (`.ts`, `.tsx`).
   * Resolves relative and absolute imports to internal project file paths, generating structured Node/Edge JSON payloads.

5. **Production Hardening & Security**
   * Optional **API-key bearer token protection** to guard endpoints against unauthorized path traversal.
   * Configurable CORS origin lock to prevent arbitrary browser connections.
   * Safe temporary directory cloning and cleaning for remote GitHub repository analysis.
   * Cache verification layers to prevent errored/empty runs from poisoning database cache tables.

---

## Directory Structure

```text
RepoLens/
├── app/
│   ├── __init__.py
│   ├── ai_engine.py           # Standup summary generation & RAG Q&A engine
│   ├── db_client.py           # Supabase connection client & cache manager
│   ├── dependency_parser.py   # Tree-sitter AST imports parser & resolver
│   ├── git_parser.py          # Subprocess git log parses, Pandas churn & hotspot math
│   ├── main.py                # FastAPI application setup, middleware, & API routing
│   └── utils.py               # Repository cloning, hashes, and validation helpers
├── static/
│   ├── app.js                 # Dashboard controllers, chart.js rendering, & API connections
│   ├── index.html             # Sleek dark-mode dashboard UI structure
│   └── style.css              # Custom layout CSS, cards, grids, and glassmorphism styling
├── .env.example               # Template environment configuration file
├── requirements.txt           # Version-locked package dependencies
└── supabase_schema.sql        # Database schema definitions for pgvector & cache tables
```

---

## Setup & Installation

### 1. Prerequisites
* **Python**: 3.9+ installed.
* **Git**: Installed and available in your system path.
* **Ollama**: Installed and running locally. Pull your preferred model (e.g., `deepseek-coder:1.3b` or `mistral`):
  ```bash
  ollama pull deepseek-coder:1.3b
  ```
* **Supabase** (Optional but recommended for RAG & Cloud Caching): Create a Supabase project and enable the `vector` extension.

### 2. Install Dependencies
Set up a virtual environment and install the required libraries:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3. Database Schema Setup
If utilizing Supabase, run the SQL script located in [supabase_schema.sql](file:///e:/Projects/RepoLens/supabase_schema.sql) within the Supabase SQL Editor. This sets up two tables:
1. `repo_analysis`: Caches computed commit statistics to speed up dashboard loads.
2. `code_embeddings`: Stores vector embeddings for code chunks.
3. `match_code_embeddings`: RPC function utilized during RAG codebase Q&A.

### 4. Configuration (`.env`)
Create a `.env` file in the project root:
```env
# Supabase Configuration
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_KEY=your-service-role-key

# Ollama Customizations
REPOLENS_OLLAMA_MODEL=deepseek-coder:1.3b
REPOLENS_OLLAMA_BASE_URL=http://localhost:11434

# Security Configuration
# Uncomment to restrict API access via Authorization Bearer token header:
# REPOLENS_API_KEY=your-secret-api-key

# CORS Origins Configuration (comma-separated)
# REPOLENS_ALLOWED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

---

## Running the Application

Launch the development server:
```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Open [http://localhost:8000](http://localhost:8000) in your browser to view the interactive dashboard.

---

## API Documentation

All request payloads should use JSON format. If `REPOLENS_API_KEY` is configured in `.env`, include `Authorization: Bearer <key>` in headers.

### `POST /api/analyze`
Analyzes a repository (local path or Git URL) and returns metric reports.
* **Payload**:
  ```json
  {
    "repo_path": "e:/Projects/MyProject",
    "force_refresh": false
  }
  ```
* **Response**: A comprehensive metrics payload containing commit summaries, daily commit graphs, top author lists, code churn history, and file hotspots.

### `POST /api/summarize`
Generates a 3-bullet standup summary of the repository status, activity, and progress.
* **Payload**:
  ```json
  {
    "repo_path": "e:/Projects/MyProject"
  }
  ```

### `POST /api/index`
Synchronously indexes the codebase into Supabase vectors for RAG chat.
* **Payload**:
  ```json
  {
    "repo_path": "e:/Projects/MyProject"
  }
  ```

### `POST /api/chat`
Answers technical questions using context retrieved from the indexed codebase.
* **Payload**:
  ```json
  {
    "repo_path": "e:/Projects/MyProject",
    "query": "How is authentication implemented?"
  }
  ```

### `POST /api/dependencies`
Generates a file-level dependency knowledge graph using AST import analysis.
* **Payload**:
  ```json
  {
    "repo_path": "e:/Projects/MyProject"
  }
  ```
* **Response**: Returns a JSON representation containing nodes (files) and edges (imports).

---

## License
MIT License. Feel free to use and distribute.
