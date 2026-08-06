"""
RepoLens - Tree-sitter Dependency Graph Engine

Builds a file-level dependency knowledge graph for a repository by
parsing each supported source file with Tree-sitter, extracting
import/require statements, and resolving those references to internal
file paths.

Supported languages:
    - Python     (.py)          import x / from x import y
    - JavaScript (.js, .jsx)    import ... from 'y' / require('y')
    - TypeScript (.ts, .tsx)    import ... from 'y' / require('y')

Optional runtime dependency (only needed for /api/dependencies):

    pip install tree-sitter tree-sitter-python tree-sitter-javascript \
        tree-sitter-typescript

Tree-sitter grammars are imported lazily so the rest of RepoLens keeps
working when the packages are not installed, matching the convention used
by ai_engine.py and rag_indexer.py.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories never walked into (kept in sync with rag_indexer.py).
IGNORED_DIRS = {".git", "node_modules", "venv", "__pycache__", "dist", "build"}

# File extensions analyzed for import statements.
SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx"}

# Files larger than this are skipped (vendored bundles, generated output).
MAX_FILE_BYTES = 1_000_000

# Extension candidates tried when a JS/TS relative import omits its suffix.
_JS_EXTENSIONS = (".js", ".ts", ".jsx", ".tsx")


def _load_parsers() -> dict:
    """
    Lazily build {extension: Parser} from the installed Tree-sitter grammars.

    Raises:
        ImportError: When tree-sitter or any grammar package is missing.
    """
    from tree_sitter import Language, Parser
    import tree_sitter_javascript
    import tree_sitter_python
    import tree_sitter_typescript

    # Modern grammar packages expose `language()` as a PyCapsule that must
    # be wrapped in tree_sitter.Language before use (API changed in the
    # 0.25+ era; Parser() rejects raw capsules).
    return {
        ".py": Parser(Language(tree_sitter_python.language())),
        ".js": Parser(Language(tree_sitter_javascript.language())),
        ".jsx": Parser(Language(tree_sitter_javascript.language())),
        ".ts": Parser(Language(tree_sitter_typescript.language_typescript())),
        ".tsx": Parser(Language(tree_sitter_typescript.language_tsx())),
    }


def _iter_nodes(node):
    """Iterative depth-first walk over `node` and all of its descendants."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)


def _collect_source_files(repo_path: str) -> list:
    """Return absolute paths of supported source files under `repo_path`."""
    files = []
    for root, dirs, names in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for name in names:
            if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            full_path = os.path.join(root, name)
            try:
                if os.path.getsize(full_path) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(full_path)
    return files


def _extract_python_imports(root_node) -> list:
    """
    Return module references from Python import statements.

    Relative imports keep their leading dots (e.g. `..pkg.mod`) so the
    resolver knows how many package levels to climb. Imports nested inside
    function bodies are found too (lazy imports are common), but we never
    descend into an import node itself to avoid re-reading its parts.
    """
    imports = []
    stack = [root_node]
    while stack:
        node = stack.pop()
        if node.type in ("import_statement", "import_from_statement"):
            imports.extend(_python_import_from_statement(node))
            continue  # skip descending into the import subtree
        stack.extend(node.children)
    return imports


def _python_import_from_statement(node) -> list:
    """Extract module names from one Python import statement node."""
    if node.type == "import_statement":
        # `import os`, `import a.b`, `import x as y`, `import a, b`
        refs = []
        for child in node.children:
            if child.type == "dotted_name":
                refs.append(child.text.decode("utf-8"))
            elif child.type == "aliased_import":
                for sub in child.children:
                    if sub.type == "dotted_name":
                        refs.append(sub.text.decode("utf-8"))
                        break
        return refs

    # import_from_statement: `from a.b import x` / `from .c import y`
    module = None
    for child in node.children:
        if child.type == "relative_import":
            rel_text = child.text.decode("utf-8")
            # Root cause note: tree-sitter-python >= 0.23 folds the module
            # name into relative_import (e.g. `.helpers`, `..utils`), while
            # older grammars kept dots only with a separate dotted_name
            # child. Handle both: if the text contains a name, it is the
            # full reference; if it is dots only (`from . import x`), keep
            # it as the package reference.
            if rel_text.rstrip("."):
                return [rel_text]
            module = rel_text
        elif child.type == "dotted_name" and module is None:
            module = child.text.decode("utf-8")
    if module is not None:
        return [module]
    return []


def _extract_js_imports(root_node) -> list:
    """
    Return module specifiers from JS/TS import/require/export statements.

    Handles `import ... from 'spec'`, `import 'spec'` (side-effect import),
    `require('spec')` calls, and `export ... from 'spec'` re-exports.
    """
    specifiers = []
    for node in _iter_nodes(root_node):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "string":
                    specifiers.append(child.text.decode("utf-8").strip("'\""))
        elif node.type == "call_expression":
            text = node.text.decode("utf-8").lstrip()
            if text.startswith("require("):
                for sub in _iter_nodes(node):
                    if sub.type == "string":
                        specifiers.append(sub.text.decode("utf-8").strip("'\""))
                        break
        elif node.type == "export_statement":
            source = node.child_by_field_name("source")
            if source is not None and source.type == "string":
                specifiers.append(source.text.decode("utf-8").strip("'\""))
    return specifiers


def _as_rel(path, repo_root: str) -> str:
    """Return a repo-relative, forward-slash path string."""
    return os.path.relpath(str(path), repo_root).replace(os.sep, "/")


def _resolve_python_candidate(candidate: Path):
    """Return the module file path for `candidate`, or None."""
    py = candidate.with_suffix(".py")
    if py.is_file():
        return py
    init = candidate / "__init__.py"
    if init.is_file():
        return init
    return None


def _resolve_python_import(
    importing_file: str, module: str, repo_root: str, known_files: set
):
    """
    Resolve a Python module reference to a repo-relative path, or None.

    Relative references (`./x`, `../y`) climb the package tree; absolute
    ones are tried as `<root>/<module>` first and fall back to the
    importer's directory (for flat scripts that rely on cwd/sys.path).
    Only files already collected in this repo produce edges — anything
    else (stdlib, site-packages) resolves to None and is ignored.
    """
    base = Path(importing_file).parent
    if module.startswith("."):
        depth = len(module) - len(module.lstrip("."))
        parts = module.lstrip(".").split(".")
        # depth 1 = this package dir; each extra dot climbs one level up.
        for _ in range(depth - 1):
            base = base.parent
        candidates = [Path(base, *parts)] if parts != [""] else [base]
    else:
        parts = module.split(".")
        candidates = [Path(repo_root, *parts), Path(base, *parts)]

    for candidate in candidates:
        target = _resolve_python_candidate(candidate)
        if target:
            rel = _as_rel(target, repo_root)
            if rel in known_files:
                return rel
    return None


def _resolve_js_import(
    importing_file: str, specifier: str, repo_root: str, known_files: set
):
    """
    Resolve a JS/TS import specifier to a repo-relative path, or None.

    Bare specifiers (`react`, `lodash`) point at node_modules/external
    packages and never produce internal edges. Relative specifiers are
    resolved against the importing file's directory, trying each of the
    supported extensions plus `/index.<ext>` for directory imports.
    """
    if not specifier.startswith("."):
        return None  # external package import
    base = Path(importing_file).parent
    target = Path(os.path.normpath(base / specifier))

    candidates = []
    if target.suffix and target.suffix.lower() in _JS_EXTENSIONS:
        candidates.append(target)
    else:
        for ext in _JS_EXTENSIONS:
            candidates.append(target.with_suffix(ext))
        for ext in _JS_EXTENSIONS:
            candidates.append(target / f"index{ext}")

    for candidate in candidates:
        candidate = Path(os.path.normpath(candidate))
        try:
            candidate.relative_to(Path(repo_root))
        except ValueError:
            continue  # escaped the repo → not an internal dependency
        if candidate.is_file():
            rel = _as_rel(candidate, repo_root)
            if rel in known_files:
                return rel
    return None


def build_dependency_graph(repo_path: str) -> dict:
    """
    Build a file-level dependency graph for a repository.

    Args:
        repo_path (str): Path to the repository to analyze

    Returns:
        dict: {"nodes": [{"id", "label"}], "edges": [{"source", "target"}],
        "status": "completed"} on success. On failure an error payload with
        "status": "error" and "message", plus empty nodes/edges lists.
    """
    if not os.path.isdir(repo_path):
        return {
            "status": "error",
            "message": "Repository path does not exist or is not a directory.",
            "nodes": [],
            "edges": [],
        }

    try:
        parsers = _load_parsers()
    except ImportError:
        return {
            "status": "error",
            "message": (
                "Tree-sitter packages are not installed. Run: pip install "
                "tree-sitter tree-sitter-python tree-sitter-javascript "
                "tree-sitter-typescript"
            ),
            "nodes": [],
            "edges": [],
        }

    files = _collect_source_files(repo_path)
    if not files:
        return {
            "status": "completed",
            "message": "No supported source files found.",
            "nodes": [],
            "edges": [],
        }

    known_files = {
        os.path.relpath(f, repo_path).replace(os.sep, "/") for f in files
    }
    parsed_files = []
    edges = set()

    for full_path in files:
        ext = Path(full_path).suffix.lower()
        rel = os.path.relpath(full_path, repo_path).replace(os.sep, "/")
        try:
            with open(full_path, "r", encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        if "\x00" in text or not text.strip():
            continue  # binary or empty — nothing to parse

        try:
            tree = parsers[ext].parse(text.encode("utf-8"))
        except Exception as e:  # parser-level failures: skip the file
            logger.debug("Tree-sitter parse failed for %s: %s", rel, e)
            continue

        if tree.root_node.has_error:
            # Syntax errors produce partial/ERROR subtrees; skip the file
            # rather than emit a misleading graph for broken code.
            logger.debug("Skipping %s: syntax error(s) in file", rel)
            continue
        parsed_files.append(rel)

        try:
            if ext == ".py":
                imports = _extract_python_imports(tree.root_node)
            else:
                imports = _extract_js_imports(tree.root_node)
        except Exception as e:
            logger.debug("Import extraction failed for %s: %s", rel, e)
            continue

        for module in imports:
            if ext == ".py":
                target = _resolve_python_import(
                    full_path, module, repo_path, known_files
                )
            else:
                target = _resolve_js_import(
                    full_path, module, repo_path, known_files
                )
            if target and target != rel:
                edges.add((rel, target))

    nodes = [
        {"id": file_path, "label": Path(file_path).name}
        for file_path in sorted(parsed_files)
    ]
    edge_list = [
        {"source": source, "target": target} for source, target in sorted(edges)
    ]
    return {"nodes": nodes, "edges": edge_list, "status": "completed"}
