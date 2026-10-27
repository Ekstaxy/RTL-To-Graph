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
