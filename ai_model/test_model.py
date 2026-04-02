"""
test_model.py  —  RepoAI Model Evaluator (v2 - Fixed)
Tests your trained Flan-T5 model with 15 questions and scores it.

WHAT CHANGED FROM v1:
  - v1 did NOT use prompt prefix in ask() — test results were garbage
  - v2 uses the same prefix as training for accurate evaluation
  - v2 loads prefix from training_meta.json

Run AFTER training: python ai_model/test_model.py
"""

import os, json, time
from pathlib import Path

MODEL_PATH   = "./ai_model/my_repo_model"
TEST_FILE    = "./ai_model/data/test.jsonl"
REPORT_FILE  = "./ai_model/test_report.txt"

# Default prompt prefix (must match train.py)
PROMPT_PREFIX = "Answer the following question about a GitHub repository: "

# Load from training meta if available
_meta_path = Path(MODEL_PATH) / "training_meta.json"
if _meta_path.exists():
    _meta = json.loads(_meta_path.read_text())
    PROMPT_PREFIX = _meta.get("prompt_prefix", PROMPT_PREFIX)

# ── 15 built-in test questions ───────────────────────────
TESTS = [
    # Repo overview
    {
        "q": "What does the psf/requests repository do?",
        "keywords": ["http","library","requests","python","stars"],
        "category": "Repo Overview"
    },
    {
        "q": "What does the pallets/flask repository do?",
        "keywords": ["flask","web","framework","python","micro"],
        "category": "Repo Overview"
    },
    # Installation
    {
        "q": "How do I install requests?",
        "keywords": ["pip","install","requests","bash","clone"],
        "category": "Installation"
    },
    # Architecture
    {
        "q": "Explain the architecture of pallets/flask.",
        "keywords": ["structure","files","directory","flask","language"],
        "category": "Architecture"
    },
    # Auth
    {
        "q": "Which file handles authentication in django/django?",
        "keywords": ["auth","django","file","authentication","login"],
        "category": "Auth"
    },
    # Entry points
    {
        "q": "What are the main entry points of pallets/flask?",
        "keywords": ["entry","main","app","flask"],
        "category": "Entry Points"
    },
    # README
    {
        "q": "Generate a professional README.md for the psf/requests repository.",
        "keywords": ["#","installation","license","features","overview"],
        "category": "README Gen"
    },
    # Complexity
    {
        "q": "Which files have the highest complexity in django/django?",
        "keywords": ["complex","files","core","django","logic"],
        "category": "Complexity"
    },
    # Generic Q&A
    {
        "q": "What is cyclomatic complexity and why does it matter?",
        "keywords": ["complexity","paths","code","bugs","test"],
        "category": "Generic"
    },
    {
        "q": "What is a dependency graph in software?",
        "keywords": ["graph","nodes","import","files","circular"],
        "category": "Generic"
    },
    {
        "q": "What does RAG mean in AI?",
        "keywords": ["retrieval","augmented","generation","context","search"],
        "category": "Generic"
    },
    {
        "q": "What is a circular dependency and how do I fix it?",
        "keywords": ["circular","import","loop","fix","extract"],
        "category": "Generic"
    },
    {
        "q": "How do I improve a file with high complexity?",
        "keywords": ["break","function","nesting","return","smaller"],
        "category": "Generic"
    },
    {
        "q": "How can I contribute to expressjs/express?",
        "keywords": ["fork","clone","branch","pull","request"],
        "category": "Contributing"
    },
    {
        "q": "How do I run the tests for expressjs/express?",
        "keywords": ["test","npm","run","bash"],
        "category": "Testing"
    },
]


def load_model():
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    if not Path(MODEL_PATH).exists():
        print(f"❌ Model not found at {MODEL_PATH}")
        print("   Run: python ai_model/train.py")
        return None, None

    meta_path = Path(MODEL_PATH) / "training_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        print(f"ℹ Model info: base={meta.get('base_model')} | "
              f"examples={meta.get('train_examples')} | loss={meta.get('final_loss')}\n")

    print(f"📥 Loading model from {MODEL_PATH}...")
    tok   = AutoTokenizer.from_pretrained(MODEL_PATH)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
    print("✓ Model loaded\n")
    return model, tok


def ask(model, tok, question, max_new_tokens=250):
    # CRITICAL: Must use the same prefix as training!
    prompt = PROMPT_PREFIX + question
    inputs = tok(prompt, return_tensors="pt", max_length=512, truncation=True)
    t0 = time.time()
    out = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        num_beams=4,
        early_stopping=True,
        no_repeat_ngram_size=3,
        length_penalty=1.2,
        temperature=1.0,
    )
    elapsed = round(time.time() - t0, 2)
    return tok.decode(out[0], skip_special_tokens=True), elapsed


def score(answer, keywords):
    al = answer.lower()
    hits = sum(1 for k in keywords if k.lower() in al)
    return round(hits / len(keywords), 2) if keywords else 0.0


def eval_test_file(model, tok):
    if not Path(TEST_FILE).exists():
        return None
    lines = [json.loads(l) for l in open(TEST_FILE, encoding="utf-8") if l.strip()]
    if not lines:
        return None

    print(f"📊 Evaluating on {len(lines)} test examples...")
    total, results = 0, []
    for ex in lines[:20]:
        ans, _ = ask(model, tok, ex["prompt"], max_new_tokens=200)
        exp_words = set(ex["completion"].lower().split())
        ans_words = set(ans.lower().split())
        overlap = len(exp_words & ans_words) / len(exp_words) if exp_words else 0
        total += overlap
        results.append({
            "prompt": ex["prompt"][:70],
            "overlap": round(overlap, 2),
            "answer": ans[:80],
        })
    avg = total / len(results) if results else 0
    return {"avg": round(avg, 3), "samples": results}


def main():
    print("=" * 55)
    print("  RepoAI — Model Test & Evaluation (v2)")
    print("=" * 55)
    print()

    model, tok = load_model()
    if model is None:
        return

    print("🧪 Running 15 built-in tests...\n")
    results, total_score = [], 0

    for i, t in enumerate(TESTS, 1):
        print(f"[{i:02d}/{len(TESTS)}] {t['category']}: {t['q'][:60]}")
        ans, sec = ask(model, tok, t["q"])
        sc = score(ans, t["keywords"])
        total_score += sc
        grade = "✅" if sc >= 0.6 else "🟡" if sc >= 0.4 else "❌"
        print(f"       → {ans[:120]}{'...' if len(ans)>120 else ''}")
        print(f"       Score: {sc:.0%} | {sec}s | {grade}\n")
        results.append({**t, "answer": ans, "score": sc, "time": sec})

    avg = total_score / len(TESTS)

    # Test file evaluation
    file_eval = eval_test_file(model, tok)

    # ── Summary ──────────────────────────────────────────
    print("=" * 55)
    print("  RESULTS SUMMARY")
    print("=" * 55)
    print(f"  Built-in test avg:  {avg:.1%}")
    if file_eval:
        print(f"  Test file overlap:  {file_eval['avg']:.1%}")

    if avg >= 0.65:
        verdict = "✅ GOOD  — Model is working well!"
        advice  = "Your app is ready to use."
    elif avg >= 0.45:
        verdict = "🟡 OK    — Acceptable quality"
        advice  = "Collect more data and retrain for better results."
    else:
        verdict = "❌ POOR  — Model needs improvement"
        advice  = "Check your training data quality and retrain."

    print(f"\n  {verdict}")
    print(f"  {advice}")

    # By category
    from collections import defaultdict
    cat_scores = defaultdict(list)
    for r in results:
        cat_scores[r["category"]].append(r["score"])
    print(f"\n  By category:")
    for cat, scores in sorted(cat_scores.items()):
        avg_c = sum(scores)/len(scores)
        bar = "█" * int(avg_c * 10) + "░" * (10 - int(avg_c * 10))
        print(f"  {cat:<15} {bar} {avg_c:.0%}")

    # ── Save report ──────────────────────────────────────
    lines_out = [
        "=" * 55,
        "  RepoAI Model — Test Report",
        "=" * 55, "",
        f"Overall score: {avg:.1%}",
        f"Verdict: {verdict}", "",
        "── Per-Question Results ──", "",
    ]
    for r in results:
        lines_out.append(f"[{r['score']:.0%}] {r['category']}: {r['q']}")
        lines_out.append(f"       → {r['answer'][:150]}")
        lines_out.append("")
    if file_eval:
        lines_out += ["── Test File Results ──", f"Avg overlap: {file_eval['avg']:.1%}", ""]
        for s in file_eval["samples"][:5]:
            lines_out.append(f"[{s['overlap']:.0%}] {s['prompt']}")
            lines_out.append(f"       → {s['answer']}")
            lines_out.append("")

    Path(REPORT_FILE).write_text("\n".join(lines_out), encoding="utf-8")
    print(f"\n📄 Full report → {REPORT_FILE}")

    print("\n── Next steps ──────────────────────────────────")
    if avg >= 0.45:
        print("  ▶ Start your app:  cd backend && python app.py")
    else:
        print("  ▶ Collect more data:  python ai_model/collect_data.py")
        print("  ▶ Retrain:            python ai_model/train.py")


if __name__ == "__main__":
    main()
