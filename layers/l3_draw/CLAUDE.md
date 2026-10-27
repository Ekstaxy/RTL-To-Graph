# rtl2d_l3 — L3 draw

## 輸入 → 輸出
Diagram（＋LayoutHints／LayoutOverrides）→ DrawResult（.svg: str）

## 對外介面（唯一允許從 __init__ 匯出的東西）
```python
def draw(diagram: Diagram,
         hints: LayoutHints | None = None,
         overrides: LayoutOverrides | None = None) -> DrawResult: ...
```

## 相依
- 可以：rtl2d_contracts、本層自己的第三方套件（TODO：擁有者列出）。
- 不可以：其他層、rtl2d_pipeline、rtl2d_eval、本層的 experiments/、corpus/。

## experiments/
一個實驗一個資料夾，必有 README（docs/experiment_template.md）；輸出寫到 runs/。

## 本層禁忌
- 只能讀 Diagram，不得增刪 block／port／net。
- 所有圖元都要帶 data-rtl2d-kind 與 data-rtl2d-id（round-trip 依賴它）。
