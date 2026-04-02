"""
evaluate.py — RepoAI Model Evaluator (v2 - Fixed)
Measures how good your trained model is using BLEU score and accuracy.

WHAT CHANGED FROM v1:
  - v1 did NOT use the prompt prefix — BLEU scores were meaningless
  - v2 uses the same prefix as training for accurate evaluation
  - v2 loads prefix from training_meta.json

Run from project root:
    python ai_model/evaluate.py
"""

import os
import sys
import json
import torch
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(ROOT, "ai_model", "my_repo_model")
TEST_FILE  = os.path.join(ROOT, "ai_model", "data", "test.jsonl")

# Default prompt prefix (must match train.py)
PROMPT_PREFIX = "Answer the following question about a GitHub repository: "

# ── Check files exist ────────────────────────────────────
if not os.path.exists(MODEL_PATH):
    print(f"❌ Model not found: {MODEL_PATH}")
    print("   Train first: python ai_model/train.py")
    sys.exit(1)

if not os.path.exists(TEST_FILE):
    print(f"❌ Test data not found: {TEST_FILE}")
    print("   Collect data first: python ai_model/collect_data.py")
    sys.exit(1)

# Load prompt prefix from training metadata
meta_path = os.path.join(MODEL_PATH, "training_meta.json")
if os.path.exists(meta_path):
    with open(meta_path) as f:
        meta = json.load(f)
    PROMPT_PREFIX = meta.get("prompt_prefix", PROMPT_PREFIX)
    print(f"ℹ Model: {meta.get('base_model')} | "
          f"Train examples: {meta.get('train_examples')} | Loss: {meta.get('final_loss')}")

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

print("Loading model for evaluation...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
model.eval()
device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)
print(f"Model loaded on {device.upper()} ✅")


def generate_answer(question: str) -> str:
    """Generate model answer for a question."""
    # CRITICAL: Must use the same prefix as training!
    full_prompt = PROMPT_PREFIX + question

    inputs = tokenizer(
        full_prompt, return_tensors="pt",
        max_length=512, truncation=True, padding=True
    ).to(device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs, max_new_tokens=300, num_beams=4,
            early_stopping=True, no_repeat_ngram_size=3,
            length_penalty=1.2,
        )
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


def simple_bleu(reference: str, hypothesis: str) -> float:
    """Simple unigram + bigram BLEU score (no external library needed)."""
    ref_tokens = reference.lower().split()
    hyp_tokens = hypothesis.lower().split()

    if not hyp_tokens:
        return 0.0

    # Unigram precision
    ref_unigrams = {}
    for t in ref_tokens:
        ref_unigrams[t] = ref_unigrams.get(t, 0) + 1

    matches_1 = 0
    for t in hyp_tokens:
        if ref_unigrams.get(t, 0) > 0:
            matches_1 += 1
            ref_unigrams[t] -= 1
    p1 = matches_1 / len(hyp_tokens)

    # Bigram precision
    ref_bigrams = {}
    for i in range(len(ref_tokens) - 1):
        bg = (ref_tokens[i], ref_tokens[i+1])
        ref_bigrams[bg] = ref_bigrams.get(bg, 0) + 1

    matches_2 = 0
    for i in range(len(hyp_tokens) - 1):
        bg = (hyp_tokens[i], hyp_tokens[i+1])
        if ref_bigrams.get(bg, 0) > 0:
            matches_2 += 1
            ref_bigrams[bg] -= 1
    p2 = matches_2 / max(len(hyp_tokens) - 1, 1)

    # Brevity penalty
    bp = min(1.0, len(hyp_tokens) / max(len(ref_tokens), 1))

    bleu = bp * ((p1 * p2) ** 0.5)
    return round(bleu * 100, 2)


def keyword_match(reference: str, hypothesis: str) -> float:
    """Check what % of important keywords from the answer are in the prediction."""
    # Focus on content words (skip common words)
    stop_words = {"is","a","an","the","in","of","and","or","to","for","with","it","this","that","are","be","has","have","was","were","by","on","at","from"}
    ref_words = set(w.lower() for w in reference.split() if w.lower() not in stop_words and len(w) > 3)
    hyp_words = set(w.lower() for w in hypothesis.split() if w.lower() not in stop_words and len(w) > 3)

    if not ref_words:
        return 100.0
    overlap = ref_words & hyp_words
    return round(len(overlap) / len(ref_words) * 100, 1)


def evaluate():
    """Run full evaluation on test dataset."""
    print(f"\n{'='*60}")
    print("  Model Evaluation Report")
    print(f"{'='*60}")

    # Load test data
    test_examples = []
    with open(TEST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                test_examples.append(json.loads(line))

    print(f"Test examples: {len(test_examples)}")
    # Evaluate on up to 50 examples (faster)
    eval_examples = test_examples[:50]
    print(f"Evaluating on: {len(eval_examples)} examples\n")

    bleu_scores = []
    keyword_scores = []
    length_ratios = []
    results = []

    for i, example in enumerate(eval_examples):
        question = example["prompt"]
        reference = example["completion"]

        prediction = generate_answer(question)

        bleu = simple_bleu(reference, prediction)
        kw_match = keyword_match(reference, prediction)
        len_ratio = len(prediction.split()) / max(len(reference.split()), 1)

        bleu_scores.append(bleu)
        keyword_scores.append(kw_match)
        length_ratios.append(len_ratio)

        results.append({
            "question": question[:60] + "..." if len(question) > 60 else question,
            "bleu": bleu,
            "keyword_match": kw_match,
            "predicted_words": len(prediction.split()),
            "reference_words": len(reference.split()),
        })

        # Print progress every 10
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(eval_examples)}...")

    # ── Summary Metrics ──────────────────────────────────
    avg_bleu = sum(bleu_scores) / len(bleu_scores)
    avg_kw   = sum(keyword_scores) / len(keyword_scores)
    avg_len  = sum(length_ratios) / len(length_ratios)

    print(f"\n{'='*60}")
    print(f"  EVALUATION RESULTS")
    print(f"{'='*60}")
    print(f"  Average BLEU Score:      {avg_bleu:.1f}  (higher = better, max 100)")
    print(f"  Keyword Match Rate:      {avg_kw:.1f}%  (% of key words correct)")
    print(f"  Avg Length Ratio:        {avg_len:.2f}   (1.0 = perfect length)")
    print(f"{'='*60}")

    # ── Grade the model ───────────────────────────────────
    print("\n  Model Grade:")
    if avg_bleu >= 40:
        print("  🎉 EXCELLENT — Model is working great!")
        grade = "A"
    elif avg_bleu >= 25:
        print("  ✅ GOOD — Model is working well")
        grade = "B"
    elif avg_bleu >= 15:
        print("  ⚠️  FAIR — Model needs more training data")
        grade = "C"
    elif avg_bleu >= 8:
        print("  ❌ POOR — Add more training examples and retrain")
        grade = "D"
    else:
        print("  ❌ VERY POOR — Model barely learned anything")
        print("     → Run collect_data.py to get better data")
        print("     → Increase EPOCHS in train.py to 10")
        grade = "F"

    # ── Best and worst examples ───────────────────────────
    results_sorted = sorted(results, key=lambda x: x["bleu"], reverse=True)

    print(f"\n  Top 3 Best Predictions (BLEU):")
    for r in results_sorted[:3]:
        print(f"    [{r['bleu']:.1f}] {r['question']}")

    print(f"\n  Top 3 Worst Predictions (BLEU):")
    for r in results_sorted[-3:]:
        print(f"    [{r['bleu']:.1f}] {r['question']}")

    # ── Recommendations ───────────────────────────────────
    print(f"\n{'='*60}")
    print("  Recommendations:")
    if avg_kw < 30:
        print("  • Add more diverse training examples (run collect_data.py again with more REPOS)")
    if avg_len < 0.5:
        print("  • Increase MAX_TARGET_LEN in train.py (answers too short)")
    if avg_bleu < 15:
        print("  • Increase EPOCHS to 10 in train.py")
        print("  • Add more training data (target 500+ examples)")
    if grade in ("A", "B"):
        print("  • Model is ready! Connect it to your Flask backend.")
        print("  • See: backend/chat_engine.py to replace Claude API")
    print(f"{'='*60}")

    # Save evaluation report
    report = {
        "avg_bleu": avg_bleu,
        "avg_keyword_match": avg_kw,
        "avg_length_ratio": avg_len,
        "grade": grade,
        "num_examples": len(eval_examples),
        "results": results,
    }
    report_path = os.path.join(ROOT, "ai_model", "eval_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Full report saved: {report_path}")


if __name__ == "__main__":
    evaluate()
