"""
complexity.py
Calculates cyclomatic complexity per file.
- Python: uses Radon (pip install radon)
- JS/TS: custom cyclomatic complexity via AST-like regex counting
- Others: simplified metric based on decision points
"""

import re
from pathlib import Path


# ─────────────────────────────────────────
# Python: Radon
# ─────────────────────────────────────────

def analyze_python_complexity(content: str) -> dict:
    """Use radon to calculate cyclomatic complexity for Python files."""
    try:
        from radon.complexity import cc_visit
        from radon.metrics import mi_visit, h_visit

        blocks = cc_visit(content)
        if not blocks:
            return {"score": 1, "grade": "A", "functions": []}

        scores = [b.complexity for b in blocks]
        avg = sum(scores) / len(scores)
        max_score = max(scores)

        # Maintainability Index (0-100, higher is better)
        try:
            mi = mi_visit(content, multi=True)
            mi_score = round(mi, 1)
        except Exception:
            mi_score = None

        # Halstead metrics
        try:
            h = h_visit(content)
            if h and h[0].volume is not None and h[0].difficulty is not None and h[0].effort is not None:
                halstead = {
                    "volume": round(h[0].volume, 1),
                    "difficulty": round(h[0].difficulty, 1),
                    "effort": round(h[0].effort, 1),
                }
            else:
                halstead = None
        except Exception:
            halstead = None

        functions = [
            {
                "name": b.name,
                "complexity": b.complexity,
                "grade": get_grade(b.complexity),
                "line": b.lineno,
            }
            for b in sorted(blocks, key=lambda x: x.complexity, reverse=True)
        ]

        return {
            "score": round(avg, 1),
            "max_score": max_score,
            "grade": get_grade(max_score),
            "maintainability_index": mi_score,
            "halstead": halstead,
            "functions": functions[:10],  # top 10 most complex
        }

    except ImportError:
        # Radon not installed, fall back to simple counting
        return analyze_simple_complexity(content, "python")
    except Exception as e:
        return {"score": 1, "grade": "A", "functions": [], "error": str(e)}


# ─────────────────────────────────────────
# JavaScript/TypeScript: Manual CC
# ─────────────────────────────────────────

# Each of these adds 1 to cyclomatic complexity
JS_DECISION_POINTS = [
    r"\bif\s*\(",
    r"\belse\s+if\s*\(",
    r"\bwhile\s*\(",
    r"\bfor\s*\(",
    r"\bfor\s+\w+\s+of\b",
    r"\bfor\s+\w+\s+in\b",
    r"\bcase\s+.+:",
    r"\bcatch\s*\(",
    r"\b\?\s",        # ternary
    r"&&",
    r"\|\|",
    r"\?\?",          # nullish coalescing
]

def analyze_js_complexity(content: str) -> dict:
    """Calculate complexity for JS/TS files by counting decision points."""
    # Count per-function complexity
    # Simple approach: count decision points globally
    total_decision_points = 1  # base complexity
    for pattern in JS_DECISION_POINTS:
        matches = re.findall(pattern, content)
        total_decision_points += len(matches)

    # Rough estimate: distribute across functions
    func_pattern = r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\())"
    funcs = re.findall(func_pattern, content)
    func_count = len(funcs)

    avg = total_decision_points / max(func_count, 1)
    avg = min(avg, total_decision_points)  # cap

    # Try to find per-function complexities by splitting
    function_blocks = split_js_functions(content)
    function_complexities = []
    for fname, block in function_blocks[:10]:
        fc = 1
        for pattern in JS_DECISION_POINTS:
            fc += len(re.findall(pattern, block))
        function_complexities.append({
            "name": fname,
            "complexity": fc,
            "grade": get_grade(fc),
        })

    function_complexities.sort(key=lambda x: x["complexity"], reverse=True)

    return {
        "score": round(avg, 1),
        "max_score": max((f["complexity"] for f in function_complexities), default=total_decision_points),
        "grade": get_grade(total_decision_points // max(func_count, 1)),
        "total_decision_points": total_decision_points,
        "functions": function_complexities,
    }


def split_js_functions(content: str) -> list[tuple[str, str]]:
    """Very rough JS function splitter for complexity estimation."""
    results = []
    pattern = re.compile(
        r"(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function\s*)?)\s*\("
    )
    for match in pattern.finditer(content):
        name = match.group(1) or match.group(2) or "anonymous"
        start = match.start()
        # Find the function body (naive brace counting)
        depth = 0
        i = start
        body_start = content.find("{", start)
        if body_start == -1:
            continue
        i = body_start
        while i < len(content):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    results.append((name, content[body_start:i+1]))
                    break
            i += 1
    return results


# ─────────────────────────────────────────
# Generic (Java, Go, Rust, etc.)
# ─────────────────────────────────────────

GENERIC_DECISION_POINTS = [
    r"\bif\s*\(",
    r"\belse\s+if\s*\(",
    r"\bwhile\s*\(",
    r"\bfor\s*\(",
    r"\bswitch\s*\(",
    r"\bcase\s+",
    r"\bcatch\s*\(",
    r"&&", r"\|\|",
]

def analyze_simple_complexity(content: str, lang: str) -> dict:
    """Simple complexity for unsupported languages."""
    score = 1
    for pattern in GENERIC_DECISION_POINTS:
        score += len(re.findall(pattern, content))

    lines = content.splitlines()
    # Rough function count
    if lang == "go":
        func_count = len(re.findall(r"\bfunc\s+\w+", content))
    elif lang == "rust":
        func_count = len(re.findall(r"\bfn\s+\w+", content))
    elif lang == "java":
        func_count = len(re.findall(r"(?:public|private|protected)\s+\w+\s+\w+\s*\(", content))
    else:
        func_count = max(1, score // 5)

    avg = score / max(func_count, 1)

    return {
        "score": round(min(avg, score), 1),
        "max_score": score,
        "grade": get_grade(int(avg)),
        "functions": [],
    }


# ─────────────────────────────────────────
# Grade system
# ─────────────────────────────────────────

def get_grade(score: float) -> str:
    if score <= 5:   return "A"
    if score <= 10:  return "B"
    if score <= 15:  return "C"
    if score <= 20:  return "D"
    if score <= 30:  return "E"
    return "F"


def get_grade_label(grade: str) -> str:
    return {
        "A": "Low", "B": "Low",
        "C": "Medium", "D": "Medium",
        "E": "High", "F": "Critical"
    }.get(grade, "Unknown")


def get_grade_color(grade: str) -> str:
    return {
        "A": "green", "B": "green",
        "C": "yellow", "D": "orange",
        "E": "red", "F": "red"
    }.get(grade, "gray")


# ─────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────

def analyze_complexity(files: list[dict]) -> list[dict]:
    """
    Analyze complexity for all files.
    Stores `complexity` score back into each file dict (for other modules to use).
    Returns sorted list of complexity results.
    """
    results = []

    for f in files:
        content = f.get("content", "")
        lang = f.get("lang", "")
        path = f.get("path", f["name"])

        if not content or not lang:
            continue

        if lang == "python":
            metrics = analyze_python_complexity(content)
        elif lang in ("javascript", "typescript"):
            metrics = analyze_js_complexity(content)
        else:
            metrics = analyze_simple_complexity(content, lang)

        score = metrics.get("score", 1)
        grade = metrics.get("grade", "A")

        # Store back into file dict for dependency_graph and chat_engine
        f["complexity"] = int(score)

        results.append({
            "file": f["name"],
            "path": path,
            "lang": lang,
            "lines": f.get("lines", 0),
            "functions": f.get("functions", 0),
            "complexity": round(score, 1),
            "max_complexity": metrics.get("max_score", score),
            "grade": grade,
            "grade_label": get_grade_label(grade),
            "grade_color": get_grade_color(grade),
            "maintainability_index": metrics.get("maintainability_index"),
            "halstead": metrics.get("halstead"),
            "top_functions": metrics.get("functions", []),
        })

    # Sort: most complex first
    results.sort(key=lambda x: x["complexity"], reverse=True)
    return results
