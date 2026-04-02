"""
chat_engine.py  —  RepoAI Hybrid AI Engine

Priority order:
  1. Ollama (local, free, real chatbot quality — phi3/llama3)
  2. Fine-tuned Flan-T5 (your trained model)
  3. Claude API (best quality, needs API key)
  4. Template fallback (if nothing else works)

Why Ollama first?
  Ollama runs real LLMs locally (phi3, llama3, mistral).
  These are 100x better at conversation than CodeT5 or Flan-T5.
  They're FREE and work offline.
  Install: https://ollama.com  then run: ollama pull phi3
"""

import os, json
from pathlib import Path

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "ai_model", "my_repo_model")

# Ollama config
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3")   # or "llama3.2", "mistral", "qwen2.5-coder"

# Lazy singletons
_flan_model = _flan_tok = _claude = None
_ollama_state = {"checked_at": 0.0, "available": False}


# ── Engine loaders ───────────────────────────────────────

def _load_flan():
    global _flan_model, _flan_tok
    if _flan_model:
        return _flan_model, _flan_tok
    if not Path(MODEL_PATH).exists():
        return None, None
    try:
        from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
        print("[chat] Loading local Flan-T5 model...")
        _flan_tok   = AutoTokenizer.from_pretrained(MODEL_PATH)
        _flan_model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
        print("[chat] Flan-T5 loaded ✓")
        return _flan_model, _flan_tok
    except Exception as e:
        print(f"[chat] Flan-T5 load failed: {e}")
        return None, None


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
        return None


def _ollama_available():
    import time
    now = time.time()
    if now - _ollama_state["checked_at"] < 5:
        return _ollama_state["available"]
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434", timeout=2)
        available = True
    except Exception:
        available = False
    _ollama_state["checked_at"] = now
    _ollama_state["available"] = available
    return available


# ── Ask functions ────────────────────────────────────────

def _ask_ollama(prompt: str, max_tokens: int = 600) -> str | None:
    """Ask Ollama (local LLM — best quality, totally free)."""
    try:
        import urllib.request, json as _json
        payload = _json.dumps({
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
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = _json.loads(resp.read())
            return data.get("response", "").strip() or None
    except Exception as e:
        print(f"[chat] Ollama error: {e}")
        return None


def _ask_flan(prompt: str, max_new_tokens: int = 350) -> str | None:
    """Ask the local fine-tuned Flan-T5 model."""
    model, tok = _load_flan()
    if model is None:
        return None
    try:
        # Flan-T5 needs the instruction prefix
        full_prompt = "Answer the following question about a GitHub repository: " + prompt
        inputs = tok(full_prompt, return_tensors="pt", max_length=384, truncation=True)
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            num_beams=4,
            early_stopping=True,
            no_repeat_ngram_size=3,
            length_penalty=1.2,
        )
        result = tok.decode(out[0], skip_special_tokens=True).strip()
        return result if len(result) > 10 else None
    except Exception as e:
        print(f"[chat] Flan-T5 error: {e}")
        return None


def _ask_claude(system: str, messages: list, max_tokens: int = 900) -> str | None:
    """Ask Claude API."""
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


def _active_engine() -> str:
    if _ollama_available():             return "ollama"
    if Path(MODEL_PATH).exists():       return "flan"
    if os.getenv("ANTHROPIC_API_KEY"): return "claude"
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
    engine  = _active_engine()
    context = _fmt_context(context_chunks)
    repo    = repo_meta.get("full_name", "this repository")

    # ── Ollama (real chatbot, best quality) ──────────────
    if engine == "ollama":
        # Build full conversation context for Ollama
        hist_str = ""
        for turn in history[-6:]:
            role = turn.get("role","")
            content = turn.get("content","")
            if role == "user":      hist_str += f"User: {content}\n"
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

    # ── Fine-tuned Flan-T5 ───────────────────────────────
    if engine in ("flan", "ollama"):  # try flan as fallback if ollama failed
        prompt = (
            f"Repository: {repo}\n"
            f"Description: {repo_meta.get('description','')}\n\n"
            f"Code context:\n{context[:600]}\n\n"
            f"Question: {message}"
        )
        result = _ask_flan(prompt, max_new_tokens=300)
        if result:
            return result

    # ── Claude API ───────────────────────────────────────
    if engine == "claude" or _load_claude():
        system = _build_system(repo_meta, complexity)
        msgs = []
        for turn in history[-10:]:
            if turn.get("role") in ("user","assistant"):
                msgs.append({"role": turn["role"], "content": turn["content"]})
        msgs.append({"role":"user","content": f"Code context:\n{context}\n\nQuestion: {message}"})
        result = _ask_claude(system, msgs, max_tokens=800)
        if result:
            return result

    # ── No engine ────────────────────────────────────────
    return (
        "⚠️ **No AI engine is running.**\n\n"
        "**Option 1 — Ollama (recommended, free, best quality):**\n"
        "1. Download: https://ollama.com\n"
        "2. Install and run: `ollama pull phi3`\n"
        "3. Restart this app\n\n"
        "**Option 2 — Train your local model:**\n"
        "```bash\npython ai_model/collect_data.py\npython ai_model/train.py\n```\n\n"
        "**Option 3 — Add Claude API key to .env:**\n"
        "```\nANTHROPIC_API_KEY=sk-ant-api03-...\n```"
    )


def explain_file_content(file_data: dict, repo_meta: dict) -> str:
    name      = file_data.get("name","unknown")
    lang      = file_data.get("lang","")
    lines     = file_data.get("lines",0)
    complexity= file_data.get("complexity",1)
    functions = file_data.get("functions",0)
    content   = file_data.get("content","")[:2000]
    repo      = repo_meta.get("full_name","?")
    engine    = _active_engine()

    # Ollama
    if engine == "ollama":
        prompt = (
            f"You are a code analysis expert. Explain the following file from the {repo} repository.\n\n"
            f"File: {name} | Language: {lang} | Lines: {lines} | Functions: {functions} | Complexity: {complexity}\n\n"
            f"Code:\n```{lang}\n{content[:1200]}\n```\n\n"
            f"Provide:\n1. What this file does (2-3 sentences)\n"
            f"2. Key functions/classes\n3. Complexity notes\n4. Dependencies"
        )
        result = _ask_ollama(prompt, max_tokens=500)
        if result: return result

    # Flan-T5
    if engine in ("flan","ollama"):
        prompt = (
            f"Explain the file {name} in {repo}. "
            f"Language: {lang}. Lines: {lines}. Functions: {functions}. "
            f"Code: {content[:500]}"
        )
        result = _ask_flan(prompt, max_new_tokens=300)
        if result: return result

    # Claude
    if _load_claude():
        prompt = (
            f"Explain `{name}` from `{repo}`.\n\n"
            f"Stats: {lines} lines | {functions} functions | complexity {complexity} | {lang}\n\n"
            f"```{lang}\n{content}\n```\n\n"
            f"Provide:\n1. **Purpose** (2-3 sentences)\n2. **Key functions/classes**\n"
            f"3. **Complexity notes**\n4. **Dependencies**"
        )
        result = _ask_claude(
            "You are an expert code reviewer. Be concise and technical.",
            [{"role":"user","content":prompt}], 600
        )
        if result: return result

    return f"Cannot explain `{name}` — no AI engine available. Install Ollama or add ANTHROPIC_API_KEY."


def generate_readme(repo_meta: dict, files: list, complexity: list) -> str:
    repo        = repo_meta.get("full_name","?")
    desc        = repo_meta.get("description","")
    lang        = repo_meta.get("language","")
    stars       = repo_meta.get("stars",0)
    file_list   = "\n".join(f"- `{f.get('path',f['name'])}` ({f.get('lang','')}, {f.get('lines',0)} lines)" for f in files[:15])
    total_lines = sum(f.get("lines",0) for f in files)
    existing    = repo_meta.get("existing_readme","")
    engine      = _active_engine()

    # Ollama
    if engine == "ollama":
        prompt = (
            f"Generate a complete, professional README.md for this GitHub repository.\n\n"
            f"Repository: {repo}\nDescription: {desc}\nLanguage: {lang}\n"
            f"Stars: {stars:,}\nTotal lines: {total_lines:,}\n\n"
            f"Files:\n{file_list}\n\n"
            + (f"Existing README:\n{existing[:800]}\n\n" if existing else "")
            + "Write a complete README with: title, badges, overview, features, installation, usage, project structure, contributing, license.\nOutput only the README."
        )
        result = _ask_ollama(prompt, max_tokens=800)
        if result: return result

    # Flan-T5
    if engine in ("flan","ollama"):
        prompt = f"Generate a README for {repo}. Description: {desc}. Language: {lang}."
        result = _ask_flan(prompt, max_new_tokens=500)
        if result: return result

    # Claude
    if _load_claude():
        prompt = (
            f"Generate a complete professional README.md for: {repo}\n\n"
            f"Description: {desc}\nLanguage: {lang} | Stars: {stars:,}\n"
            f"Files:\n{file_list}\n\n"
            + (f"Existing README:\n{existing[:1200]}\n\n" if existing else "")
            + "Include: title+badges, overview, features, installation, usage, project structure, contributing, license."
        )
        result = _ask_claude(
            "You are a technical writer. Create professional open-source README files.",
            [{"role":"user","content":prompt}], 1000
        )
        if result: return result

    # Template fallback
    name = repo_meta.get("name","project")
    return (
        f"# {name}\n\n{desc}\n\n"
        f"## Installation\n```bash\ngit clone https://github.com/{repo}.git\n```\n\n"
        f"## Files\n{file_list}\n\n## License\nSee LICENSE.\n\n"
        f"---\n*Generated by RepoAI — install Ollama or add ANTHROPIC_API_KEY for better output.*"
    )
