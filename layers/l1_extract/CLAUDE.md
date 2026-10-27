# rtl2d_l1 — L1 extract

## 輸入 → 輸出
RTL 目錄 → Selection（契約 v0-draft）

## 對外介面（唯一允許從 __init__ 匯出的東西）
```python
def extract(rtl_dir: Path) -> Selection: ...
```
- Selection 契約還沒有欄位，所以 `extract()` 會發出 `SelectionDraftWarning`，並回傳 v0-draft 欄位的 dict（`schema_version`、`design`、`signals[]`、`modules[]`，每筆含 `name`、`reason`、`source_refs`）；預設 heuristic，不花 API。對應方式見 `docs/adr/0002-selection-from-stage1-anchors.md`。契約定案後改成回傳 `Selection(**d)`。
- Stage 1 的完整輸出（anchors／region／fsm）先用開發用 CLI 產生：`python -m rtl2d_l1.cli ...`，要在 `layers/l1_extract/` 底下執行。

## 相依
- 可以：
  - rtl2d_contracts
  - pyslang（slang 12）：parse 與 elaborate
  - networkx：dependency graph
  - pydantic：內部 schema
  - anthropic：teacher LLM
  - 選配 `[distill]`：torch、transformers、peft、trl、datasets，只在 GPU 機器上裝
- 外部工具（選配，沒有也能跑）：
  - Graphviz `dot`：預覽圖
  - Yosys：FSM 交叉驗證與等價檢查；Windows 上透過 WSL 呼叫
- 不可以：其他層、rtl2d_pipeline、rtl2d_eval、本層的 experiments/、corpus/。

## 目錄
- `src/rtl2d_l1/`：實作，規格在 `docs/SPEC.md`（凍結，改了要升版並寫 `docs/CHANGELOG.md`）。
- `tests/`：只用 `examples/`（自寫的測試設計）和 `gold/`（draft gold）。第三方 corpus 不存在時，相關測試要自動跳過。
- `scripts/`：工具。`fetch_corpus.py` 抓第三方 RTL 到 `data/corpus/`（不進版控）；`equiv_check.py` 用 Yosys 做 bounded 等價檢查。
- `experiments/`：一個實驗一個資料夾，必有 README（照 docs/experiment_template.md）；輸出寫到 `runs/`。

## 本層禁忌
- LLM 只能挑 entity ID，不能自己寫出 RTL 名稱。所有 annotation 都要先過 `validate.py`，包括 ID 與名稱交叉比對、證據行號。
- 改了 `llm/prompt.py`、`taxonomy.py` 或 entity table 的格式，Run Store 的快取 key 就會變，必須升 `PROMPT_VERSION`／`versions.py`。
- 不要改 `docs/SPEC.md` 的既有語意，只能新增章節並升版。
- 本機路徑有中文時，uv 建的 venv 會在讀 `.pth` 時失敗（cp950）。請在 ASCII 路徑的 clone 跑測試；CI 不受影響。
