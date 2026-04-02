"""
train.py  —  RepoAI Model Fine-Tuner (v2 - Fixed)
Uses google/flan-t5-base — an INSTRUCTION-TUNED model that actually
understands Q&A, unlike plain T5 which only does translation/summarization.

WHAT CHANGED FROM v1:
  - v1 saved a plain T5 model instead of Flan-T5 (wrong architecture)
  - v2 verifies the loaded model is actually Flan-T5
  - v2 uses proper hyperparameters for small-dataset fine-tuning
  - v2 increases target length to 512 for longer answers
  - v2 adds better logging and progress info

Run: python ai_model/train.py
"""

import os, json
from pathlib import Path

# ── Config ───────────────────────────────────────────────
MODEL_NAME  = "google/flan-t5-base"       # instruction-tuned, ~250MB
OUTPUT_DIR  = "./ai_model/my_repo_model"
TRAIN_FILE  = "./ai_model/data/train.jsonl"
TEST_FILE   = "./ai_model/data/test.jsonl"

EPOCHS          = 5       # good balance for small dataset on CPU
BATCH_SIZE      = 2       # small batch for CPU (low RAM usage)
GRAD_ACCUM      = 8       # effective batch = 16
LEARNING_RATE   = 3e-4    # good for small dataset
MAX_INPUT_LEN   = 256     # fits CPU memory
MAX_TARGET_LEN  = 256     # fits CPU memory
SAVE_STEPS      = 200
LOGGING_STEPS   = 25
WARMUP_STEPS    = 50      # warmup for stability

# The instruction prefix — MUST match inference.py and chat_engine.py
PROMPT_PREFIX = "Answer the following question about a GitHub repository: "


def check_data():
    if not Path(TRAIN_FILE).exists():
        print(f"❌ No training data found at {TRAIN_FILE}")
        print("   Run first: python ai_model/collect_data.py")
        return 0
    with open(TRAIN_FILE, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    if len(lines) < 5:
        print(f"❌ Only {len(lines)} examples — too few. Run collect_data.py")
        return 0
    try:
        sample = json.loads(lines[0])
        assert "prompt" in sample and "completion" in sample
    except Exception as e:
        print(f"❌ Bad data format: {e}")
        return 0

    # Quick quality check
    garbage = sum(1 for l in lines if "0 lines of code" in l)
    if garbage > len(lines) * 0.3:
        print(f"⚠️  Warning: {garbage}/{len(lines)} examples look like garbage data")
        print("   Consider re-running collect_data.py for better quality")

    print(f"✓ Training data: {len(lines)} examples")
    return len(lines)


def main():
    print("=" * 55)
    print("  RepoAI — Model Training (Flan-T5-base) v2")
    print("=" * 55)

    n = check_data()
    if not n:
        return

    # ── Imports ──────────────────────────────────────────
    try:
        from transformers import (
            AutoTokenizer, AutoModelForSeq2SeqLM,
            TrainingArguments, Trainer,
            DataCollatorForSeq2Seq, EarlyStoppingCallback
        )
        from datasets import load_dataset
        import torch
        print(f"✓ PyTorch {torch.__version__}")
        use_gpu = torch.cuda.is_available()
        print(f"✓ Device: {'GPU ⚡ ' + torch.cuda.get_device_name(0) if use_gpu else 'CPU'}")
    except ImportError as e:
        print(f"❌ Missing: {e}")
        print("   Run: pip install transformers datasets accelerate")
        return

    # ── Load model ───────────────────────────────────────
    print(f"\n📥 Loading {MODEL_NAME}...")
    print("   First time: downloads ~1GB — please wait...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model     = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
    params    = sum(p.numel() for p in model.parameters()) / 1e6
    print(f"✓ Model loaded | {params:.0f}M parameters")

    # Verify it's actually Flan-T5
    config_name = model.config._name_or_path
    print(f"✓ Base model: {config_name}")
    if "flan" not in config_name.lower():
        print(f"⚠️  Warning: Expected Flan-T5 but got {config_name}")
        print(f"   Flan-T5 is instruction-tuned and much better for Q&A")
    print()

    # ── Load dataset ─────────────────────────────────────
    data_files = {"train": TRAIN_FILE}
    has_test   = Path(TEST_FILE).exists()
    if has_test:
        data_files["test"] = TEST_FILE
    dataset = load_dataset("json", data_files=data_files)
    print(f"✓ Train: {len(dataset['train'])} examples")
    if has_test:
        print(f"✓ Test:  {len(dataset['test'])} examples")

    # ── Tokenize ─────────────────────────────────────────
    # Flan-T5 uses instruction format: prefix + prompt → completion
    def tokenize(batch):
        # Prefix with task instruction so Flan-T5 understands the task
        prompts = [PROMPT_PREFIX + p for p in batch["prompt"]]
        model_inputs = tokenizer(
            prompts,
            max_length=MAX_INPUT_LEN,
            truncation=True,
            padding="max_length",
        )
        labels = tokenizer(
            batch["completion"],
            max_length=MAX_TARGET_LEN,
            truncation=True,
            padding="max_length",
        )
        # -100 = ignore padding in loss
        label_ids = [
            [(l if l != tokenizer.pad_token_id else -100) for l in lab]
            for lab in labels["input_ids"]
        ]
        model_inputs["labels"] = label_ids
        return model_inputs

    print("\n⚙️  Tokenizing...")
    tokenized = dataset.map(
        tokenize, batched=True,
        remove_columns=["prompt", "completion"],
        desc="Tokenizing",
    )
    print("✓ Done\n")

    # ── Training args ────────────────────────────────────
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Clean up old checkpoints to save disk space
    for old_ckpt in Path(OUTPUT_DIR).glob("checkpoint-*"):
        import shutil
        shutil.rmtree(old_ckpt, ignore_errors=True)
        print(f"  Cleaned old checkpoint: {old_ckpt.name}")

    args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LEARNING_RATE,
        warmup_steps=WARMUP_STEPS,
        weight_decay=0.01,
        save_steps=SAVE_STEPS,
        save_total_limit=2,
        logging_steps=LOGGING_STEPS,
        fp16=use_gpu,
        report_to="none",
        load_best_model_at_end=has_test,
        eval_strategy="steps" if has_test else "no",
        eval_steps=SAVE_STEPS if has_test else None,
        metric_for_best_model="eval_loss" if has_test else None,
        greater_is_better=False,
        dataloader_num_workers=0,   # important for Windows
        lr_scheduler_type="cosine",  # better than linear for fine-tuning
    )

    callbacks = [EarlyStoppingCallback(early_stopping_patience=3)] if has_test else []

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized.get("test"),
        data_collator=DataCollatorForSeq2Seq(tokenizer, model=model, padding=True),
        callbacks=callbacks or None,
    )

    # ── Train ────────────────────────────────────────────
    print(f"🚀 Training started!")
    print(f"   Model:      {MODEL_NAME}")
    print(f"   Epochs:     {EPOCHS}")
    print(f"   Batch size: {BATCH_SIZE} × {GRAD_ACCUM} = {BATCH_SIZE*GRAD_ACCUM} effective")
    print(f"   LR:         {LEARNING_RATE}")
    print(f"   Max input:  {MAX_INPUT_LEN} tokens")
    print(f"   Max output: {MAX_TARGET_LEN} tokens")
    print(f"   Device:     {'GPU ⚡' if use_gpu else 'CPU (slow — grab a coffee ☕)'}\n")

    result = trainer.train()

    # ── Save ─────────────────────────────────────────────
    print("\n💾 Saving model...")
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    # Save meta
    meta = {
        "base_model": MODEL_NAME,
        "prompt_prefix": PROMPT_PREFIX,
        "epochs": EPOCHS,
        "learning_rate": LEARNING_RATE,
        "max_input_len": MAX_INPUT_LEN,
        "max_target_len": MAX_TARGET_LEN,
        "train_examples": len(dataset["train"]),
        "test_examples": len(dataset.get("test", [])) if has_test else 0,
        "final_loss": round(result.training_loss, 4),
    }
    with open(os.path.join(OUTPUT_DIR, "training_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n✅ Training complete!")
    print(f"   Saved to:   {OUTPUT_DIR}")
    print(f"   Final loss: {result.training_loss:.4f}")
    print(f"\n▶ Test your model:  python ai_model/test_model.py")
    print(f"▶ Start the app:    cd backend && python app.py")


if __name__ == "__main__":
    main()
