"""
insights.py — Advanced Analytics & Visualizations for RepoLens

Provides:
  1. Language Breakdown (for Donut Chart)
  2. Health Radar Metrics (Security, Maintenance, Documentation, Tests, Community)
  3. Tech Debt Score (Cyclomatic Complexity + Code Smells)
"""

from collections import Counter
from typing import Optional


def calculate_language_breakdown(files: list[dict]) -> dict:
    """
    Calculate distribution of programming languages in the repository.
    Returns: {
        languages: [
            { language: "Python", count: 45, percentage: 35.2, color: "#58A6FF" },
            { language: "JavaScript", count: 38, percentage: 29.7, color: "#F0883E" },
            ...
        ],
        total_files: 128,
        primary_language: "Python"
    }
    """
    lang_colors = {
        "python": "#58A6FF",
        "javascript": "#F0883E",
        "typescript": "#3FB950",
        "html": "#F85149",
        "css": "#FF61F6",
        "java": "#FF6B6B",
        "go": "#00ADD8",
        "rust": "#CE422B",
        "c": "#A8B9CC",
        "cpp": "#F34B7D",
        "csharp": "#239120",
        "php": "#777BB4",
        "ruby": "#CC342D",
        "sql": "#F29111",
        "json": "#FBBF24",
        "yaml": "#CB171E",
        "markdown": "#083FA1",
        "other": "#6E7681",
    }
    
    lang_counter = Counter()
    for f in files:
        lang = f.get("lang", "other").lower()
        lang_counter[lang] += 1
    
    total = len(files)
    if total == 0:
        return {"languages": [], "total_files": 0, "primary_language": None}
    
    languages = []
    for lang, count in lang_counter.most_common():
        percentage = round((count / total) * 100, 1)
        color = lang_colors.get(lang, lang_colors["other"])
        languages.append({
            "language": lang.capitalize(),
            "count": count,
            "percentage": percentage,
            "color": color,
        })
    
    return {
        "languages": languages,
        "total_files": total,
        "primary_language": languages[0]["language"] if languages else None,
    }


def calculate_health_radar(
    complexity_data: dict,
    smells_data: list[dict],
    timeline_data: dict,
    files: list[dict]
) -> dict:
    """
    Calculate 5 health metrics for radar chart (0-100 scale).
    
    Returns: {
        security: 75,              # Based on code smells count
        maintenance: 82,           # Recent commit frequency
        documentation: 68,         # Comment-to-code ratio
        tests: 55,                 # Presence of test files
        community: 70,             # Activity trends from timeline
        overall_health: 70,        # Average
        status: "healthy"          # "excellent" | "healthy" | "fair" | "poor"
    }
    """
    
    # 1. Security: Based on critical smells (lower = more smells = less secure)
    critical_smells = len([s for s in smells_data if s.get("severity") == "critical"])
    warning_smells = len([s for s in smells_data if s.get("severity") == "warning"])
    total_potentially_bad = critical_smells * 2 + warning_smells
    security_score = max(20, 100 - (total_potentially_bad * 3))
    
    # 2. Maintenance: Based on recent commit activity
    timeframe = timeline_data.get("timeframe_comparison", {})
    last_7_commits = timeframe.get("last_7_days", {}).get("commits", 0)
    last_30_commits = timeframe.get("last_30_days", {}).get("commits", 0)
    
    if last_7_commits >= 5:
        maintenance_score = 95
    elif last_30_commits >= 20:
        maintenance_score = 80
    elif last_30_commits >= 10:
        maintenance_score = 65
    elif last_30_commits >= 5:
        maintenance_score = 45
    else:
        maintenance_score = 25
    
    # 3. Documentation: Comment-to-code ratio
    total_lines = 0
    total_comments = 0
    
    for f in files:
        content = f.get("content", "")
        if not content:
            continue
        lines = content.count("\n")
        total_lines += lines
        
        # Simple comment detection
        comments = content.count("#") + content.count("//") + content.count("/*")
        total_comments += comments
    
    if total_lines > 0:
        doc_ratio = (total_comments / total_lines) * 100
        documentation_score = min(100, int(doc_ratio * 10))  # Scale up ratio
    else:
        documentation_score = 50
    
    # 4. Test Coverage: Presence of test files
    test_files = len([f for f in files if "test" in f.get("path", "").lower() or "spec" in f.get("path", "").lower()])
    total_files = len(files)
    
    if total_files > 0:
        test_percentage = (test_files / total_files) * 100
        if test_percentage >= 20:
            tests_score = 90
        elif test_percentage >= 10:
            tests_score = 75
        elif test_percentage >= 5:
            tests_score = 60
        elif test_files > 0:
            tests_score = 40
        else:
            tests_score = 20
    else:
        tests_score = 30
    
    # 5. Community: Based on contributor diversity and activity trend
    contributors = timeline_data.get("contributors", [])
    contributor_count = len(contributors)
    
    volatility_data = timeline_data.get("volatility", {})
    consistency = volatility_data.get("consistency", "stable")
    
    community_score = 50
    if contributor_count >= 5:
        community_score += 20
    elif contributor_count >= 3:
        community_score += 15
    else:
        community_score += 5
    
    if consistency in ("very_stable", "stable"):
        community_score += 15
    elif consistency == "moderate":
        community_score += 8
    
    community_score = min(100, community_score)
    
    # Overall health
    scores = [security_score, maintenance_score, documentation_score, tests_score, community_score]
    overall = round(sum(scores) / len(scores))
    
    if overall >= 80:
        status = "excellent"
    elif overall >= 65:
        status = "healthy"
    elif overall >= 50:
        status = "fair"
    else:
        status = "poor"
    
    return {
        "security": round(security_score),
        "maintenance": round(maintenance_score),
        "documentation": round(documentation_score),
        "tests": round(tests_score),
        "community": round(community_score),
        "overall_health": overall,
        "status": status,
    }


def calculate_tech_debt_score(
    complexity_data: dict,
    smells_data: list[dict]
) -> dict:
    """
    Calculate Tech Debt Score (0-100) using formula:
    Score = (Avg Complexity * 0.4) + (Critical Smells Percentage * 0.6)
    
    Returns: {
        score: 68,                 # 0-100
        status: "high",            # "low" | "moderate" | "high" | "critical"
        message: "Refactor Suggested",
        color: "red",
        complexity_impact: 35,
        smells_impact: 33,
        recommendation: "..."
    }
    """
    
    # Get average complexity
    complexity_scores = []
    if complexity_data and isinstance(complexity_data, dict):
        for file_key, data in complexity_data.items():
            if isinstance(data, dict):
                score = data.get("score", 1)
                if isinstance(score, (int, float)):
                    complexity_scores.append(score)
    
    avg_complexity = sum(complexity_scores) / len(complexity_scores) if complexity_scores else 1
    # Normalize to 0-100 scale (complexity > 10 is bad)
    complexity_normalized = min(100, int((avg_complexity / 15) * 100))
    
    # Get critical smells percentage
    critical_smells = len([s for s in smells_data if s.get("severity") == "critical"])
    total_smells = len(smells_data)
    
    if total_smells > 0:
        critical_percentage = (critical_smells / total_smells) * 100
    else:
        critical_percentage = 0
    
    # Calculate overall tech debt
    tech_debt_score = int((complexity_normalized * 0.4) + (critical_percentage * 0.6))
    tech_debt_score = min(100, max(0, tech_debt_score))
    
    # Determine status
    if tech_debt_score >= 70:
        status = "critical"
        message = "Critical Refactoring Needed"
        color = "red"
    elif tech_debt_score >= 50:
        status = "high"
        message = "High Debt - Refactor Suggested"
        color = "orange"
    elif tech_debt_score >= 30:
        status = "moderate"
        message = "Moderate Debt - Plan Refactoring"
        color = "yellow"
    else:
        status = "low"
        message = "Low Debt - Healthy Codebase"
        color = "green"
    
    # Recommendation
    recommendations = {
        "critical": "Prioritize refactoring high-complexity files and resolve critical code smells immediately.",
        "high": "Schedule focused refactoring sprints. Break down large functions and reduce complexity.",
        "moderate": "Monitor complexity growth. Refactor as part of regular development cycles.",
        "low": "Maintain current code quality standards. Continue regular reviews.",
    }
    
    return {
        "score": tech_debt_score,
        "status": status,
        "message": message,
        "color": color,
        "complexity_impact": complexity_normalized,
        "smells_impact": int(critical_percentage),
        "recommendation": recommendations.get(status, ""),
    }


def build_insights(
    files: list[dict],
    complexity_data: dict,
    smells_data: list[dict],
    timeline_data: dict
) -> dict:
    """
    Build complete insights package for frontend visualizations.
    """
    return {
        "language_breakdown": calculate_language_breakdown(files),
        "health_radar": calculate_health_radar(
            complexity_data,
            smells_data,
            timeline_data,
            files
        ),
        "tech_debt": calculate_tech_debt_score(complexity_data, smells_data),
    }
