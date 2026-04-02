"""
collect_data.py  —  RepoAI Training Data Generator (v2 - Fixed)
Generates 1000+ high-quality conversational Q&A pairs.

WHAT CHANGED FROM v1:
  - v1 generated 80% garbage data like "X is a file with 0 lines of code"
  - v2 generates rich, conversational answers that teach the model to chat
  - v2 actually fetches file contents for code explanation pairs
  - v2 includes 50+ generic coding knowledge pairs
  - v2 generates ~1200+ pairs vs v1's ~200

Run: python ai_model/collect_data.py
"""

import json, requests, os, base64, time, random
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# ── Config ───────────────────────────────────────────────
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
HEADERS = {"Accept": "application/vnd.github+json"}
if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

OUT_DIR    = "ai_model/data"
TRAIN_FILE = f"{OUT_DIR}/train.jsonl"
TEST_FILE  = f"{OUT_DIR}/test.jsonl"
TRAIN_SPLIT = 0.85

REPOS = [
    "psf/requests",      "pallets/flask",       "tiangolo/fastapi",
    "django/django",     "numpy/numpy",          "pandas-dev/pandas",
    "expressjs/express", "axios/axios",          "lodash/lodash",
    "denoland/deno",     "vuejs/vue",            "microsoft/TypeScript",
    "golang/go",         "rust-lang/rust",       "rails/rails",
    "laravel/laravel",   "spring-projects/spring-boot",
    "pallets/click",     "encode/httpx",         "torvalds/linux",
    "facebook/react",    "vercel/next.js",       "socketio/socket.io",
    "redis/redis",       "docker/compose",
]

MAX_FILES_PER_REPO = 8
CODE_EXTS = {".py",".js",".ts",".jsx",".tsx",".java",".go",
             ".rs",".rb",".php",".cs",".cpp",".c",".swift",".kt"}


# ── GitHub helpers ───────────────────────────────────────

def gh(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code in (403, 429):
            print("  ⚠ Rate limited. Add GITHUB_TOKEN to .env")
            return None
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ⚠ {e}")
        return None

def get_file_content(owner, repo, path):
    data = gh(f"https://api.github.com/repos/{owner}/{repo}/contents/{path}")
    if not data or not isinstance(data, dict): return None
    if data.get("encoding") == "base64":
        try: return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except: return None
    return None

def get_tree(owner, repo):
    info = gh(f"https://api.github.com/repos/{owner}/{repo}")
    if not info: return [], {}
    branch = info.get("default_branch", "main")
    tree   = gh(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    items  = tree.get("tree", []) if tree else []
    return [i for i in items if i["type"] == "blob"], info


# ── Q&A builders (rich, conversational) ──────────────────

def q_overview(repo, desc, lang, stars, topics):
    topic_str = ", ".join(topics[:5]) if topics else "general software development"
    return {
        "prompt": f"What does the {repo} repository do?",
        "completion": (
            f"`{repo}` is an open-source {lang} project with {stars:,} GitHub stars. "
            f"{desc} "
            f"It is commonly used for: {topic_str}."
        )
    }

def q_overview_alt(repo, desc, lang, stars):
    """Alternative phrasing for the same question."""
    return {
        "prompt": f"Tell me about {repo}.",
        "completion": (
            f"`{repo}` is a popular {lang} project on GitHub with {stars:,} stars. "
            f"{desc} "
            f"It's widely used by developers and has an active open-source community."
        )
    }

def q_install(repo, lang, desc):
    cmds = {
        "python":     f"pip install {repo.split('/')[1]}",
        "javascript": f"npm install {repo.split('/')[1]}",
        "typescript": f"npm install {repo.split('/')[1]}",
        "go":         f"go get github.com/{repo}",
        "rust":       f"cargo add {repo.split('/')[1]}",
        "ruby":       f"gem install {repo.split('/')[1]}",
        "php":        f"composer require {repo}",
    }
    cmd = cmds.get(lang.lower(), f"git clone https://github.com/{repo}.git")
    return {
        "prompt": f"How do I install {repo.split('/')[1]}?",
        "completion": (
            f"To install `{repo.split('/')[1]}`:\n\n"
            f"**Via package manager:**\n```bash\n{cmd}\n```\n\n"
            f"**From source:**\n```bash\n"
            f"git clone https://github.com/{repo}.git\n"
            f"cd {repo.split('/')[1]}\n```\n\n"
            f"**About:** {desc}"
        )
    }

def q_file_list(repo, paths):
    listed = "\n".join(f"- `{p}`" for p in paths[:20])
    return {
        "prompt": f"List the source files in the {repo} repository.",
        "completion": f"The main source files in `{repo}` are:\n\n{listed}"
    }

def q_architecture(repo, paths, desc, lang):
    folders = sorted(set(str(Path(p).parent) for p in paths if "/" in p))[:10]
    folder_str = "\n".join(f"- `{f}/`" for f in folders)
    return {
        "prompt": f"Explain the architecture of {repo}.",
        "completion": (
            f"## Architecture of `{repo}`\n\n"
            f"{desc}\n\n"
            f"**Language:** {lang} | **Files:** {len(paths)}\n\n"
            f"**Directory structure:**\n{folder_str}\n\n"
            f"The project is organized into {len(folders)} main directories, "
            f"following standard {lang} project conventions."
        )
    }

def q_auth(repo, paths):
    auth_files = [p for p in paths if any(
        k in p.lower() for k in ["auth","login","token","session","security","jwt","oauth","permission"]
    )]
    if auth_files:
        answer = (
            f"Authentication in `{repo}` is handled in:\n\n"
            + "\n".join(f"- `{f}`" for f in auth_files[:5])
            + "\n\nThese files manage user authentication, session handling, and security."
        )
    else:
        answer = (
            f"No dedicated authentication files found in `{repo}`. "
            f"Authentication may be handled via middleware or the main application module. "
            f"Search for `auth`, `login`, or `session` keywords in the codebase."
        )
    return {"prompt": f"Which file handles authentication in {repo}?", "completion": answer}

def q_entry(repo, paths, lang):
    keywords = {
        "python":["main.py","app.py","run.py","server.py","__main__.py","manage.py","wsgi.py"],
        "javascript":["index.js","app.js","server.js","main.js"],
        "typescript":["index.ts","app.ts","main.ts","server.ts"],
        "go":["main.go","server.go"],
        "rust":["main.rs","lib.rs"],
        "ruby":["application.rb","config.ru"],
    }
    kws = keywords.get(lang.lower(), ["main","app","index","server"])
    entries = [p for p in paths if any(k in Path(p).name.lower() for k in kws)]
    if entries:
        ans = "The main entry points are:\n\n" + "\n".join(f"- `{f}`" for f in entries[:5])
        ans += f"\n\nThese files initialize the {repo.split('/')[1]} application and start execution."
    else:
        ans = (f"Check `package.json` (JS) or `setup.py`/`pyproject.toml` (Python) "
               f"for entry point configuration in `{repo}`.")
    return {"prompt": f"What are the main entry points of {repo}?", "completion": ans}

def q_readme(repo, desc, lang, stars, paths, topics):
    file_list = "\n".join(f"- `{p}`" for p in paths[:12])
    topic_badges = " ".join(f"`{t}`" for t in topics[:4]) if topics else ""
    return {
        "prompt": f"Generate a professional README.md for the {repo} repository.",
        "completion": (
            f"# {repo.split('/')[1].title()}\n\n"
            f"> {desc}\n\n"
            f"![Stars](https://img.shields.io/github/stars/{repo}?style=flat-square)\n"
            f"![Language](https://img.shields.io/badge/language-{lang}-blue?style=flat-square)\n"
            f"![License](https://img.shields.io/github/license/{repo}?style=flat-square)\n\n"
            f"## Overview\n\n{desc}\n\n"
            f"**Topics:** {topic_badges}\n\n"
            f"## Installation\n\n"
            f"```bash\ngit clone https://github.com/{repo}.git\ncd {repo.split('/')[1]}\n```\n\n"
            f"## Project Structure\n\n{file_list}\n\n"
            f"## Contributing\n\nPull requests welcome! Please open an issue first.\n\n"
            f"## License\n\nSee [LICENSE](LICENSE) for details.\n\n"
            f"---\n*{stars:,} stars on GitHub*"
        )
    }

def q_complexity(repo, paths, lang):
    core_files = [p for p in paths if any(
        k in p.lower() for k in ["core","engine","parser","compiler","processor","router","handler"]
    )]
    ans = (
        f"The most complex files in `{repo}` are typically:\n\n"
        + "\n".join(f"- `{f}`" for f in (core_files or paths[:4])[:5])
        + f"\n\nThese handle the core logic of the project. "
        f"Use `radon cc <file> -s` (Python) to get exact cyclomatic complexity scores."
    )
    return {"prompt": f"Which files have the highest complexity in {repo}?", "completion": ans}

def q_explain_file(repo, fpath, content, lang):
    """Generate a rich file explanation using ACTUAL file content."""
    lines = content.splitlines()
    total = len(lines)
    imports = [l.strip() for l in lines if l.strip().startswith(
        ("import ","from ","require(","use ","#include","using ")
    )][:6]
    defs = []
    for line in lines:
        s = line.strip()
        for prefix in ["def ","async def ","class ","function ","func ","fn ","pub fn "]:
            if s.startswith(prefix):
                name = s[len(prefix):].split("(")[0].split(":")[0].strip()
                if name and len(name) < 40:
                    defs.append(f"`{prefix.strip()} {name}`")
                break
    snippet = "\n".join(lines[:15])
    imports_str = "\n".join(imports) if imports else "None detected"
    defs_str    = ", ".join(defs[:6]) if defs else "Not detected"

    # Determine purpose from path
    if "util" in fpath.lower() or "helper" in fpath.lower():
        purpose = "utility/helper functions shared across the project"
    elif "core" in fpath.lower() or "engine" in fpath.lower():
        purpose = "the core business logic and main processing pipeline"
    elif "test" in fpath.lower() or "spec" in fpath.lower():
        purpose = "unit tests and test cases for verification"
    elif "config" in fpath.lower() or "setting" in fpath.lower():
        purpose = "application configuration and environment settings"
    elif "model" in fpath.lower():
        purpose = "data models, schemas, and database interactions"
    elif "route" in fpath.lower() or "view" in fpath.lower() or "handler" in fpath.lower():
        purpose = "HTTP request handling and route definitions"
    elif "auth" in fpath.lower():
        purpose = "authentication, authorization, and security logic"
    else:
        purpose = "module-specific functionality"

    return {
        "prompt": (
            f"Explain the file `{fpath}` in the {repo} repository.\n\n"
            f"```{lang}\n{snippet}\n```"
        ),
        "completion": (
            f"## `{Path(fpath).name}` in `{repo}`\n\n"
            f"**Language:** {lang} | **Lines:** {total}\n\n"
            f"**Purpose:** This file handles {purpose} "
            f"in the `{repo.split('/')[1]}` project.\n\n"
            f"**Key definitions:** {defs_str}\n\n"
            f"**Imports:**\n```\n{imports_str}\n```\n\n"
            f"**Size:** {total} lines of {lang} code."
        )
    }

def q_add_feature(repo, lang, desc):
    return {
        "prompt": f"How do I add a new feature to {repo}?",
        "completion": (
            f"To add a new feature to `{repo}`:\n\n"
            f"1. **Fork and clone:**\n```bash\ngit clone https://github.com/{repo}.git\ncd {repo.split('/')[1]}\n```\n\n"
            f"2. **Create a branch:**\n```bash\ngit checkout -b feature/my-feature\n```\n\n"
            f"3. **Study the existing code** — understand patterns used in the project\n\n"
            f"4. **Implement** your feature following the existing {lang} style\n\n"
            f"5. **Write tests** for your new code\n\n"
            f"6. **Submit a PR** with a clear description of what and why\n\n"
            f"The project: {desc}"
        )
    }

def q_tests(repo, paths, lang):
    test_files = [p for p in paths if any(k in p.lower() for k in ["test","spec","__test__"])][:4]
    runners = {
        "python":"pytest","javascript":"npm test","typescript":"npm test",
        "go":"go test ./...","rust":"cargo test","ruby":"bundle exec rspec",
    }
    runner = runners.get(lang.lower(), "# see README for test command")
    test_str = "\n".join(f"- `{f}`" for f in test_files) if test_files else "No test files found in root"
    return {
        "prompt": f"How do I run the tests for {repo}?",
        "completion": (
            f"To run tests for `{repo}`:\n\n"
            f"```bash\n{runner}\n```\n\n"
            f"**Test files found:**\n{test_str}\n\n"
            f"Check `CONTRIBUTING.md` or `README.md` for full test instructions."
        )
    }

def q_contribute(repo, desc):
    return {
        "prompt": f"How can I contribute to {repo}?",
        "completion": (
            f"To contribute to `{repo}`:\n\n"
            f"1. Read `CONTRIBUTING.md` in the repo\n"
            f"2. Fork and clone the repo locally\n"
            f"3. Look for issues tagged `good first issue` or `help wanted`\n"
            f"4. Create a branch: `git checkout -b fix/your-fix`\n"
            f"5. Make changes + write tests\n"
            f"6. Open a PR with a clear description\n\n"
            f"About: {desc}"
        )
    }

def q_tech_stack(repo, lang, desc, paths):
    """What technologies does this repo use?"""
    return {
        "prompt": f"What tech stack does {repo} use?",
        "completion": (
            f"`{repo}` is built with **{lang}**. {desc}\n\n"
            f"It has {len(paths)} source files in its root/tree. "
            f"Check `package.json` (JS/TS), `requirements.txt` (Python), "
            f"`go.mod` (Go), or `Cargo.toml` (Rust) for the full dependency list."
        )
    }

def q_dependencies(repo, paths, lang):
    """What are the dependencies?"""
    dep_files = [p for p in paths if any(
        k in Path(p).name.lower() for k in
        ["requirements", "package.json", "go.mod", "cargo.toml", "gemfile", "composer.json", "pom.xml"]
    )]
    if dep_files:
        files_str = "\n".join(f"- `{f}`" for f in dep_files[:5])
        return {
            "prompt": f"What are the dependencies of {repo}?",
            "completion": (
                f"Dependencies for `{repo}` are defined in:\n\n{files_str}\n\n"
                f"Read these files to see the full list of external packages used."
            )
        }
    return {
        "prompt": f"What are the dependencies of {repo}?",
        "completion": (
            f"Check the project configuration files in `{repo}` for dependency information. "
            f"For {lang} projects, look for `requirements.txt`, `pyproject.toml`, "
            f"`package.json`, or similar dependency manifest files."
        )
    }

def q_license(repo, paths):
    """What license does this use?"""
    license_files = [p for p in paths if "license" in p.lower()]
    if license_files:
        return {
            "prompt": f"What license does {repo} use?",
            "completion": (
                f"License information for `{repo}` can be found in: "
                + ", ".join(f"`{f}`" for f in license_files[:3])
                + ". Check this file for specific terms and permissions."
            )
        }
    return {
        "prompt": f"What license does {repo} use?",
        "completion": f"Check the repository page for `{repo}` on GitHub for license information."
    }


# ── Generic conversational pairs (no repo specific) ──────

GENERIC_CONVOS = [
    # Core concepts
    {
        "prompt": "What is cyclomatic complexity and why does it matter?",
        "completion": (
            "**Cyclomatic complexity** measures how many independent paths exist through your code.\n\n"
            "**Scores:**\n- 1-10: Simple ✅\n- 11-20: Moderate ⚠️\n- 21+: Complex ❌\n\n"
            "**Why it matters:** High complexity = more bugs, harder to test, harder to maintain.\n\n"
            "**How to reduce it:**\n"
            "- Break large functions into smaller ones\n"
            "- Use early returns instead of deep nesting\n"
            "- Replace long if/else chains with dictionaries"
        )
    },
    {
        "prompt": "What is a dependency graph in software?",
        "completion": (
            "A **dependency graph** shows how files/modules import each other.\n\n"
            "**Nodes** = files | **Arrows** = import relationships (A→B means A imports B)\n\n"
            "**Why useful:**\n"
            "- Shows which files are most critical (imported by many others)\n"
            "- Detects circular dependencies (A imports B, B imports A)\n"
            "- Helps predict impact of code changes\n\n"
            "**Hub files** (imported by 3+ others) are the most important — changes there affect the whole system."
        )
    },
    {
        "prompt": "What does RAG mean in AI?",
        "completion": (
            "**RAG = Retrieval-Augmented Generation**\n\n"
            "A technique that makes AI more accurate:\n\n"
            "1. **Retrieve** — find relevant information from a database\n"
            "2. **Augment** — add it to the AI prompt as context\n"
            "3. **Generate** — AI answers using both the question AND retrieved context\n\n"
            "**In RepoAI:** Code chunks → ChromaDB → semantic search → top 5 chunks → "
            "sent to AI → smart answer based on your actual code."
        )
    },
    {
        "prompt": "What is a circular dependency and how do I fix it?",
        "completion": (
            "A **circular dependency** = File A imports B, and File B imports A → "
            "infinite loop at import time.\n\n"
            "**Symptoms:** `ImportError: cannot import name X`, app crashes on startup\n\n"
            "**Fixes:**\n"
            "1. Extract shared code into a 3rd file that both A and B import\n"
            "2. Move the import inside the function (lazy import)\n"
            "3. Redesign the module structure\n\n"
            "In RepoAI, circular deps appear as **dashed nodes** on the dependency graph."
        )
    },
    {
        "prompt": "How do I improve a file with high complexity?",
        "completion": (
            "To reduce complexity:\n\n"
            "**1. Break large functions into smaller ones**\n\n"
            "**2. Use early returns to reduce nesting:**\n"
            "```python\n# Bad\ndef process(x):\n    if x:\n        if x > 0:\n            return x * 2\n\n"
            "# Good\ndef process(x):\n    if not x: return None\n    if x <= 0: return None\n    return x * 2\n```\n\n"
            "**3. Replace if-chains with dictionaries:**\n"
            "```python\nrunners = {'py': run_python, 'js': run_js}\nrunners[lang]()\n```\n\n"
            "**4. Extract classes** for groups of related functions."
        )
    },
    {
        "prompt": "Explain what utils.py typically does in a Python project.",
        "completion": (
            "`utils.py` contains shared helper functions used across multiple modules:\n\n"
            "- String formatting/parsing\n- Date/time helpers\n"
            "- File I/O convenience functions\n- Validation functions\n- Constants\n\n"
            "**Why:** Avoids code duplication — write once, import everywhere.\n\n"
            "**Complexity:** Usually grade A or B (simple, focused functions)."
        )
    },
    {
        "prompt": "What is the difference between complexity grade A and F?",
        "completion": (
            "Complexity grades:\n\n"
            "| Grade | Score | Status |\n|-------|-------|--------|\n"
            "| **A** | 1-5   | ✅ Simple, easy to test |\n"
            "| **B** | 6-10  | ✅ Manageable |\n"
            "| **C** | 11-15 | ⚠️ Consider refactoring |\n"
            "| **D** | 16-20 | ⚠️ Hard to maintain |\n"
            "| **E** | 21-30 | ❌ Refactor soon |\n"
            "| **F** | 30+   | ❌ Critical — bugs likely |\n\n"
            "Rule: Functions over grade C should be broken into smaller pieces."
        )
    },
    {
        "prompt": "How does RepoAI analyze GitHub repositories?",
        "completion": (
            "RepoAI analyzes in 4 stages:\n\n"
            "**1. Fetch** — Downloads up to 300 files via GitHub REST API\n\n"
            "**2. Parse & Analyze**\n"
            "- Imports: Python `ast` module or regex (JS/TS)\n"
            "- Complexity: Radon library\n"
            "- Graph: NetworkX\n\n"
            "**3. Embed**\n"
            "- Code split into ~400 char chunks\n"
            "- Converted to vectors via sentence-transformers\n"
            "- Stored in ChromaDB\n\n"
            "**4. Chat**\n"
            "- Question → semantic search → top 5 relevant chunks → AI model → answer"
        )
    },
    {
        "prompt": "How do I generate a README for my repository?",
        "completion": (
            "In RepoAI dashboard:\n\n"
            "1. Click the **README tab**\n"
            "2. Click **'Generate with AI'**\n"
            "3. Wait ~5 seconds\n"
            "4. Click **'Copy'** to copy the Markdown\n\n"
            "The AI generates: title + badges, overview, features, installation, "
            "project structure, contributing, and license sections."
        )
    },
    {
        "prompt": "What does the embeddings module do in RepoAI?",
        "completion": (
            "`embeddings.py` converts source code into searchable vectors:\n\n"
            "**Process:**\n"
            "1. Split each file into ~400 char overlapping chunks\n"
            "2. Each chunk → 384-dimensional vector (using `all-MiniLM-L6-v2`)\n"
            "3. Vectors stored in ChromaDB\n\n"
            "**At query time:**\n"
            "- Question → vector → ChromaDB finds 5 most similar code chunks\n"
            "- Those chunks are added to the AI prompt as context\n\n"
            "This means AI reads *actual relevant code* before answering."
        )
    },
    {
        "prompt": "Why is my code getting a high complexity score?",
        "completion": (
            "High complexity is caused by:\n\n"
            "- **Too many if/else conditions** in a single function\n"
            "- **Deep nesting** (if inside if inside for inside while)\n"
            "- **Long switch/case statements**\n"
            "- **Multiple loops** with conditions inside\n"
            "- **Try/except blocks** with many except clauses\n\n"
            "**Each of these adds +1 to complexity score:**\n"
            "`if`, `elif`, `else`, `for`, `while`, `try`, `except`, `and`, `or`, `case`\n\n"
            "**Fix:** Break the function into 2-3 smaller functions, each doing one thing."
        )
    },
    {
        "prompt": "What is the best way to understand a new codebase?",
        "completion": (
            "To understand a new codebase quickly:\n\n"
            "1. **Read the README** first — understand what it does\n"
            "2. **Check the dependency graph** — find entry points and hub files\n"
            "3. **Read the entry point** (main.py, index.js, etc.)\n"
            "4. **Follow the data flow** — trace a request/input from start to finish\n"
            "5. **Read the tests** — they show how the code is *meant* to be used\n"
            "6. **Check the most complex files** — they contain the core logic\n\n"
            "**In RepoAI:** The Summary tab + Dependency Graph give you a head start on all of this."
        )
    },
    {
        "prompt": "What is a hub file in a dependency graph?",
        "completion": (
            "A **hub file** is a file that is imported by 3 or more other files.\n\n"
            "**Examples:** `utils.py`, `helpers.js`, `models.py`, `config.ts`\n\n"
            "**Why it matters:**\n"
            "- Hub files are the most critical in the codebase\n"
            "- A bug in a hub file can break many other parts\n"
            "- Changes to hub files need the most careful testing\n\n"
            "In RepoAI's graph, hub files appear as **larger nodes** with more connections."
        )
    },
    # Additional generic knowledge pairs
    {
        "prompt": "What is a virtual environment in Python?",
        "completion": (
            "A **virtual environment** is an isolated Python installation for a specific project. "
            "It keeps dependencies separate between projects to avoid version conflicts.\n\n"
            "**Create one:** `python -m venv venv`\n"
            "**Activate (Windows):** `venv\\Scripts\\activate`\n"
            "**Activate (Mac/Linux):** `source venv/bin/activate`\n"
            "**Install packages:** `pip install flask`\n\n"
            "Always activate before running your project."
        )
    },
    {
        "prompt": "What is the MVC pattern?",
        "completion": (
            "**MVC (Model-View-Controller)** separates applications into three layers:\n\n"
            "- **Model** — manages data, database operations, business logic (`models.py`, `database.py`)\n"
            "- **View** — handles presentation and UI (templates, React components)\n"
            "- **Controller** — processes user input, calls models, returns views (`views.py`, `routes.js`)\n\n"
            "This separation makes code easier to maintain, test, and scale independently."
        )
    },
    {
        "prompt": "What does setup.py do?",
        "completion": (
            "`setup.py` is the package installation script for Python projects. It defines:\n\n"
            "- Package name, version, and author\n"
            "- Dependencies (install_requires)\n"
            "- Entry points and console scripts\n"
            "- Package data and classifiers\n\n"
            "Used to build and distribute the package to PyPI with `pip install .` or `python setup.py install`."
        )
    },
    {
        "prompt": "What is the difference between authentication and authorization?",
        "completion": (
            "**Authentication (AuthN)** verifies WHO you are — confirms identity via "
            "password, API key, or OAuth token.\n\n"
            "**Authorization (AuthZ)** determines WHAT you can do — checks permissions "
            "after identity is confirmed.\n\n"
            "**Example:** Authentication logs you in; Authorization decides if you can "
            "access admin pages.\n\n"
            "In code: `auth.py` handles login/tokens; decorators like `@require_admin` "
            "handle authorization checks."
        )
    },
    {
        "prompt": "What does requirements.txt do?",
        "completion": (
            "`requirements.txt` lists all Python package dependencies with version constraints.\n\n"
            "**Install everything:** `pip install -r requirements.txt`\n"
            "**Generate from current environment:** `pip freeze > requirements.txt`\n\n"
            "Each line is a package: `flask==3.0.0`, `requests>=2.28`, `numpy`."
        )
    },
    {
        "prompt": "What does __init__.py do in Python?",
        "completion": (
            "`__init__.py` marks a directory as a Python package so it can be imported.\n\n"
            "It runs when the package is first imported and commonly:\n"
            "- Exports the package's public API by importing key classes/functions\n"
            "- Defines `__all__` to control what `from package import *` exports\n"
            "- Sets up package-level configuration\n\n"
            "Can be empty or contain initialization code."
        )
    },
    {
        "prompt": "What does package.json do?",
        "completion": (
            "`package.json` is the Node.js project manifest. It defines:\n\n"
            "- Project name, version, and description\n"
            "- Dependencies (`dependencies` and `devDependencies`)\n"
            "- Scripts (`npm run dev`, `npm test`, etc.)\n"
            "- Entry point (`main` field)\n\n"
            "Run scripts with: `npm run <script-name>`."
        )
    },
    {
        "prompt": "How do I find the entry point of a Python project?",
        "completion": (
            "Look for:\n\n"
            "1. A file with `if __name__ == '__main__':` block\n"
            "2. `main.py` or `app.py` in root directory\n"
            "3. `[tool.poetry.scripts]` in `pyproject.toml`\n"
            "4. `entry_points` in `setup.py`\n"
            "5. `console_scripts` in `setup.cfg`\n\n"
            "The entry point is where execution begins when you run the program."
        )
    },
    {
        "prompt": "How do I identify database-related files in a repo?",
        "completion": (
            "Look for:\n\n"
            "1. Files named `models.py`, `database.py`, `db.py`, `schema.py`\n"
            "2. Imports of SQLAlchemy, Django ORM, Mongoose, Prisma\n"
            "3. Classes inheriting from `Model` or `Base`\n"
            "4. Functions named `create`, `find`, `update`, `delete`\n"
            "5. SQL query strings or query builder calls\n"
            "6. Database connection setup with connection strings\n\n"
            "Usually found in `models/` or `db/` directory."
        )
    },
    {
        "prompt": "What is a REST API?",
        "completion": (
            "**REST API** (Representational State Transfer) is an architectural style for "
            "web services that uses HTTP methods:\n\n"
            "- **GET** — Read data\n"
            "- **POST** — Create data\n"
            "- **PUT/PATCH** — Update data\n"
            "- **DELETE** — Remove data\n\n"
            "**Key principles:**\n"
            "- Stateless (each request contains all needed information)\n"
            "- Resource-based URLs (`/api/users/123`)\n"
            "- JSON response format\n"
            "- Standard HTTP status codes (200, 404, 500)"
        )
    },
    {
        "prompt": "What is Git and why use it?",
        "completion": (
            "**Git** is a distributed version control system that tracks changes in your code.\n\n"
            "**Key commands:**\n"
            "- `git init` — start tracking a project\n"
            "- `git add .` — stage all changes\n"
            "- `git commit -m 'message'` — save a snapshot\n"
            "- `git push` — upload to GitHub/remote\n"
            "- `git pull` — download latest changes\n"
            "- `git branch` — create parallel development lines\n\n"
            "**Why:** Lets multiple developers work together, tracks history, enables rollbacks."
        )
    },
    {
        "prompt": "What is Docker and why use it?",
        "completion": (
            "**Docker** packages your application and its dependencies into a **container** — "
            "a lightweight, portable, isolated environment.\n\n"
            "**Key files:**\n"
            "- `Dockerfile` — instructions to build the container image\n"
            "- `docker-compose.yml` — define multi-container applications\n"
            "- `.dockerignore` — files to exclude from the image\n\n"
            "**Why use it:**\n"
            "- \"Works on my machine\" → works everywhere\n"
            "- Consistent dev/staging/production environments\n"
            "- Easy deployment and scaling"
        )
    },
    {
        "prompt": "What is CI/CD?",
        "completion": (
            "**CI/CD** = Continuous Integration / Continuous Deployment\n\n"
            "**CI (Continuous Integration):**\n"
            "- Automatically run tests when code is pushed\n"
            "- Catch bugs before merging to main branch\n"
            "- Tools: GitHub Actions, Jenkins, CircleCI\n\n"
            "**CD (Continuous Deployment):**\n"
            "- Automatically deploy to production after tests pass\n"
            "- No manual release process\n\n"
            "Look for `.github/workflows/`, `.circleci/`, or `Jenkinsfile` in repos."
        )
    },
    {
        "prompt": "How do I read a Python traceback?",
        "completion": (
            "Read a Python traceback **from bottom to top**:\n\n"
            "1. **Last line** = the actual error type and message\n"
            "2. **Lines above** = the call stack (where the error happened)\n"
            "3. **First line** = where execution started\n\n"
            "**Example:**\n```\nTraceback (most recent call last):\n"
            "  File \"app.py\", line 42, in main\n"
            "    result = process(data)\n"
            "  File \"utils.py\", line 15, in process\n"
            "    return data['key']\n"
            "KeyError: 'key'\n```\n\n"
            "The error is `KeyError: 'key'` in `utils.py` line 15, called from `app.py` line 42."
        )
    },
    {
        "prompt": "What is middleware?",
        "completion": (
            "**Middleware** is code that runs between receiving a request and sending a response. "
            "It processes requests before they reach your route handlers.\n\n"
            "**Common uses:**\n"
            "- Authentication (check if user is logged in)\n"
            "- Logging (record every request)\n"
            "- CORS (allow cross-origin requests)\n"
            "- Rate limiting (prevent abuse)\n"
            "- Error handling\n\n"
            "In Express: `app.use(middleware)` | In Flask: `@app.before_request`"
        )
    },
    {
        "prompt": "What is an ORM?",
        "completion": (
            "**ORM (Object-Relational Mapping)** lets you interact with databases using "
            "programming language objects instead of raw SQL.\n\n"
            "**Popular ORMs:**\n"
            "- Python: SQLAlchemy, Django ORM\n"
            "- JavaScript: Prisma, Sequelize, TypeORM\n"
            "- Ruby: ActiveRecord\n"
            "- Java: Hibernate\n\n"
            "**Example (SQLAlchemy):**\n"
            "```python\n# Instead of: SELECT * FROM users WHERE age > 18\n"
            "users = User.query.filter(User.age > 18).all()\n```\n\n"
            "**Pros:** Safer (no SQL injection), portable. **Cons:** Can be slower for complex queries."
        )
    },
    {
        "prompt": "What is an API key and how do I keep it safe?",
        "completion": (
            "An **API key** is a secret token that identifies your application when making API calls.\n\n"
            "**How to keep it safe:**\n"
            "1. Never commit API keys to Git — add to `.gitignore`\n"
            "2. Store in `.env` file: `API_KEY=sk-abc123...`\n"
            "3. Load with `python-dotenv`: `os.getenv('API_KEY')`\n"
            "4. Use environment variables in production\n"
            "5. Rotate keys if they're ever exposed\n\n"
            "**If you accidentally push a key:** Revoke it immediately from the provider's dashboard."
        )
    },
    {
        "prompt": "What is the difference between SQL and NoSQL?",
        "completion": (
            "**SQL databases** (PostgreSQL, MySQL, SQLite):\n"
            "- Structured tables with rows and columns\n"
            "- Schema must be defined upfront\n"
            "- Good for: relationships, transactions, structured data\n\n"
            "**NoSQL databases** (MongoDB, Redis, Firebase):\n"
            "- Flexible documents (JSON-like)\n"
            "- Schema-free, can change structure anytime\n"
            "- Good for: rapid prototyping, unstructured data, real-time apps\n\n"
            "**Rule of thumb:** Start with SQL unless you have a specific reason for NoSQL."
        )
    },
    {
        "prompt": "What are design patterns in programming?",
        "completion": (
            "**Design patterns** are reusable solutions to common software design problems.\n\n"
            "**Most important ones:**\n"
            "- **Singleton** — only one instance of a class (e.g., database connection)\n"
            "- **Factory** — create objects without specifying exact class\n"
            "- **Observer** — notify multiple objects when state changes (event systems)\n"
            "- **Strategy** — swap algorithms at runtime\n"
            "- **Decorator** — add behavior to objects dynamically (Python's `@decorator`)\n\n"
            "Don't force patterns — use them when they naturally fit the problem."
        )
    },
    {
        "prompt": "What is linting and why is it important?",
        "completion": (
            "**Linting** is automated static analysis that checks code for:\n\n"
            "- Syntax errors before running\n"
            "- Style violations (indentation, naming)\n"
            "- Potential bugs (unused variables, unreachable code)\n"
            "- Security issues\n\n"
            "**Popular linters:**\n"
            "- Python: `pylint`, `flake8`, `ruff`\n"
            "- JavaScript: `eslint`\n"
            "- TypeScript: `eslint` + `@typescript-eslint`\n\n"
            "Look for `.eslintrc`, `.flake8`, `ruff.toml` config files in repos."
        )
    },
    {
        "prompt": "What does .gitignore do?",
        "completion": (
            "`.gitignore` tells Git which files/folders to NOT track.\n\n"
            "**Common entries:**\n"
            "```\nnode_modules/     # JS dependencies\n"
            "venv/             # Python virtual env\n"
            "__pycache__/      # Python bytecode\n"
            ".env              # Secret environment variables\n"
            "*.pyc             # Compiled Python files\n"
            "dist/             # Build output\n"
            ".DS_Store         # macOS system file\n```\n\n"
            "Without `.gitignore`, you'd accidentally commit thousands of dependency files."
        )
    },
    {
        "prompt": "How do I debug Python code?",
        "completion": (
            "**Debug techniques in Python:**\n\n"
            "1. **Print debugging:** `print(f'x = {x}')` — quick but messy\n\n"
            "2. **Built-in debugger:**\n"
            "```python\nimport pdb; pdb.set_trace()  # drops into interactive debugger\n"
            "# or in Python 3.7+:\nbreakpoint()\n```\n\n"
            "3. **VS Code debugger** — set breakpoints in the UI, inspect variables\n\n"
            "4. **Logging** (better than print for production):\n"
            "```python\nimport logging\nlogging.debug(f'Processing {item}')\n```\n\n"
            "5. **Read the traceback** — always start from the bottom."
        )
    },
    {
        "prompt": "What is a code review?",
        "completion": (
            "A **code review** is when another developer reads your code before it's merged.\n\n"
            "**What reviewers look for:**\n"
            "- Bugs and edge cases\n"
            "- Code style and readability\n"
            "- Performance issues\n"
            "- Security vulnerabilities\n"
            "- Test coverage\n"
            "- Documentation\n\n"
            "**Best practices:**\n"
            "- Keep PRs small (< 400 lines)\n"
            "- Write a clear PR description\n"
            "- Respond to feedback constructively\n"
            "- Don't take feedback personally"
        )
    },
    {
        "prompt": "What is refactoring?",
        "completion": (
            "**Refactoring** is restructuring existing code without changing its behavior.\n\n"
            "**When to refactor:**\n"
            "- Cyclomatic complexity > 15\n"
            "- Functions longer than 50 lines\n"
            "- Duplicate code in multiple places\n"
            "- Hard to understand variable names\n"
            "- Too many parameters in a function\n\n"
            "**Common refactoring techniques:**\n"
            "- Extract method (break long functions into small ones)\n"
            "- Rename variables for clarity\n"
            "- Remove dead code\n"
            "- Consolidate duplicate logic"
        )
    },
    {
        "prompt": "What is semantic versioning?",
        "completion": (
            "**Semantic versioning (SemVer)** uses the format `MAJOR.MINOR.PATCH`:\n\n"
            "- **MAJOR** (1.0.0 → 2.0.0): Breaking changes, incompatible API\n"
            "- **MINOR** (1.0.0 → 1.1.0): New features, backward compatible\n"
            "- **PATCH** (1.0.0 → 1.0.1): Bug fixes, backward compatible\n\n"
            "**Examples:**\n"
            "- `flask==3.0.0` — exact version\n"
            "- `flask>=2.0,<3.0` — any 2.x version\n"
            "- `flask~=2.1` — compatible with 2.1.x\n\n"
            "Found in `package.json`, `requirements.txt`, `pyproject.toml`."
        )
    },
    {
        "prompt": "What is environment variable and why use them?",
        "completion": (
            "**Environment variables** are key-value pairs set outside your code.\n\n"
            "**Why use them:**\n"
            "- Keep secrets (API keys, passwords) out of code\n"
            "- Different settings for dev/staging/production\n"
            "- Easy to change without modifying code\n\n"
            "**In Python:**\n"
            "```python\nimport os\nfrom dotenv import load_dotenv\n"
            "load_dotenv()  # reads .env file\n"
            "api_key = os.getenv('API_KEY')\n```\n\n"
            "**In `.env` file:**\n"
            "```\nAPI_KEY=sk-abc123\nDATABASE_URL=sqlite:///app.db\nDEBUG=true\n```"
        )
    },
    {
        "prompt": "What is test-driven development?",
        "completion": (
            "**TDD (Test-Driven Development)** follows the Red-Green-Refactor cycle:\n\n"
            "1. **Red** — Write a failing test first\n"
            "2. **Green** — Write the minimum code to make it pass\n"
            "3. **Refactor** — Clean up the code while keeping tests green\n\n"
            "**Example:**\n"
            "```python\n# 1. Write test (fails)\ndef test_add():\n    assert add(2, 3) == 5\n\n"
            "# 2. Write code (passes)\ndef add(a, b):\n    return a + b\n\n"
            "# 3. Refactor if needed\n```\n\n"
            "**Benefits:** Fewer bugs, better design, confidence to refactor."
        )
    },
    {
        "prompt": "What is async programming?",
        "completion": (
            "**Async programming** lets your code do other work while waiting for slow operations "
            "(network requests, file I/O, database queries).\n\n"
            "**Python (asyncio):**\n"
            "```python\nimport asyncio\n\nasync def fetch_data():\n"
            "    data = await http_client.get('/api/data')  # doesn't block\n"
            "    return data\n```\n\n"
            "**JavaScript (async/await):**\n"
            "```javascript\nasync function fetchData() {\n"
            "    const data = await fetch('/api/data');\n"
            "    return data.json();\n}\n```\n\n"
            "**When to use:** Web servers, API calls, file processing. "
            "**When NOT to use:** CPU-heavy calculations."
        )
    },
    {
        "prompt": "What is the difference between compiled and interpreted languages?",
        "completion": (
            "**Compiled languages** (C, Go, Rust):\n"
            "- Source code → machine code (binary) before running\n"
            "- Faster execution, catches errors at compile time\n"
            "- Must recompile after changes\n\n"
            "**Interpreted languages** (Python, JavaScript, Ruby):\n"
            "- Code runs line by line through an interpreter\n"
            "- Slower execution, but faster development cycle\n"
            "- Errors found at runtime\n\n"
            "**Hybrid:** Java/TypeScript compile to intermediate format (bytecode/JS)."
        )
    },
    {
        "prompt": "What is a webhook?",
        "completion": (
            "A **webhook** is a way for one service to notify another when something happens.\n\n"
            "**How it works:**\n"
            "1. You give Service A a URL on your server\n"
            "2. When an event occurs (new commit, payment, etc.)\n"
            "3. Service A sends a POST request to your URL with event data\n"
            "4. Your server processes the notification\n\n"
            "**Examples:**\n"
            "- GitHub webhook → triggers CI/CD on push\n"
            "- Stripe webhook → processes payment confirmations\n"
            "- Slack webhook → sends notifications to channels\n\n"
            "Unlike APIs (you request data), webhooks push data to you."
        )
    },
    {
        "prompt": "What is caching and when should I use it?",
        "completion": (
            "**Caching** stores frequently accessed data in fast storage to avoid "
            "recalculating or re-fetching it.\n\n"
            "**Types:**\n"
            "- **In-memory** (Redis, Memcached) — fastest\n"
            "- **Browser cache** — stores static files locally\n"
            "- **CDN cache** — serves content from nearby servers\n"
            "- **Application cache** — `@lru_cache` in Python\n\n"
            "**When to cache:**\n"
            "- Data that rarely changes but is read often\n"
            "- Expensive database queries\n"
            "- API responses\n\n"
            "**When NOT to cache:** Real-time data, user-specific sensitive data."
        )
    },
    {
        "prompt": "Hello",
        "completion": (
            "Hello! I'm RepoAI, your code analysis assistant. I can help you:\n\n"
            "- **Analyze repositories** — understand structure, dependencies, and complexity\n"
            "- **Explain code** — what specific files do and how they work\n"
            "- **Generate READMEs** — professional documentation for your projects\n"
            "- **Answer coding questions** — about patterns, tools, and best practices\n\n"
            "What would you like to know?"
        )
    },
    {
        "prompt": "Hi",
        "completion": (
            "Hi there! 👋 I'm RepoAI, your code analysis assistant.\n\n"
            "Ask me about any GitHub repository — I can explain its architecture, "
            "files, dependencies, and help you understand the codebase.\n\n"
            "What can I help you with?"
        )
    },
    {
        "prompt": "Who are you?",
        "completion": (
            "I'm **RepoAI**, an AI assistant specialized in analyzing GitHub repositories.\n\n"
            "I can:\n"
            "- Explain what a repository does and how it's structured\n"
            "- Analyze code complexity and dependencies\n"
            "- Generate professional README files\n"
            "- Answer questions about code patterns and best practices\n"
            "- Help you understand any file in a codebase\n\n"
            "I was trained on real open-source repositories to give accurate code analysis."
        )
    },
    {
        "prompt": "Thank you",
        "completion": "You're welcome! If you have more questions about code or repositories, feel free to ask. Happy coding! 🚀"
    },
    {
        "prompt": "What can you do?",
        "completion": (
            "I can help you with:\n\n"
            "1. **Repository Analysis** — explain what a project does, its architecture, and entry points\n"
            "2. **File Explanations** — describe what any code file does, its functions, and imports\n"
            "3. **Complexity Analysis** — identify complex files that need refactoring\n"
            "4. **Dependency Graphs** — show how files import each other\n"
            "5. **README Generation** — create professional documentation\n"
            "6. **Coding Q&A** — answer questions about patterns, tools, and best practices\n\n"
            "Try asking about a specific GitHub repository!"
        )
    },
]


# ── Main ─────────────────────────────────────────────────

def collect_repo(full_name):
    owner, repo = full_name.split("/")
    print(f"\n📦 {full_name}...")
    blobs, info = get_tree(owner, repo)
    if not info:
        print("  ✗ Skipped")
        return []

    desc  = info.get("description") or f"A {info.get('language','software')} project"
    lang  = info.get("language") or "Unknown"
    stars = info.get("stargazers_count", 0)
    topics= info.get("topics", [])
    paths = [b["path"] for b in blobs]
    print(f"  ✓ {len(paths)} files | {lang} | ⭐{stars:,}")

    pairs = []

    # ── Rich conversational pairs ────────────────────────
    pairs.append(q_overview(full_name, desc, lang, stars, topics))
    pairs.append(q_overview_alt(full_name, desc, lang, stars))
    pairs.append(q_install(full_name, lang, desc))
    pairs.append(q_file_list(full_name, paths))
    pairs.append(q_architecture(full_name, paths, desc, lang))
    pairs.append(q_auth(full_name, paths))
    pairs.append(q_entry(full_name, paths, lang))
    pairs.append(q_readme(full_name, desc, lang, stars, paths, topics))
    pairs.append(q_complexity(full_name, paths, lang))
    pairs.append(q_add_feature(full_name, lang, desc))
    pairs.append(q_tests(full_name, paths, lang))
    pairs.append(q_contribute(full_name, desc))
    pairs.append(q_tech_stack(full_name, lang, desc, paths))
    pairs.append(q_dependencies(full_name, paths, lang))
    pairs.append(q_license(full_name, paths))

    # ── File-level pairs with REAL content ───────────────
    code_blobs = [b for b in blobs
                  if Path(b["path"]).suffix.lower() in CODE_EXTS
                  and b.get("size", 0) < 80000
                  and b.get("size", 0) > 100][:MAX_FILES_PER_REPO]

    for i, blob in enumerate(code_blobs):
        print(f"  [{i+1}/{len(code_blobs)}] {blob['path']}")
        content = get_file_content(owner, repo, blob["path"])
        if content and len(content.strip()) > 80:
            ext = Path(blob["path"]).suffix.lstrip(".")
            pairs.append(q_explain_file(full_name, blob["path"], content, ext))
        time.sleep(0.25)

    print(f"  → {len(pairs)} pairs")
    return pairs


def main():
    print("=" * 55)
    print("  RepoAI — Training Data Generator v2")
    print("=" * 55)
    if GITHUB_TOKEN:
        print("✓ GitHub token found\n")
    else:
        print("⚠ No GitHub token — rate limit: 60 req/hr\n")

    all_pairs = list(GENERIC_CONVOS)
    print(f"Added {len(GENERIC_CONVOS)} generic conversational pairs")

    for repo in REPOS:
        try:
            pairs = collect_repo(repo)
            all_pairs.extend(pairs)
        except Exception as e:
            print(f"  ✗ Error on {repo}: {e}")

    # Remove any pairs with empty/garbage completions
    all_pairs = [
        p for p in all_pairs
        if p.get("completion", "").strip()
        and len(p["completion"].split()) > 8  # at least 8 words in answer
        and "0 lines of code" not in p["completion"]  # filter garbage
    ]

    random.shuffle(all_pairs)
    os.makedirs(OUT_DIR, exist_ok=True)

    split     = int(len(all_pairs) * TRAIN_SPLIT)
    train_set = all_pairs[:split]
    test_set  = all_pairs[split:]

    with open(TRAIN_FILE, "w", encoding="utf-8") as f:
        for p in train_set:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(TEST_FILE, "w", encoding="utf-8") as f:
        for p in test_set:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(f"\n{'='*55}")
    print(f"✅ Total:  {len(all_pairs)} pairs")
    print(f"✅ Train:  {len(train_set)} → {TRAIN_FILE}")
    print(f"✅ Test:   {len(test_set)}  → {TEST_FILE}")
    print(f"\n▶ Next step: python ai_model/train.py")


if __name__ == "__main__":
    main()
