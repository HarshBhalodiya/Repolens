"""
run.py — Start the Flask development server
Usage: python run.py
"""
import sys
from pathlib import Path

# Resolve project root using pathlib (no os.chdir!)
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"

# Add backend/ to the Python path so "from app import app" works
sys.path.insert(0, str(BACKEND_DIR))

from app import app

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 5000))
    print(f"""
╔════════════════════════════════════════════╗
║   RepoLens — AI GitHub Repo Analyzer       ║
╠════════════════════════════════════════════╣
║   http://localhost:{port}                  ║
║   Open in your browser to start            ║
╚════════════════════════════════════════════╝
    """)
    app.run(debug=True, port=port, host="0.0.0.0")
