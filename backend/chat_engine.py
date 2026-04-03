"""
chat_engine.py  —  RepoLens Hybrid AI Engine

Priority order:
  1. Ollama (local, free — phi3 / llama3 / mistral)
  2. Claude API (best quality, needs API key — graceful fallback)
  3. Template fallback (if nothing else works)

Install Ollama: https://ollama.com  →  ollama pull phi3
"""

import os
import json
import time
import urllib.request
import urllib.error


# ── Config ───────────────────────────────────────────────

OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3")

# Lazy singletons
_claude = None
_ollama_cache = {"checked_at": 0.0, "available": False}


# ── Engine loaders ───────────────────────────────────────

def _load_claude():
    global _claude
    if _claude:
        return _claude
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    try:
        import anthropic
        _claude = anthropic.Anthropic(api_key=key)
        return _claude
    except ImportError:
        print("[chat] anthropic package not installed — Claude unavailable")
        return None


def _ollama_available() -> bool:
    """Check if Ollama daemon is reachable (cached for 10 s)."""
    now = time.time()
    if now - _ollama_cache["checked_at"] < 10:
        return _ollama_cache["available"]
    try:
        urllib.request.urlopen(OLLAMA_URL, timeout=2)
        available = True
    except Exception:
        available = False
    _ollama_cache["checked_at"] = now
    _ollama_cache["available"] = available
    return available


def check_ollama_health() -> dict:
    """Return detailed Ollama health info for the /api/health endpoint."""
    try:
        resp = urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3)
        data = json.loads(resp.read())
        models = [m.get("name", "") for m in data.get("models", [])]
        has_model = any(OLLAMA_MODEL in m for m in models)
        return {
            "running": True,
            "model_available": has_model,
            "configured_model": OLLAMA_MODEL,
            "installed_models": models[:10],
        }
    except Exception as e:
        return {
            "running": False,
            "model_available": False,
            "configured_model": OLLAMA_MODEL,
            "error": str(e),
        }


def check_claude_health() -> dict:
    """Verify the Claude API key is valid (lightweight check)."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return {"configured": False}
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        # Just try a minimal call to verify key
        client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=5,
            messages=[{"role": "user", "content": "ping"}],
        )
        return {"configured": True, "valid": True}
    except Exception as e:
        return {"configured": True, "valid": False, "error": str(e)}


# ── Ask functions ────────────────────────────────────────

def _ask_ollama(prompt: str, max_tokens: int = 600) -> str | None:
    """Ask Ollama (local LLM — best quality, totally free)."""
    try:
        payload = json.dumps({
            "model":  OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.7,
                "top_p": 0.9,
            }
        }).encode()
        req = urllib.request.Request(
            OLLAMA_URL + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip() or None
    except Exception as e:
        print(f"[chat] Ollama error: {e}")
        return None


def _ask_claude(system: str, messages: list, max_tokens: int = 900) -> str | None:
    """Ask Claude API (graceful fallback)."""
    client = _load_claude()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return resp.content[0].text
    except Exception as e:
        print(f"[chat] Claude error: {e}")
        return None


def active_engine() -> str:
    """Return which AI engine is currently active. Public for health-check."""
    if _ollama_available():
        return "ollama"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "claude"
    return "none"


# ── Context & prompt builders ────────────────────────────

def _fmt_context(chunks: list) -> str:
    if not chunks:
        return "No code context retrieved."
    parts = []
    for i, c in enumerate(chunks[:5], 1):
        parts.append(
            f"[File: {c.get('file_name','?')} | relevance: {c.get('relevance_score',0):.2f}]\n"
            f"{c['text'][:500]}"
        )
    return "\n\n".join(parts)


def _build_system(repo_meta: dict, complexity: list) -> str:
    top = sorted(complexity, key=lambda x: x["complexity"], reverse=True)[:5]
    comp_str = "\n".join(
        f"  - {f['file']}: score {f['complexity']} ({f['grade_label']})"
        for f in top
    )
    return (
        f"You are an expert code analysis AI assistant for the repository: "
        f"{repo_meta.get('full_name','?')}.\n\n"
        f"Repository info:\n"
        f"- Description: {repo_meta.get('description','')}\n"
        f"- Language: {repo_meta.get('language','?')}\n"
        f"- Stars: {repo_meta.get('stars',0):,}\n"
        f"- License: {repo_meta.get('license','?')}\n\n"
        f"Most complex files:\n{comp_str}\n\n"
        f"Instructions:\n"
        f"- Answer questions about this codebase accurately\n"
        f"- Use `backticks` for file names\n"
        f"- Use code blocks for code snippets\n"
        f"- Be concise and technical\n"
        f"- Use the provided code context to give specific answers"
    )


# ── Public API ───────────────────────────────────────────

def chat_with_repo(
    message: str,
    history: list,
    repo_meta: dict,
    context_chunks: list,
    complexity: list,
) -> str:
    engine  = active_engine()
    context = _fmt_context(context_chunks)
    repo    = repo_meta.get("full_name", "this repository")

    # ── Ollama (primary, local) ─────────────────────────
    if engine == "ollama":
        hist_str = ""
        for turn in history[-6:]:
            role = turn.get("role", "")
            content = turn.get("content", "")
            if role == "user":        hist_str += f"User: {content}\n"
            elif role == "assistant": hist_str += f"Assistant: {content}\n"

        prompt = (
            f"You are an expert code analysis AI for the GitHub repository: {repo}\n"
            f"Description: {repo_meta.get('description','')}\n"
            f"Language: {repo_meta.get('language','?')} | Stars: {repo_meta.get('stars',0):,}\n\n"
            f"Relevant code from the repository:\n{context}\n\n"
            f"{hist_str}"
            f"User: {message}\n"
            f"Assistant:"
        )
        result = _ask_ollama(prompt, max_tokens=500)
        if result:
            return result
        # Ollama was expected but failed — fall through to Claude

    # ── Claude API (graceful fallback) ──────────────────
    if engine == "claude" or _load_claude():
        system = _build_system(repo_meta, complexity)
        msgs = []
        for turn in history[-10:]:
            if turn.get("role") in ("user", "assistant"):
                msgs.append({"role": turn["role"], "content": turn["content"]})
        msgs.append({"role": "user", "content": f"Code context:\n{context}\n\nQuestion: {message}"})
        result = _ask_claude(system, msgs, max_tokens=800)
        if result:
            return result

    # ── No engine ────────────────────────────────────────
    return (
        "⚠️ **No AI engine is available.**\n\n"
        "**Option 1 — Ollama (recommended, free):**\n"
        "1. Download: https://ollama.com\n"
        "2. Install and run: `ollama pull phi3`\n"
        "3. Restart this app\n\n"
        "**Option 2 — Add Claude API key to .env:**\n"
        "```\nANTHROPIC_API_KEY=sk-ant-api03-...\n```"
    )


def explain_file_content(file_data: dict, repo_meta: dict) -> str:
    name       = file_data.get("name", "unknown")
    lang       = file_data.get("lang", "")
    lines      = file_data.get("lines", 0)
    complexity = file_data.get("complexity", 1)
    functions  = file_data.get("functions", 0)
    content    = file_data.get("content", "")[:2000]
    repo       = repo_meta.get("full_name", "?")
    engine     = active_engine()

    base_prompt = (
        f"Explain the following file from the {repo} repository.\n\n"
        f"File: {name} | Language: {lang} | Lines: {lines} | "
        f"Functions: {functions} | Complexity: {complexity}\n\n"
        f"Code:\n```{lang}\n{content[:1200]}\n```\n\n"
        f"Provide:\n1. What this file does (2-3 sentences)\n"
        f"2. Key functions/classes\n3. Complexity notes\n4. Dependencies"
    )

    # Ollama
    if engine == "ollama":
        result = _ask_ollama(
            "You are a code analysis expert. " + base_prompt, max_tokens=500
        )
        if result:
            return result

    # Claude fallback
    if _load_claude():
        result = _ask_claude(
            "You are an expert code reviewer. Be concise and technical.",
            [{"role": "user", "content": base_prompt}],
            600,
        )
        if result:
            return result

    return f"Cannot explain `{name}` — no AI engine available. Install Ollama or add ANTHROPIC_API_KEY."


def generate_readme(repo_meta: dict, files: list, complexity: list) -> str:
    repo        = repo_meta.get("full_name", "?")
    desc        = repo_meta.get("description", "")
    lang        = repo_meta.get("language", "")
    stars       = repo_meta.get("stars", 0)
    file_list   = "\n".join(
        f"- `{f.get('path', f['name'])}` ({f.get('lang','')}, {f.get('lines',0)} lines)"
        for f in files[:15]
    )
    total_lines = sum(f.get("lines", 0) for f in files)
    existing    = repo_meta.get("existing_readme", "")
    engine      = active_engine()

    base_prompt = (
        f"Generate a complete, professional README.md for this GitHub repository.\n\n"
        f"Repository: {repo}\nDescription: {desc}\nLanguage: {lang}\n"
        f"Stars: {stars:,}\nTotal lines: {total_lines:,}\n\n"
        f"Files:\n{file_list}\n\n"
        + (f"Existing README:\n{existing[:800]}\n\n" if existing else "")
        + "Write a complete README with: title, badges, overview, features, "
          "installation, usage, project structure, contributing, license.\n"
          "Output only the README markdown."
    )

    # Ollama
    if engine == "ollama":
        result = _ask_ollama(base_prompt, max_tokens=800)
        if result:
            return result

    # Claude fallback
    if _load_claude():
        result = _ask_claude(
            "You are a technical writer. Create professional open-source README files.",
            [{"role": "user", "content": base_prompt}],
            1000,
        )
        if result:
            return result

    # Template fallback
    name = repo_meta.get("name", "project")
    return (
        f"# {name}\n\n{desc}\n\n"
        f"## Installation\n```bash\ngit clone https://github.com/{repo}.git\n```\n\n"
        f"## Files\n{file_list}\n\n## License\nSee LICENSE.\n\n"
        f"---\n*Generated by RepoLens — install Ollama or add ANTHROPIC_API_KEY for better output.*"
    )
