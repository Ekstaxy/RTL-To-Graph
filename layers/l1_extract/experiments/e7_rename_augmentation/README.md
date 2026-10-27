# e7_rename_augmentation

**Owner:** L1（薛晏閎）　**Date:** 2026-10-03

## Hypothesis
已經標好的 leaf module，可以不花任何標註成本，轉成多筆改名的 SFT 樣本：
1. 混淆名稱：內部訊號、enum literal、localparam；如果是設計的最上層，連 port、parameter、module 名稱也一起混淆。
2. 去掉註解。
3. 重建 entity table。entity ID 依原始碼位置排序，所以應該不變。
4. 把 teacher 的答案搬過去：ID 保持不變；`name` 和所有自由文字（`why`、`module_summary`、group 名稱）都用同一張對照表改寫。

這些樣本會逼 student 從結構判斷，而不是靠名稱猜（SPEC 第 1 條硬規則：「Judge by structure, not by names」）。

## Measurement
```bash
python experiments/e7_rename_augmentation/run.py examples/corpus.json data/corpus/opensource.json \
    experiments/e3_perturb_benchmark/data/manifest_orig.json data/corpus/round4_all.json \
    --seeds 0 1 2 --out runs/sft_aug.jsonl
```
每個樣本都必須通過兩項檢查才保留：
- 改名後的 entity ID 和原本完全相同；
- 通過 validator，而且要求證據行號正確（`require_evidence=True`）。

## Pass / abandon criteria
- 通過：至少 95% 的變體能保留下來。
- 放棄：ID 不一致的比例超過 1%（代表改名改動了結構）。

## Results
- 355 個 leaf 單元 × 3 個 seed，產生 **1,059 筆**樣本。
- ID 不一致：0 筆。
- validator 不通過：6 筆。原因是改名後證據行號對不到名稱，例如同一行出現兩個名稱、其中一個被改掉。這 6 筆直接丟棄。

## Conclusion
- 採用。`export-sft --augment runs/sft_aug.jsonl --split-dir ...` 會把這些樣本併進資料集。
- train／eval 依「原始 module」切分：同一個 module 的所有改名變體和參數變體只會出現在同一邊，評估量到的是對沒看過 module 的泛化能力。
- 只是寬度不同的重複 module 在 teacher 端已經去重，它們的改名樣本也一起不收。
