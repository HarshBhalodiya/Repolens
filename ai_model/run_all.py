"""
run_all.py — ONE COMMAND TO FIX EVERYTHING
Runs: collect_data → train → test in sequence.
Skips data collection if data already exists.

Usage: python ai_model/run_all.py
"""
import subprocess, sys, os
from pathlib import Path

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
print(f"Working directory: {os.getcwd()}\n")

# Skip data collection if we already have enough data
train_file = Path("ai_model/data/train.jsonl")
skip_collect = False
if train_file.exists():
    count = sum(1 for l in open(train_file, encoding="utf-8") if l.strip())
    if count >= 100:
        print(f"✓ Training data already exists ({count} examples) — skipping collection\n")
        skip_collect = True

steps = []
if not skip_collect:
    steps.append(("Step 1/3: Collecting training data...", [sys.executable, "ai_model/collect_data.py"]))
steps.append(("Training model (this takes ~1-2 hours on CPU)...", [sys.executable, "ai_model/train.py"]))
steps.append(("Testing model...", [sys.executable, "ai_model/test_model.py"]))

for i, (label, cmd) in enumerate(steps, 1):
    print(f"\n{'='*55}")
    print(f"  Step {i}/{len(steps)}: {label}")
    print(f"{'='*55}\n")
    result = subprocess.run(cmd, cwd=os.getcwd())
    if result.returncode != 0:
        print(f"\n❌ Failed at: {label}")
        print(f"   Fix the error above and re-run: python ai_model/run_all.py")
        sys.exit(1)

print(f"\n{'='*55}")
print(f"  ✅ ALL DONE! Your model is ready.")
print(f"  ▶ Start app: cd backend && python app.py")
print(f"{'='*55}")
