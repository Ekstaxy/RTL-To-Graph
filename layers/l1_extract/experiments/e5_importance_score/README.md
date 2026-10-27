# e5_importance_score

**Owner:** L1（薛晏閎）　**Date:** 2026-10-03

## Hypothesis
critical／major／minor 是主觀的三級標籤，也是之前最不穩的部分（HIGH 層）。如果用 RTL 的結構量化一個 0–100 的重要度分數，應該可以：
1. 在 tier 內部提供連續排名；
2. 至少和「另一位強 annotator 的判斷」一樣好；
3. 在 annotator 比較弱、tier 不可靠時，仍然保住 view 的品質。

## Measurement
**特徵**（`src/rtl2d_l1/importance.py`）只看結構，不看名稱，所以改名不會影響分數：
- 寬度、是否為 state／memory、FSM 候選、port 方向；
- fan-in／fan-out／ctrl／addr fan-out；
- 控制可達的 state 和輸出比例、任意可達比例、到輸出的比例、反向 cone；
- module 內的排名、module 大小；
- 另外加上 annotator 給的 role。

**資料：**
- `build_dataset.py`：123 個 teacher module（examples、新 corpora、亂改 benchmark 的原版／S1／S2），共 3,367 個 entity，其中 1,735 個 anchor。
- `fit.py`：logistic regression，按電路分組做 10-fold 交叉驗證，同一電路的原版和改寫版放在同一組，不會跨 fold。
- `pair_eval.py`：拿 26 組獨立雙標（k0/k1），比較「用另一位 annotator 的 tier」和「用分數」哪一個比較能預測這位 annotator 的等級。訓練時排除這些電路。

指令（在 `layers/l1_extract/` 底下）：
```bash
uv run python experiments/e5_importance_score/build_dataset.py
uv run --with numpy --with scikit-learn python experiments/e5_importance_score/fit.py
uv run --with numpy --with scikit-learn python experiments/e5_importance_score/pair_eval.py
uv run python experiments/e3_perturb_benchmark/perturb_compare.py physical --importance structure
```

## Pass / abandon criteria
- 通過：結構＋role 的 HIGH AUC ≥ 0.8，而且加入分數後，對獨立 annotator 的預測不比只用 tier 差。
- 放棄：AUC < 0.7。

## Results

**在沒看過的電路上預測 teacher 的等級**（grouped CV AUC）：

| 特徵 | MEDIUM | HIGH |
|---|---|---|
| 只有結構 | 0.801 | 0.820 |
| 結構＋role | **0.841** | **0.907** |
| 選不選成 anchor（只有結構） | 0.816 | |

**預測一位獨立 annotator 的等級**（26 組 k0/k1，AUC）：

| 用什麼預測 | MEDIUM | HIGH |
|---|---|---|
| 另一位 Opus 級 annotator 的 tier | 0.942 | 0.879 |
| 結構＋role（不看 tier） | 0.816 | 0.858 |
| **分數：0.3×結構 + 0.7×tier** | **0.944** | **0.922** |

結構權重從 0.1 到 0.4 效果都一樣好（mean AUC 0.933），取 0.3。

**亂改 benchmark 的穩定度**（同一電路改寫後抽出的 view，F1）：

| 模式 | S1 HIGH | S2 HIGH | S1 MEDIUM recall | S2 MEDIUM recall |
|---|---|---|---|---|
| tier | 0.941 | 0.786 | 1.000 | 0.949 |
| score | 0.941 | 0.786 | 1.000 | 0.950 |
| structure | **0.945** | **0.822** | 0.969 | 0.926 |

**門檻**：HIGH ≥ 70，MEDIUM ≥ 40。
- 有 tier 時，這組門檻重現 teacher 原本的分級 99%。
- 只看結構時，用分段線性校準，讓 HIGH／MEDIUM 的比例和 teacher 相同（34%／62%）。

## Conclusion
- 已併入 `src`，對應 SPEC §4.6。每個 anchor 現在都有 `score` 和 `struct_score`（0–100）。
- `--importance score` 是預設：有強 annotator 時，等級和以前相同，但多了可以排序、可以設門檻的數字（`--min-score`）。
- `--importance structure`：完全不信任 annotator 的 tier。HIGH 跨改寫更穩，給弱模型用；實測見 e6。

## v2（2026-10-03）
用第 1–4 輪的資料重新擬合：9,151 個 anchor，412 個不同 module，同一個 module 只算一次，並依 module 分組做交叉驗證。

```bash
uv run --with numpy --with scikit-learn python experiments/e5_importance_score/fit.py --data runs/e5/dataset_r4.jsonl --tag _r4
```

**結果：**
- grouped CV AUC：MEDIUM 0.82、HIGH 0.87。
- 在 v1 沒看過的第四輪 module 上，v1 為 0.79／0.84，v2 為 0.81／0.86。
- 新的校準點：原始值 60.4 對應 70，32.8 對應 40；teacher 的 HIGH／MEDIUM 比例分別是 27%／56%。
- 已寫回 `importance.py`，版本 `importance-score-v2`。
