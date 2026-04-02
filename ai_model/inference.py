"""
inference.py — RepoAI Model Inference (v2 - Fixed)
Test and use your trained model interactively.

WHAT CHANGED FROM v1:
  - v1 did NOT use the prompt prefix, causing bad outputs
  - v2 uses the same prefix as training: "Answer the following question..."
  - v2 has better generation parameters
  - v2 loads the prefix from training_meta.json for consistency

Run from project root:
    python ai_model/inference.py
"""

import os
import sys
import json
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(ROOT, "ai_model", "my_repo_model")

# Default prompt prefix (should match train.py)
PROMPT_PREFIX = "Answer the following question about a GitHub repository: "

# ── Check model exists ───────────────────────────────────
if not os.path.exists(MODEL_PATH):
    print(f"❌ Model not found at: {MODEL_PATH}")
    print("   Run training first: python ai_model/train.py")
    sys.exit(1)

# Load prompt prefix from training metadata if available
meta_path = os.path.join(MODEL_PATH, "training_meta.json")
if os.path.exists(meta_path):
    with open(meta_path) as f:
        meta = json.load(f)
    PROMPT_PREFIX = meta.get("prompt_prefix", PROMPT_PREFIX)
    print(f"ℹ Model info: base={meta.get('base_model')} | "
          f"examples={meta.get('train_examples')} | loss={meta.get('final_loss')}")

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

print(f"Loading model from: {MODEL_PATH}")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
model.eval()

device = "cuda" if torch.cuda.is_available() else "cpu"
model = model.to(device)
print(f"Model loaded on {device.upper()} ✅")
print(f"Prompt prefix: \"{PROMPT_PREFIX[:50]}...\"\n")


def ask(question: str, max_new_tokens: int = 300) -> str:
    """Ask your trained model a question and get an answer."""
    # CRITICAL: Must use the same prefix as training!
    full_prompt = PROMPT_PREFIX + question

    inputs = tokenizer(
        full_prompt,
        return_tensors="pt",
        max_length=512,
        truncation=True,
        padding=True,
    ).to(device)

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            num_beams=4,             # beam search for better quality
            early_stopping=True,
            no_repeat_ngram_size=3,  # avoid repetition
            length_penalty=1.2,      # encourage longer answers
            temperature=1.0,
        )

    answer = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return answer


def run_demo_tests():
    """Run a set of test questions to see how well the model performs."""
    print("=" * 60)
    print("  Running Demo Tests on Your Trained Model")
    print("=" * 60)

    test_questions = [
        "What does the psf/requests repository do?",
        "What does the pallets/flask repository do?",
        "How do I install requests?",
        "What is cyclomatic complexity and why does it matter?",
        "How do I find the entry point of a Python project?",
        "Generate a professional README.md for the psf/requests repository.",
        "What is the difference between authentication and authorization?",
        "What does requirements.txt do?",
        "What does RAG mean in AI?",
        "Hello",
        "What is a dependency graph in software?",
        "How can I contribute to expressjs/express?",
    ]

    passed = 0
    for i, question in enumerate(test_questions, 1):
        print(f"\n[{i}/{len(test_questions)}] Q: {question}")
        answer = ask(question)
        print(f"          A: {answer[:250]}{'...' if len(answer) > 250 else ''}")

        # Quality check — answer should be more than just a few words
        if len(answer.split()) > 8:
            print("          ✅ Good response")
            passed += 1
        else:
            print("          ⚠️  Short response — model may need more training")

    print(f"\n{'='*60}")
    print(f"Results: {passed}/{len(test_questions)} good responses")
    if passed >= 9:
        print("🎉 Model is working great!")
    elif passed >= 6:
        print("✅ Model is working well but could improve with more data")
    elif passed >= 4:
        print("⚠️  Model is okay but could use more training data")
    else:
        print("❌ Model needs more training — run collect_data.py to get more data")
    print(f"{'='*60}\n")


def interactive_mode():
    """Run the model in interactive chat mode."""
    print("\n" + "=" * 60)
    print("  Interactive Mode — Type your questions!")
    print("  Type 'quit' to exit")
    print("=" * 60)

    while True:
        try:
            question = input("\n❓ Your question: ").strip()
            if question.lower() in ("quit", "exit", "q"):
                print("Goodbye! 👋")
                break
            if not question:
                continue

            print("🤔 Thinking...")
            answer = ask(question)
            print(f"\n💡 Answer:\n{answer}")

        except KeyboardInterrupt:
            print("\n\nGoodbye! 👋")
            break


if __name__ == "__main__":
    # First run the demo tests
    run_demo_tests()

    # Then enter interactive mode
    print("\nWould you like to chat with your model interactively?")
    choice = input("Enter 'yes' to start interactive mode: ").strip().lower()
    if choice in ("yes", "y"):
        interactive_mode()
