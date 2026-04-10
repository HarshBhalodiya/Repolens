"""
smells.py — Code Smell Detection for RepoLens

Detects common code smells:
  1. Long functions (> 50 lines)
  2. High cyclomatic complexity (grade D or F, score > 10)
  3. Circular dependencies (from the existing dependency graph)
  4. Unused imports (files imported but never referenced elsewhere)
"""

import re
import ast
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────
# Smell severity levels
# ─────────────────────────────────────────

SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


# ─────────────────────────────────────────
# 1. Long functions (> 50 lines)
# ─────────────────────────────────────────

def detect_long_functions(files: list[dict], threshold: int = 50) -> list[dict]:
    """Find functions longer than `threshold` lines."""
    smells = []

    for f in files:
        content = f.get("content", "")
        lang = f.get("lang", "")
        path = f.get("path", f.get("name", "?"))

        if not content:
            continue

        if lang == "python":
            long_fns = _find_long_python_functions(content, threshold)
        elif lang in ("javascript", "typescript"):
            long_fns = _find_long_js_functions(content, threshold)
        else:
            continue

        for fn_name, line_count, start_line in long_fns:
            severity = SEVERITY_CRITICAL if line_count > threshold * 2 else SEVERITY_WARNING
            smells.append({
                "type": "long_function",
                "file": path,
                "function": fn_name,
                "line": start_line,
                "value": line_count,
                "threshold": threshold,
                "severity": severity,
                "description": f"Function `{fn_name}()` is {line_count} lines long (threshold: {threshold})",
            })

    return smells


def _find_long_python_functions(content: str, threshold: int) -> list[tuple]:
    """Find Python functions exceeding line threshold."""
    results = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return results

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Calculate function length from first to last line
            start = node.lineno
            end = node.end_lineno or start
            length = end - start + 1
            if length > threshold:
                results.append((node.name, length, start))

    return results


def _find_long_js_functions(content: str, threshold: int) -> list[tuple]:
    """Find JS/TS functions exceeding line threshold (rough heuristic)."""
    results = []
    lines = content.splitlines()

    # Match function declarations and arrow functions
    func_pattern = re.compile(
        r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\s*)?\()"
    )

    for match in func_pattern.finditer(content):
        name = match.group(1) or match.group(2) or "anonymous"
        start_pos = match.start()
        start_line = content[:start_pos].count("\n") + 1

        # Find opening brace
        brace_pos = content.find("{", match.end())
        if brace_pos == -1:
            continue

        # Count lines until matching closing brace
        depth = 0
        i = brace_pos
        while i < len(content):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    end_line = content[:i].count("\n") + 1
                    length = end_line - start_line + 1
                    if length > threshold:
                        results.append((name, length, start_line))
                    break
            i += 1

    return results


# ─────────────────────────────────────────
# 2. High complexity files (grade D or F)
# ─────────────────────────────────────────

def detect_high_complexity(complexity_data: list[dict], threshold: int = 10) -> list[dict]:
    """Flag files with cyclomatic complexity score above threshold."""
    smells = []

    for entry in complexity_data:
        score = entry.get("complexity", 0)
        grade = entry.get("grade", "A")

        if score > threshold or grade in ("D", "E", "F"):
            severity = SEVERITY_CRITICAL if grade in ("E", "F") else SEVERITY_WARNING
            smells.append({
                "type": "high_complexity",
                "file": entry.get("path", entry.get("file", "?")),
                "value": score,
                "grade": grade,
                "threshold": threshold,
                "severity": severity,
                "description": f"Cyclomatic complexity {score} (grade {grade}) exceeds threshold {threshold}",
            })

    return smells


# ─────────────────────────────────────────
# 3. Circular dependencies
# ─────────────────────────────────────────

def detect_circular_deps(graph_data: dict) -> list[dict]:
    """Extract circular dependency smells from graph metrics."""
    smells = []
    metrics = graph_data.get("metrics", {})
    cycle_nodes = metrics.get("cycle_nodes", [])
    cycles_count = metrics.get("cycles_detected", 0)

    if cycles_count > 0:
        # Group cycle nodes for reporting
        smells.append({
            "type": "circular_dependency",
            "file": ", ".join(cycle_nodes[:5]) + ("…" if len(cycle_nodes) > 5 else ""),
            "value": cycles_count,
            "severity": SEVERITY_CRITICAL,
            "description": f"{cycles_count} circular dependency cycle(s) detected involving {len(cycle_nodes)} files",
            "affected_files": cycle_nodes,
        })

        # Also add per-file entries for inline display
        for node in cycle_nodes:
            smells.append({
                "type": "circular_dependency",
                "file": node,
                "value": 1,
                "severity": SEVERITY_WARNING,
                "description": f"File is part of a circular dependency chain",
            })

    return smells


# ─────────────────────────────────────────
# 4. Unused imports (imported but never referenced)
# ─────────────────────────────────────────

def detect_unused_imports(files: list[dict], deps: list[dict]) -> list[dict]:
    """
    Find files that are imported by others but never import anything themselves,
    AND files that import modules not used elsewhere in the codebase.
    """
    smells = []

    # Build sets of what imports what
    imported_by = {}  # target -> set of sources
    imports_from = {}  # source -> set of targets

    for dep in deps:
        src = dep.get("source", "")
        tgt = dep.get("target", "")
        imported_by.setdefault(tgt, set()).add(src)
        imports_from.setdefault(src, set()).add(tgt)

    all_filenames = {f.get("name", "") for f in files}

    # Find files that import things not in the repo (potential unused imports)
    for f in files:
        content = f.get("content", "")
        lang = f.get("lang", "")
        name = f.get("name", "")
        path = f.get("path", name)

        if not content or lang not in ("python",):
            continue

        # For Python: find imports that don't match any repo file
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue

        local_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local_imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    local_imports.add(node.module.split(".")[0])

        # Check if any imported name is actually used in the file body
        for imp_name in local_imports:
            # Check if the import is used anywhere in the file (after the import line)
            usage_pattern = re.compile(r"\b" + re.escape(imp_name) + r"\b")
            # Remove import lines to check usage in actual code
            code_lines = []
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped.startswith("import ") and not stripped.startswith("from "):
                    code_lines.append(line)
            code_body = "\n".join(code_lines)

            if not usage_pattern.search(code_body):
                smells.append({
                    "type": "unused_import",
                    "file": path,
                    "value": imp_name,
                    "severity": SEVERITY_WARNING,
                    "description": f"Import `{imp_name}` appears unused in `{name}`",
                })

    return smells


# ─────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────

def detect_all_smells(
    files: list[dict],
    complexity_data: list[dict],
    graph_data: dict,
    deps: list[dict],
) -> list[dict]:
    """
    Run all smell detectors and return combined results.
    Each smell dict has: type, file, severity, description, value
    """
    all_smells = []

    # 1. Long functions
    all_smells.extend(detect_long_functions(files))

    # 2. High complexity
    all_smells.extend(detect_high_complexity(complexity_data))

    # 3. Circular deps
    all_smells.extend(detect_circular_deps(graph_data))

    # 4. Unused imports
    all_smells.extend(detect_unused_imports(files, deps))

    # Sort: critical first, then by file
    severity_order = {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 1}
    all_smells.sort(key=lambda s: (severity_order.get(s["severity"], 2), s["file"]))

    return all_smells
