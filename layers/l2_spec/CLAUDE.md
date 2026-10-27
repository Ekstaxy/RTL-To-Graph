# rtl2d_l2 — L2 spec

## 輸入 → 輸出
Selection ＋ RTL 目錄 → Diagram；verify() 回傳問題清單給 agent 迴圈用

## 對外介面（唯一允許從 __init__ 匯出的東西）
```python
def build_spec(rtl_dir: Path, selection: Selection) -> Diagram: ...
def verify(rtl_dir: Path, selection: Selection) -> list[Issue]: ...
```

## 相依
- 可以：rtl2d_contracts、本層自己的第三方套件（TODO：擁有者列出）。
- 不可以：其他層、rtl2d_pipeline、rtl2d_eval、本層的 experiments/、corpus/。

## experiments/
一個實驗一個資料夾，必有 README（docs/experiment_template.md）；輸出寫到 runs/。

## 本層禁忌
- TODO：擁有者補充。
