"""
run.py — Start the Flask development server
Usage: python run.py
"""
import sys
import os

# Add backend/ to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
os.chdir(os.path.join(os.path.dirname(__file__), "backend"))

from app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"""
╔════════════════════════════════════════════╗
║   AI GitHub Repo Analyzer — Backend        ║
╠════════════════════════════════════════════╣
║   http://localhost:{port}                  ║
║   Open frontend/index.html in browser      ║
╚════════════════════════════════════════════╝
    """)
    app.run(debug=True, port=port, host="0.0.0.0")
