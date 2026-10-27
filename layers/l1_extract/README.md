# rtl2d_l1：L1 extract（Stage 1：RTL semantic anchor extraction）

L1 的做法分三步：
1. EDA front-end 建立事實；
2. LLM 只負責挑出「哪裡重要」；
3. 演算法 trace 出跟架構有關的區域，交給 L2。

- 規格（凍結）：[docs/SPEC.md](docs/SPEC.md)；版本紀錄：[docs/CHANGELOG.md](docs/CHANGELOG.md)
- 驗證報告：[docs/VALIDATION.md](docs/VALIDATION.md)，包含資料集、盲測、亂改等價 benchmark、多輪標註
- 原始設計說明：[docs/stage1_architecture.md](docs/stage1_architecture.md)；提案書：[docs/proposal.pdf](docs/proposal.pdf)
- `extract()`：目前回傳 v0-draft Selection 的 dict，並發出 `SelectionDraftWarning`（不會報錯）
- 對 L2 的契約提案：[../../docs/adr/0002-selection-from-stage1-anchors.md](../../docs/adr/0002-selection-from-stage1-anchors.md)

```
RTL (.v/.sv, -f filelist, -I, -D)
  │  slang / pyslang 12：parse + elaborate（不做 synthesis）
  ▼
Typed dependency graph   DATA / CONTROL / ADDR / CLOCK / RESET / PORT（含 partial-read）
  ▼
Entity table / module    穩定 ID、FSM 候選、fan-in/out、控制扇出
  ▼
Anchor selector          heuristic | teacher LLM（Claude Opus 5.5 或 session）| distilled student（Qwen3-8B LoRA）
  │  validator（ID/名稱交叉、證據行號）→ retry；trace finding → refine；k-voting
  ▼
anchors.json ─► trace（cost-bounded slicing）─► region.json ─► (Selection, ADR-0002) ─► L2
  ├─► --target fsm：語法抽取 + 語意執行交叉驗證 ─► fsm.json / Mermaid / SVG
  └─► Run Store（每次標註完整存檔）─► export-sft ─► LoRA distill
```

## 安裝與測試

在 repo 根目錄：

```bash
uv sync --all-packages
uv run --package rtl2d-l1 pytest layers/l1_extract
```

- Teacher 模式需要 `ANTHROPIC_API_KEY`；heuristic、dry-run 和 session 標註都不需要。
- 選配工具：Graphviz `dot`（畫預覽圖）、Yosys（`yosys-check`、`scripts/equiv_check.py`；Windows 上透過 WSL）。

> **Windows 中文路徑**
> - slang 打不開非 ASCII 路徑：`elaborate()` 會自動把檔案 staging 到 `%TEMP%`，不需要手動處理。
> - uv 建的 venv 在中文路徑下讀 `.pth` 會失敗（cp950）：請把 repo clone 到 ASCII 路徑。

## 開發 CLI（在 `layers/l1_extract/` 下執行）

輸出預設寫到 `runs/`（不進版控）。Run Store 在 `runs/store`。

| 指令 | 用途 | 花 API？ |
|---|---|---|
| `python -m rtl2d_l1.cli entities FILES --top T` | 印出 entity table | 否 |
| `python -m rtl2d_l1.cli run --manifest M --mode heuristic\|dry-run\|teacher [--k 2]` | 產生 anchors、region，以及（選配的）fsm／timing | teacher 才花 |
| `python -m rtl2d_l1.cli diagram --manifest M --preset standard --target block fsm` | 用 Graphviz 畫預覽圖 | 否 |
| `python -m rtl2d_l1.cli eval --manifest M --gold gold --mode ...` | 對 gold 評分 | 視 mode |
| `python -m rtl2d_l1.cli augment --manifest M --gold gold` | 產生改名或去註解的變體，並搬移 label | 否 |
| `python -m rtl2d_l1.cli batch plan --manifest M [--submit \| --units-dir D]` | Batch API，或 session 標註的工作單元 | `--submit` 才花 |
| `python -m rtl2d_l1.cli batch collect PLAN --wait`／`batch ingest-session PLAN` | 收回結果並寫入 Run Store | 否 |
| `python -m rtl2d_l1.cli calibrate M1 M2 ...` | 檢查是否太細或太嚴 | 否 |
| `python -m rtl2d_l1.cli sweep --manifest M` | 前端穩健性掃描 | 否 |
| `python -m rtl2d_l1.cli yosys-check --manifest M` | FSM 偵測和 Yosys `fsm_detect` 交叉比對 | 否 |
| `python -m rtl2d_l1.cli export-sft --out runs/sft.jsonl` | 從 Run Store 匯出 SFT 資料 | 否 |
| `python -m rtl2d_l1.cli cost` | 查 API 花費 | 否 |

### 輸出目標 `--target`

| target | 狀態 |
|---|---|
| `block`（預設） | 可用 |
| `fsm` | 可用（語法抽取 + 語意交叉驗證，`semantic_check`） |
| `timing` | 預留（之後要用 SymbiYosys） |

### 使用者調控

Teacher 一律標到最細，看哪個詳細程度是事後的 view，不需要重打 API。

- `--preset overview|standard|detailed|control|datapath`
- `--level`、`--max-anchors`、`--focus`/`--exclude ROLE`、`--hide-interfaces`
- `--importance score|tier|structure`、`--min-score X`：每個 anchor 都有 0–100 的量化重要度（SPEC §4.6），HIGH ≥ 70、MEDIUM ≥ 40。強 teacher 用預設的 `score`；弱模型或 student 建議用 `structure`（實測見 e6）
- `--region-threshold`、`--depth`、`--reg-hops`、`--steiner`、`--edge-fanin`

完整說明見 SPEC §4.5。

## 目錄

```
src/rtl2d_l1/   frontend/（elab, graph, entities, fsm, fsm_semantic, fsm_hybrid, yosys_check）
                taxonomy, schema, heuristic, llm/（prompt, teacher）, validate, vote, trace,
                controls, pipeline, store, augment, evaluate, calibrate, diagram, cli,
                distill/（export, train_lora）, versions
tests/          30+ 個測試（teacher 用 fake client，不花錢）
examples/       6 個自寫測試設計 + corpus.json
gold/           draft gold（draft-v0，待三人審）
scripts/        fetch_corpus.py（第三方 RTL，固定 commit）、build_manifests*.py、equiv_check.py
data/corpus/    manifests（*.json 進版控；clone 下來的 repo 不進版控）
data/sft/       student SFT 資料集 sft-v1（gzip，含 data card）
experiments/    e1 trace 調參、e2 session 標註（含全部答案）、e3 亂改等價 benchmark、e4 語意 FSM、
                e5 量化重要度、e6 弱模型（Haiku 4.5）實測、e7 改名增強
```

## 第三方 corpus

```bash
python scripts/fetch_corpus.py
```

會下載以下 repo，皆固定 commit：picorv32（ISC）、RTLLM（MIT）、verilog-eval（MIT）、verilog-axis／verilog-uart（MIT）、serv（ISC）、darkriscv（BSD-3）。

## 目前結果（摘要，細節見 VALIDATION）

| 項目 | 結果 |
|---|---|
| Teacher vs draft gold，MEDIUM | recall 0.91、precision 0.95（heuristic recall 0.48） |
| Annotator 一致度，MEDIUM | 0.93 |
| 盲測（名稱全混淆）MEDIUM | 0.88 |
| 亂改等價 benchmark | 28/28 通過 Yosys 嚴格 BMC |
| ├ FSM | 語意抽取 18/18 同構（語法抽取 0/18） |
| └ Anchor MEDIUM recall | S1 1.00、S2 0.95–0.97 |
| 真實 corpus FSM 交叉驗證（262 個設計） | 52 個 FSM，0 個 mismatch |
| 多輪 self-audit | 沒有增益，預設 `passes=1`；要更高可信度時用 k=2 獨立投票 |
| 量化重要度 v2（沒看過的 module） | AUC MEDIUM 0.81、HIGH 0.86 |
| 弱模型（Haiku 4.5，structure 模式）亂改穩定度 S1 HIGH | 0.93 |
| 標註資料 | 683 個 Opus 級單元、426 個 module、20,342 個 anchor |
| SFT 資料集 `data/sft/` | train 1,552／eval 82，依 module 切分 |
