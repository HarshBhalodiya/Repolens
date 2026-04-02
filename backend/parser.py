"""
parser.py
Parses import/require statements from source files to build dependency relationships.
- Python: uses the built-in `ast` module for accurate parsing
- JavaScript/TypeScript: uses regex patterns
- Other languages: simple regex fallbacks
"""

import ast
import re
from pathlib import Path


# ─────────────────────────────────────────
# Python Parser (ast-based)
# ─────────────────────────────────────────

def parse_python_imports(content: str, file_path: str) -> list[str]:
    """Extract local imports from a Python file using AST."""
    imports = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    file_dir = str(Path(file_path).parent)

    for node in ast.walk(tree):
        # import foo, bar
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])

        # from .foo import bar  /  from foo import bar
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
            # relative imports: from . import utils
            elif node.level > 0:
                for alias in node.names:
                    imports.append(alias.name)

    return imports


# ─────────────────────────────────────────
# JavaScript / TypeScript Parser (regex)
# ─────────────────────────────────────────

JS_IMPORT_PATTERNS = [
    # import x from './path'
    r"""import\s+(?:[\w*{},\s]+)\s+from\s+['"]([^'"]+)['"]""",
    # const x = require('./path')
    r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    # import('./path')
    r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""",
    # export { x } from './path'
    r"""export\s+(?:[\w*{},\s]+)\s+from\s+['"]([^'"]+)['"]""",
]

def parse_js_imports(content: str) -> list[str]:
    """Extract local import paths from JS/TS files."""
    imports = []
    for pattern in JS_IMPORT_PATTERNS:
        for match in re.finditer(pattern, content, re.MULTILINE):
            path = match.group(1)
            # Only local imports (start with . or /)
            if path.startswith(".") or path.startswith("/"):
                # Normalize: strip leading ./, ../
                name = Path(path).name
                # Strip extension if present
                name = re.sub(r"\.(js|ts|jsx|tsx|mjs)$", "", name)
                if name and name != "index":
                    imports.append(name)
    return imports


# ─────────────────────────────────────────
# Generic fallback (Java, Go, Rust, etc.)
# ─────────────────────────────────────────

GENERIC_PATTERNS = {
    "java": r"""import\s+([\w.]+);""",
    "go": r"""["']([\w./]+)["']""",
    "rust": r"""(?:use|extern crate)\s+([\w:]+)""",
    "cpp": r"""#include\s+["<]([\w./]+)[">]""",
    "ruby": r"""require(?:_relative)?\s+['"]([^'"]+)['"]""",
    "php": r"""(?:require|include)(?:_once)?\s+['"]([^'"]+)['"]""",
}

def parse_generic_imports(content: str, lang: str) -> list[str]:
    pattern = GENERIC_PATTERNS.get(lang)
    if not pattern:
        return []
    imports = []
    for match in re.finditer(pattern, content, re.MULTILINE):
        raw = match.group(1)
        name = Path(raw).stem
        imports.append(name)
    return imports


# ─────────────────────────────────────────
# Count functions (per language)
# ─────────────────────────────────────────

def count_functions(content: str, lang: str) -> int:
    if lang == "python":
        try:
            tree = ast.parse(content)
            return sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        except:
            pass

    patterns = {
        "javascript": r"\bfunction\s+\w+|\w+\s*=\s*(?:async\s+)?\(",
        "typescript": r"\bfunction\s+\w+|\w+\s*[=:]\s*(?:async\s+)?\(",
        "java": r"(?:public|private|protected|static|final|void|int|String|boolean)\s+\w+\s*\(",
        "go": r"\bfunc\s+\w+",
        "rust": r"\bfn\s+\w+",
        "ruby": r"\bdef\s+\w+",
        "cpp": r"\w+\s+\w+\s*\([^)]*\)\s*\{",
        "csharp": r"(?:public|private|protected|static|void|int|string|bool|Task)\s+\w+\s*\(",
    }
    pattern = patterns.get(lang)
    if pattern:
        return len(re.findall(pattern, content))
    return 0


# ─────────────────────────────────────────
# Main: parse all files
# ─────────────────────────────────────────

def parse_imports(files: list[dict]) -> list[dict]:
    """
    For each file, parse its imports and find which other files it depends on.
    Returns list of { source, target } edges.
    """
    # Build a lookup: import key -> possible file targets
    file_lookup = {}
    for f in files:
        stem = Path(f["name"]).stem.lower()
        file_lookup.setdefault(stem, set()).add(f["name"])
        # Also index by full name
        file_lookup.setdefault(f["name"].lower(), set()).add(f["name"])

    edges = []
    seen_edges = set()

    for f in files:
        content = f.get("content", "")
        lang = f.get("lang", "")
        name = f["name"]

        # Count functions (store back into file dict)
        f["functions"] = count_functions(content, lang)

        # Parse imports
        if lang == "python":
            raw_imports = parse_python_imports(content, f.get("path", name))
        elif lang in ("javascript", "typescript"):
            raw_imports = parse_js_imports(content)
        else:
            raw_imports = parse_generic_imports(content, lang)

        # Match raw imports to actual files in repo
        for imp in raw_imports:
            imp_lower = imp.lower()
            targets = (
                file_lookup.get(imp_lower)
                or file_lookup.get(imp_lower + ".py")
                or file_lookup.get(imp_lower + ".js")
                or file_lookup.get(imp_lower + ".ts")
                or set()
            )

            for target in targets:
                if target and target != name:
                    edge_key = (name, target)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        edges.append({"source": name, "target": target})

    return edges
