"""LoRA SFT for the student (SPEC §9). Run on a GPU box:

    pip install -e ".[distill]"
    python -m rtl2d_l1.distill.train_lora --data data/sft.jsonl --model Qwen/Qwen3-8B \\
        --out ckpt/qwen3-8b-anchor

Loss is computed on the assistant JSON only (the student imitates the teacher's final
answer, not its reasoning). Written against TRL's SFTConfig/SFTTrainer API (>=0.20);
check argument names against the TRL version installed on the GPU box.
"""

from __future__ import annotations

import argparse

DEFAULTS = {
    "Qwen/Qwen3-8B": {"lr": 1e-4},
    "Qwen/Qwen3-4B": {"lr": 2e-4},
    "Qwen/Qwen2.5-Coder-7B-Instruct": {"lr": 1e-4},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--model", default="Qwen/Qwen3-8B")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=3)
    ap.add_argument("--max-len", type=int, default=16384)
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--rank", type=int, default=64)
    ap.add_argument("--eval-frac", type=float, default=0.05)
    ap.add_argument(
        "--eval-data",
        default=None,
        help="held-out file from `export-sft --split-dir` (split by module); else random split",
    )
    args = ap.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from trl import SFTConfig, SFTTrainer

    lr = args.lr or DEFAULTS.get(args.model, {"lr": 1e-4})["lr"]
    if args.eval_data:
        files = {"train": args.data, "test": args.eval_data}
        ds = load_dataset("json", data_files=files).remove_columns(["meta"])
    else:
        ds = load_dataset("json", data_files=args.data, split="train").remove_columns(["meta"])
        ds = ds.train_test_split(test_size=args.eval_frac, seed=0)

    # a truncated sample would lose the assistant JSON (it comes last): drop over-long ones
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model)

    def fits(ex):
        return len(tok.apply_chat_template(ex["messages"], tokenize=True)) <= args.max_len

    for split in list(ds.keys()):
        n0 = len(ds[split])
        ds[split] = ds[split].filter(fits)
        print(f"{split}: kept {len(ds[split])}/{n0} samples within --max-len {args.max_len}")

    peft_cfg = LoraConfig(
        r=args.rank,
        lora_alpha=2 * args.rank,
        lora_dropout=0.05,
        target_modules="all-linear",
        task_type="CAUSAL_LM",
    )
    cfg = SFTConfig(
        output_dir=args.out,
        num_train_epochs=args.epochs,
        learning_rate=lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=16,
        gradient_checkpointing=True,
        bf16=True,
        max_length=args.max_len,
        assistant_only_loss=True,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        report_to="none",
        model_init_kwargs={"torch_dtype": torch.bfloat16},
    )
    trainer = SFTTrainer(
        model=args.model,
        args=cfg,
        train_dataset=ds["train"],
        eval_dataset=ds["test"],
        peft_config=peft_cfg,
    )
    trainer.train()
    trainer.save_model(args.out)


if __name__ == "__main__":
    main()
