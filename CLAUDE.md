# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Commands

```bash
# Start backend server
python run.py

# Install dependencies
pip install -r requirements.txt

# Health check (verify API keys loaded)
curl http://localhost:5000/api/health
```

## Architecture Overview

Full-stack GitHub repository analyzer with RAG-powered AI chat.

```
repo-analyzer/
├── backend/           # Flask REST API + analysis engine
│   ├── app.py         # 6 REST endpoints, in-memory repo store
│   ├── github_fetcher.py  # GitHub Contents API + Git Trees API
│   ├── parser.py      # AST (Python) + regex (JS/TS) import extraction
│   ├── dependency_graph.py  # NetworkX → D3.js JSON
│   ├── complexity.py  # Radon (Python) + custom cyclomatic (JS/TS)
│   ├── embeddings.py  # sentence-transformers + ChromaDB RAG
│   └── chat_engine.py # Local CodeT5 model for chat/explain/readme
├── frontend/          # Vanilla HTML/CSS/JS, Tailwind CDN
│   ├── index.html     # Landing page
│   └── dashboard.html # Graph visualization, complexity, chat
├── ai_model/          # Fine-tuned CodeT5 model directory
└── chroma_db/         # Persistent ChromaDB vector store (gitignored)
```

## Backend Flow (`/api/analyze`)

1. **Fetch** - `github_fetcher.fetch_repo()` pulls ~80 files via GitHub API
2. **Parse** - `parser.parse_imports()` extracts dependency edges
3. **Graph** - `dependency_graph.build_graph()` creates NetworkX DiGraph → D3 JSON
4. **Complexity** - `complexity.analyze_complexity()` calculates cyclomatic scores
5. **Embed** - `embeddings.build_embeddings()` chunks + embeds code into ChromaDB

## Key Configuration

- `backend/github_fetcher.py`: `MAX_FILES = 300`, `MAX_FILE_SIZE = 300KB`
- `backend/embeddings.py`: `CHUNK_SIZE = 400`, `EMBED_MODEL = "all-MiniLM-L6-v2"`
- `backend/chat_engine.py`: Model path `ai_model/my_repo_model` (local CodeT5)

## Environment Variables

Required in `.env`:
```
ANTHROPIC_API_KEY=sk-ant-api03-...   # For chat, explain, readme generation
GITHUB_TOKEN=ghp_...                  # Optional, increases rate limit 60→5000/hr
```

## Model Training

The chat engine uses a local fine-tuned CodeT5 model. If not trained:
```bash
# Train model (ai_model/train.py)
# Generate README (ai_model/generate_readme.py)
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/analyze` | POST | Analyze repo, build embeddings |
| `/api/graph` | GET | Get D3 graph JSON |
| `/api/complexity` | GET | Get complexity scores |
| `/api/chat` | POST | RAG chat with codebase |
| `/api/explain-file` | POST | Explain specific file |
| `/api/readme` | POST | Generate README.md |
| `/api/health` | GET | Check API keys loaded |
