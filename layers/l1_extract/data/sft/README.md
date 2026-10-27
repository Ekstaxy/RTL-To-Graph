# Stage 1 student SFT dataset `sft-v1`（2026-10-03）

| 檔案 | 筆數 | module 群組 |
|---|---|---|
| `train.jsonl.gz` | 1,552（teacher 721 + 改名增強 831） | 419 |
| `eval.jsonl.gz` | 82（teacher 37 + 改名增強 45） | 29，和 train 沒有重疊 |

## 格式
每一行是一個 chat 樣本，對應 SPEC §9 的 I/O 合約：
- `system`：凍結的 prompt（`anchor-v2.1`、roles-v2）。
- `user`：entity table 加上逐行編號的 RTL；有子模組時另附子模組摘要。**不含**任何設計規格（spec），規格只給 teacher 看。
- `assistant`：teacher 最終通過 validator 的 JSON，包含 anchors、groups、interfaces 和證據行號 `lines`。
- `meta`：來源（`teacher` 或 `augment-rename`）、unit hash、module、design。

## 來源
- **teacher 樣本**：由 Opus 級的 Claude session 擔任 teacher，只標一輪，交件前必須通過 validator（ID 和名稱交叉比對、證據行號、auto role）。
- **語料**：examples、RTLLM、VerilogEval、picorv32/picosoc、verilog-axis／uart／i2c／axi／ethernet／wishbone、wb2axip、serv、darkriscv、biriscv、common_cells，以及亂改等價 benchmark。
- **授權**：全部為 MIT、ISC、BSD、Apache-2.0 或 SolderPad 0.51。各 repo 固定的 commit 見 `scripts/fetch_corpus.py`。
- **改名增強**：見 `experiments/e7_rename_augmentation`。內部名稱、enum 和 localparam 全部混淆；如果是設計的最上層，連 port 和 module 名稱也一起混淆。entity ID 不變，每筆都通過 validator 和證據行號檢查。

## 處理方式
- **去重**：同一個 module 的 RTL 只是參數（寬度）不同時，最多保留 2 筆；被去掉的那些，其改名變體也一起不收。
- **切分**：依「原始 module」分組。同一個 module 的參數變體和改名變體只會出現在同一邊，所以 eval 量到的是對沒看過 module 的泛化能力。
- **長度**：以字元估算，約 90% 的樣本在 16k token 以內，約 98% 在 24k 以內。`train_lora` 會丟掉超過 `--max-len` 的樣本並回報數量；建議在 GPU 允許時用 `--max-len 24576`。

## 重新產生
在 `layers/l1_extract/` 底下執行：
```bash
python scripts/fetch_corpus.py
# 把 experiments/e2_session_annotation/session/** 的答案 ingest 進 runs/store（batch plan + ingest-session）
python experiments/e7_rename_augmentation/run.py <manifests> --seeds 0 1 2 --out runs/sft_aug.jsonl
python -m rtl2d_l1.cli export-sft --out runs/sft_teacher.jsonl --augment runs/sft_aug.jsonl --split-dir runs/sft_v1
```

## 訓練
```bash
python -m rtl2d_l1.distill.train_lora --data train.jsonl --eval-data eval.jsonl \
    --model Qwen/Qwen3-8B --out ckpt/qwen3-8b-anchor --max-len 24576
```
