# rtl2diagram：方案一（分層 monorepo＋契約套件）設計規格

> 日期：2026-10-02　用途：放進 repo 的 `docs/bootstrap.md`，讓 Claude Code 依此建立骨架。
> 範圍：只用方案一。不含 DVC、lab／product 關卡、ports／plugin、通用 IR。
>
> **我做的四個假設**（不成立時要改的地方寫在 §9）
> 1. 三層都用 Python，放在同一個 uv workspace。
> 2. 層與層之間用**函式呼叫**串接，由 `pipeline/` 負責；各層不提供自己的 CLI。
> 3. 契約以 **pydantic model 為準**，JSON Schema 由 model 匯出後進版控。這比「先寫 schema 再產生程式碼」少一個工具；代價是若之後有非 Python 的層，它只能讀匯出的 schema。
> 4. L1→L2 的契約還沒定，先放一個最小的暫定版，標 `v0-draft`。
>
> 文中的 toml、指令與程式片段都是設計稿，我沒有執行過。§7 要求 Claude Code 每一步都實際跑驗收指令。

---

## 1. 設計原則

1. **層只認契約，不認彼此。** `l1`、`l2`、`l3` 之間不得互相 import。
2. **串接只發生在 `pipeline/`。** 想知道三層怎麼接，只需要讀一個檔。
3. **每個層邊界都有 fixture。** `corpus/<案例>/expected/` 放各層的期望輸出，任何一層都能跳過上游獨立執行。
4. **實驗用目錄隔離，不用分支隔離。** 每層有自己的 `experiments/`，由該層擁有者全權處理。
5. **先讓骨架走完，再長肉。** 第一個里程碑是 `pipe4` 從頭跑到 SVG 並通過 round-trip，此時 L1、L2 都還是 fixture。

---

## 2. 目錄結構

```
rtl2diagram/
├── README.md
├── CLAUDE.md                     # 全域規則（§6.1）
├── pyproject.toml                # workspace 根
├── uv.lock
├── .python-version
├── .gitignore                    # 含 runs/、.venv/、.env
├── .github/
│   ├── CODEOWNERS
│   └── workflows/ci.yml
│
├── contracts/                    # 三人共管
│   ├── pyproject.toml            # 套件 rtl2d-contracts
│   ├── src/rtl2d_contracts/
│   │   ├── __init__.py
│   │   ├── version.py            # SCHEMA_VERSION
│   │   ├── selection.py          # L1 → L2（v0-draft）
│   │   ├── diagram.py            # L2 → L3 核心圖
│   │   ├── layout.py             # layout hints、overrides
│   │   ├── render.py             # L3 輸出的約定（SVG 上的 id 屬性）
│   │   ├── validate.py           # 跨欄位檢查：ID 唯一、端點存在、方向與位寬
│   │   └── export_schema.py      # model → schemas/*.json
│   ├── schemas/                  # 匯出的 JSON Schema（進版控）
│   ├── tests/
│   └── CHANGELOG.md
│
├── layers/
│   ├── l1_extract/               # 套件 rtl2d-l1
│   │   ├── CLAUDE.md
│   │   ├── pyproject.toml
│   │   ├── src/rtl2d_l1/__init__.py      # 對外只有 extract()
│   │   ├── tests/
│   │   └── experiments/README.md
│   ├── l2_spec/                  # 套件 rtl2d-l2
│   │   ├── CLAUDE.md
│   │   ├── pyproject.toml
│   │   ├── src/rtl2d_l2/__init__.py      # 對外只有 build_spec()、verify()
│   │   ├── tests/
│   │   └── experiments/README.md
│   └── l3_draw/                  # 套件 rtl2d-l3
│       ├── CLAUDE.md
│       ├── pyproject.toml
│       ├── src/rtl2d_l3/__init__.py      # 對外只有 draw()
│       ├── tests/
│       └── experiments/README.md
│
├── pipeline/                     # 套件 rtl2d-pipeline
│   ├── pyproject.toml            # 提供指令 `rtl2d`
│   ├── src/rtl2d_pipeline/
│   │   ├── run.py                # 串三層；之後的 agent 迴圈也放這裡
│   │   ├── fixtures.py           # 從 corpus 讀 expected/
│   │   └── cli.py
│   └── tests/test_e2e_pipe4.py
│
├── eval/                         # 套件 rtl2d-eval
│   ├── pyproject.toml
│   ├── src/rtl2d_eval/
│   │   ├── roundtrip.py          # SVG → block／port／net 清單，與 diagram 比對
│   │   └── noise_reduction.py    # 先留空殼
│   └── tests/
│
├── corpus/
│   ├── README.md                 # 案例的格式與新增方式
│   └── pipe4/
│       ├── rtl/pipe4.v
│       ├── expected/
│       │   ├── selection.json
│       │   ├── diagram.json
│       │   └── layout-hints.json
│       └── notes.md              # 哪些檔是手寫、誰審過
│
├── tests/
│   └── test_layer_boundaries.py  # 檢查 §3 的相依規則
│
├── runs/                         # 不進版控；每次執行的輸出
└── docs/
    ├── bootstrap.md              # 本文件
    ├── experiment_template.md
    └── adr/
        ├── 0000-template.md
        └── 0001-adopt-layered-monorepo.md
```

---

## 3. 相依規則

| 套件 | 可以 import | 不可以 import |
|---|---|---|
| `rtl2d_contracts` | 標準函式庫、pydantic | 其他任何 `rtl2d_*` |
| `rtl2d_l1`、`rtl2d_l2`、`rtl2d_l3` | `rtl2d_contracts`、各自的第三方套件 | 其他層、`pipeline`、`eval` |
| `rtl2d_eval` | `rtl2d_contracts` | 任何層、`pipeline` |
| `rtl2d_pipeline` | 全部 | — |
| `layers/*/experiments/` | 同層的 `src`、`rtl2d_contracts`、`rtl2d_eval` | 其他層 |

補充規則：
- 各層 `src/` 不得 import 自己的 `experiments/`。
- 各層 `src/` 不得讀 `corpus/`；讀 fixture 是 `pipeline` 與測試的事。
- 各層只能把檔案寫到呼叫者指定的位置；實驗的輸出寫到 `runs/`。

uv workspace 共用同一個環境，工具本身不會阻止某個成員 import 別的成員的相依，所以這張表要靠 `tests/test_layer_boundaries.py` 執行：用 `ast` 掃過每個套件 `src/` 下的 import，違規就讓測試失敗。

---

## 4. 契約

### 4.1 資料模型

`rtl2d_contracts` 提供四組 model。**欄位以既有的 `pipe4.diagram.json` 與 `pipe4.layout-hints.json` 為準**，下表只列 design space 文件已寫明的部分；Claude Code 不得自行新增欄位。

| 模組 | 內容 | 狀態 |
|---|---|---|
| `selection.py` | `Selection`：`schema_version`、`design`、`signals[]`、`modules[]`；每筆含 `name`、`reason`、`source_refs` | **v0-draft，待 L1／L2 擁有者定案** |
| `diagram.py` | `Diagram`：`schema_version`、`blocks[]`（`id`、`label`、`kind`、`parent_id`）、`ports[]`（`id`、`owner_block_id`、`direction`、`width`、`class`、`scope`）、`nets[]`（`id`、`source`、`targets`、`width`、`class`） | 依 design space S1＋S2 |
| `layout.py` | `LayoutHints`、`LayoutOverrides`；每筆 hint 帶來源 | 依 design space §5.3 |
| `render.py` | L3 輸出 SVG 的約定：每個 block、port、net 的圖元帶 `data-rtl2d-kind` 與 `data-rtl2d-id` | 本文件新定，round-trip 依賴它 |

`validate.py` 做 schema 表達不了的檢查（對應 design space 的 Q1）：ID 全域唯一、net 的端點存在、source 是輸出方向而 target 是輸入方向、位寬一致、`parent_id` 不成環。回傳問題清單，不丟例外。

### 4.2 各層對外介面

每層的 `__init__.py` 只匯出下列函式，其餘都是內部實作。

```python
# rtl2d_l1
def extract(rtl_dir: Path) -> Selection: ...

# rtl2d_l2
def build_spec(rtl_dir: Path, selection: Selection) -> Diagram: ...
def verify(rtl_dir: Path, selection: Selection) -> list[Issue]: ...   # 給之後的 agent 迴圈用

# rtl2d_l3
def draw(diagram: Diagram,
         hints: LayoutHints | None = None,
         overrides: LayoutOverrides | None = None) -> DrawResult: ...  # DrawResult.svg: str
```

`Issue` 與 `DrawResult` 也定義在 `rtl2d_contracts`。

### 4.3 變更流程

1. 在 `docs/adr/` 開一份 ADR，寫清楚哪一層需要什麼、為什麼。
2. 改 model，遞增 `SCHEMA_VERSION`，重新匯出 `schemas/`，寫 `CHANGELOG.md`。
3. 更新 `corpus/*/expected/` 使其通過新版驗證。
4. 全部測試通過後才合併。
5. CI 會檢查 `schemas/` 與 model 匯出結果一致，不一致就失敗。

`contracts/` 的 PR 需要另外兩人都看過。GitHub 的 CODEOWNERS 在列出多位擁有者時，任一位核准即算通過，所以這條靠團隊約定，或把分支保護的必要核准數設為 2。

---

## 5. 串接：`pipeline/`

```
rtl2d run corpus/pipe4 [--out runs/<時間戳>] [--fixture l1,l2]
rtl2d check <diagram.json>          # 只跑契約驗證
```

`run` 的流程：

```
rtl_dir ──L1.extract──▶ Selection ──L2.build_spec──▶ Diagram ──L3.draw──▶ SVG
              │                          │                        │
        validate + 存檔            validate + 存檔         roundtrip 比對 + 存檔
```

- 每一層的輸出都先過 `rtl2d_contracts.validate`，再寫進 `--out` 目錄（`selection.json`、`diagram.json`、`diagram.svg`、`roundtrip.json`），之後才交給下一層。任何一步有問題就停下並回報是哪一層。
- `--fixture l1` 表示不呼叫 `l1.extract`，改讀 `corpus/<案例>/expected/selection.json`；`--fixture l1,l2` 表示直接從 `expected/diagram.json` 開始。**這是三個人可以各自開工的關鍵**：負責 L3 的人永遠可以用 `--fixture l1,l2`。
- 某一層還沒實作時，它的函式丟 `NotImplementedError`，`run` 的錯誤訊息要提示可以加哪個 `--fixture`。
- 提案書的「生成 → 驗證 → 修正」迴圈之後寫在 `run.py`，以 `l2.verify()` 的回傳值驅動；骨架階段不做。

---

## 6. Claude Code 的說明檔

根目錄的 `CLAUDE.md` 在啟動時載入，子目錄的要等 Claude 讀到該目錄的檔案才載入。所以全域規則放根目錄，各層慣例放各層。

### 6.1 根目錄 `CLAUDE.md`（可直接使用）

```markdown
# rtl2diagram

RTL → 易讀硬體架構圖。三層管線，三位擁有者，一個 uv workspace。

## 結構
- contracts/        層與層之間的資料格式（pydantic）。三人共管。
- layers/l1_extract RTL → Selection
- layers/l2_spec    Selection → Diagram（含驗證）
- layers/l3_draw    Diagram → SVG
- pipeline/         唯一串接三層的地方；指令 `rtl2d`
- eval/             跨層指標（round-trip 等）
- corpus/           測試案例與各層期望輸出
- docs/adr/         架構決定

## 不可違反的規則
1. 層之間不得互相 import；層只能 import rtl2d_contracts。
2. 不得在沒有 ADR 的情況下修改 contracts/ 的 model。需要新欄位時，停下來告訴我。
3. 各層 src/ 不得讀 corpus/，不得 import experiments/。
4. 不得編造契約欄位。欄位以 corpus/pipe4/expected/ 的現有檔案為準。
5. 不得修改 corpus/*/expected/ 來讓測試通過。測試失敗時先回報原因。
6. 只在被指定的那一層目錄內改動；需要動到其他層時先說明。

## 常用指令
- 安裝：uv sync --all-packages
- 全部測試：uv run pytest
- 單一套件測試：uv run --package rtl2d-l3 pytest layers/l3_draw
- 端到端：uv run rtl2d run corpus/pipe4 --fixture l1,l2
- 檢查：uv run ruff check .
- 匯出 schema：uv run python -m rtl2d_contracts.export_schema

## 完成的定義
改動後 `uv run ruff check .` 與 `uv run pytest` 都通過，並貼出實際輸出。
```

### 6.2 各層 `CLAUDE.md` 的內容

每層一份，各約十行，由該層擁有者維護：

- 這一層的輸入與輸出（對應 §4.2 的函式簽名）。
- 這一層可以用的第三方套件，與不該用的。
- `experiments/` 的規矩：一個實驗一個資料夾，必有 README；輸出寫到 `runs/`。
- 這一層特有的禁忌。以 L3 為例：「只能讀 Diagram，不得增刪 block／port／net；所有圖元都要帶 `data-rtl2d-id`」。

---

## 7. 用 Claude Code 建立骨架：分六步

每一步是一次對話，做完跑驗收指令、commit，再進下一步。不要一次全部丟給它：每一步都小到你能讀完 diff。

**開始前你要手動做的事**：建空 repo；把本文件存成 `docs/bootstrap.md`；把你手上的 `pipe4.v`、`pipe4.diagram.json`、`pipe4.layout-hints.json` 放到暫存目錄 `_seed/`。

### 步驟 0　workspace 骨架

```
讀 docs/bootstrap.md 的 §2 與 §3。只做這件事：建立 uv workspace 骨架。
- 用 uv init 建立各成員（contracts、layers/l1_extract、layers/l2_spec、
  layers/l3_draw、pipeline、eval），套件名與 import 名照 §2。不要手寫
  build-system 設定，用 uv 產生的。
- 根目錄 pyproject.toml 設定 workspace 成員；成員之間的相依用 workspace source。
- 加入開發用相依 pytest、ruff；設定 pytest 找得到所有成員的 tests/。
- 每個套件放一個只有 docstring 的 __init__.py 與一個會通過的佔位測試。
- 建立 .gitignore（runs/、.venv/、.env、__pycache__）。
先列出你要執行的指令與要建立的檔案，等我確認再動手。
驗收：uv sync --all-packages、uv run pytest、uv run ruff check . 都通過，貼出輸出。
```

### 步驟 1　契約

```
讀 docs/bootstrap.md 的 §4。實作 rtl2d_contracts。
- 先讀 _seed/pipe4.diagram.json 與 _seed/pipe4.layout-hints.json，列出其中
  實際出現的所有欄位與型別，給我看過再寫 model。
- model 必須能無損載入這兩個檔案；檔案與 §4.1 的表不一致時以檔案為準，
  並把差異列給我。不要新增檔案裡沒有的欄位。
- Selection 依 §4.1 做最小版，在 docstring 標明 v0-draft。
- 實作 validate.py 與 export_schema.py；匯出結果寫到 contracts/schemas/。
- 測試：載入 pipe4 兩個檔案通過驗證；對 validate 的每條規則各寫一個
  故意弄壞的案例，確認抓得到；schemas/ 與匯出結果一致。
驗收：uv run pytest contracts 通過。
```

### 步驟 2　語料與各層 stub

```
讀 §2、§3、§4.2。
- 把 _seed/ 的三個檔案搬到 corpus/pipe4/（rtl/ 與 expected/），刪除 _seed/。
- 依 pipe4.v 手寫 corpus/pipe4/expected/selection.json，內容要與
  expected/diagram.json 對得上；在 notes.md 註明這份是暫定手寫。
- 三層各自依 §4.2 建立對外函式，內容一律 raise NotImplementedError，
  訊息說明這一層尚未實作。
- 實作 tests/test_layer_boundaries.py，以 ast 檢查 §3 的表與補充規則。
  寫完後暫時在某一層加一行違規的 import 確認測試會失敗，再移除。
驗收：uv run pytest 通過。
```

### 步驟 3　L3 最小渲染器與 round-trip

```
讀 §4.1 的 render.py 約定。只動 layers/l3_draw 與 eval。
- rtl2d_l3.draw：最陽春的版本。block 依輸入順序排成格子，port 放在左右兩側，
  net 用直線連接。不做任何排版最佳化。只用標準函式庫產生 SVG。
  每個圖元依約定帶 data-rtl2d-kind 與 data-rtl2d-id。
- rtl2d_eval.roundtrip：解析 SVG，取回 block、port、net 的 id 集合與每條 net
  的端點，與 Diagram 比對，回報多畫、漏畫、接錯。
- 測試：pipe4 的 round-trip 差異為零；另外手動改壞 SVG（刪一條 net、
  改一個端點、多一個 block），確認三種都抓得到。
驗收：uv run pytest layers/l3_draw eval 通過。
```

### 步驟 4　pipeline 與 CI

```
讀 §5。實作 rtl2d_pipeline 與指令 rtl2d（用 argparse）。
- run 與 check 兩個子指令；--fixture 的行為照 §5。
- 每層輸出先驗證、再存檔、再往下傳；失敗時指出是哪一層。
- tests/test_e2e_pipe4.py：以 --fixture l1,l2 跑 pipe4，檢查四個輸出檔都存在
  且 round-trip 差異為零；不加 --fixture 時應得到提示加 fixture 的錯誤訊息。
- .github/workflows/ci.yml：安裝 uv、uv sync --all-packages、ruff、pytest、
  端到端指令、檢查 schemas/ 是最新的。
驗收：uv run rtl2d run corpus/pipe4 --fixture l1,l2 成功，並貼出 runs/ 下的檔案清單。
```

### 步驟 5　文件與分工檔

```
- 根目錄 CLAUDE.md：使用 docs/bootstrap.md §6.1 的內容，並把常用指令逐一
  實際執行，與現況不符的地方修正。
- 三層各一份 CLAUDE.md，照 §6.2；內容只寫目前已成立的事實。
- docs/experiment_template.md、docs/adr/0000-template.md、
  docs/adr/0001-adopt-layered-monorepo.md（背景與決定取自本文件 §1）。
- 各層 experiments/README.md 說明規矩。
- corpus/README.md 說明如何新增案例。
- .github/CODEOWNERS：各層目錄一位擁有者，contracts/ 三位；帳號先用
  @TODO-l1、@TODO-l2、@TODO-l3，我會自己換。
- README.md：專案一句話說明、安裝、跑 pipe4 的指令、目錄導覽。
驗收：照 README 從乾淨的 clone 能跑完 pipe4。
```

### 做完之後的狀態

- `uv run rtl2d run corpus/pipe4 --fixture l1,l2` 產生一張很醜但接線正確的 SVG，round-trip 通過。
- L1、L2 的擁有者各自把 `NotImplementedError` 換成實作，每換一層就少一個 `--fixture`。
- 你在 `layers/l3_draw/experiments/` 開始做 N1（ELK 基線），不影響任何人。

---

## 8. 實驗的規矩

每層的 `experiments/` 由該層擁有者管理，全 repo 只有三條共同規定：

1. 一個實驗一個資料夾，命名 `<編號>_<名稱>`，例如 `n1_elk_baseline`。
2. 必有 README，照 `docs/experiment_template.md`：假設、量測方式、通過與放棄的條件、結果、結論。
3. 可以 import 同層 `src/`、`rtl2d_contracts`、`rtl2d_eval`；輸入讀 `corpus/`，輸出寫 `runs/`。

實驗的程式碼不要求測試，也不進 CI。要變成產品功能時，由擁有者搬進 `src/` 並補測試。

執行方式：`uv run --package rtl2d-l3 python layers/l3_draw/experiments/n1_elk_baseline/run.py`

---

## 9. 假設不成立時怎麼改

| 情況 | 改法 |
|---|---|
| L3 改用 TypeScript＋elkjs | `layers/l3_draw/` 變成 Node 專案並從 workspace 成員中排除；它讀 `contracts/schemas/` 匯出的 JSON Schema；`pipeline` 改以子行程呼叫它，傳檔案路徑。此時應考慮把契約改成「schema 為準」，開 ADR。 |
| 只有排版引擎要用 elkjs，其餘仍是 Python | L3 保持 Python 套件，內部以子行程呼叫一支小的 Node 腳本做排版；這是 L3 的內部細節，不影響其他層。 |
| 某一層的相依與別層衝突，或需要不同的 Python 版本 | uv workspace 要求全體共用一個 Python 版本範圍，也不適合成員相依互相衝突的情況。把該層移出 workspace 成員，改成獨立專案，其他套件以 path dependency 引用它。 |
| L1 要把 L2 的驗證器當工具呼叫 | 迴圈仍寫在 `pipeline/run.py`：由它呼叫 `l1.extract`、`l2.verify`，把問題清單再傳回 L1。需要在 `extract` 加一個接收上一輪問題的參數，這是契約變更，開 ADR。 |
| L1→L2 的契約定案 | 改 `selection.py`、去掉 `v0-draft`、更新 `expected/selection.json`，照 §4.3。 |

---

## 10. 交給 Claude Code 之前先確認

1. 你手上的 `pipe4.diagram.json` 是不是目前團隊認可的格式。步驟 1 會把它當成事實來源。
2. Python 版本（三層都能接受的最低版本）。
3. 套件與指令的命名（本文件用 `rtl2d_*` 與 `rtl2d`）。建好之後改名的成本不低。
4. 另外兩位擁有者是否同意 §3 的相依規則與 §4.3 的契約變更流程；這兩節是之後最容易起爭議的地方。
