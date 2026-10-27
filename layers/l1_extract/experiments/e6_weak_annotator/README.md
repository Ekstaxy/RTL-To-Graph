# e6_weak_annotator

**Owner:** L1（薛晏閎）　**Date:** 2026-10-03

## Hypothesis
Stage 1 給 LLM 的支援包括：entity table、ID 制、validator retry、證據行號，以及 e5 的量化重要度。這些應該讓比 Opus 弱的模型也能產生可用的標註：
1. 結構上一定合法；
2. 重要的概念不漏；
3. 用 `--importance structure` 時，HIGH／MEDIUM view 接近強模型的結果。

## Measurement
- **Annotator**：Claude Haiku 4.5（session subagent）。流程和 Opus 級 annotator 完全相同：同一個 system prompt、同一個 validator（`check_answer.py`），只做一輪標註、不做自我審查。
- **單元**：54 個（兩波，第二波是階層設計的父模組），涵蓋 6 個 examples，以及亂改 benchmark 的原版／S1／S2 各 14 個。答案在 `session/`。
- **`compare.py`**：在同一批 module 上比較 Haiku 和 Opus 級 annotator 的 view（ID 相同可以直接比）。
- **`calibrate --gold gold`**：拿 draft gold 評分。
- **`perturb_compare.py physical --model claude-haiku-session`**：Haiku 對同一電路的亂改版是否給出一樣的答案。

## Pass / abandon criteria
- 合法：validator 通過率 100%。
- 一致：structure 模式和 Opus 的 MEDIUM F1 ≥ 0.85。

## Results

**合法性**：54/54 通過 validator。
- 約一半單元第一次就過，其餘需要 1–2 次修正，大多是證據行號寫錯。
- 也就是說，validator 的退回重做是弱模型能產出合法結果的關鍵，而它確實有效。

**和 Opus 級 annotator 比**（57 個 module，F1；兩邊用同一種模式）：

| 模式 | HIGH | MEDIUM |
|---|---|---|
| tier | 0.796 | 0.840 |
| score | 0.803 | 0.842 |
| **structure** | **0.878** | **0.891** |

- 如果參考答案固定用 Opus 的預設輸出，Haiku 在 structure 模式下是 HIGH 0.814、MEDIUM 0.859。
- role 一致度 0.767。
- Haiku 的 MEDIUM 平均選 7–8 個 anchor，Opus 是 6 個，也就是會多選。
- 參考基準：兩位 Opus 級 annotator 互相比，HIGH 0.847、MEDIUM 0.962（這是另一組題目）。

**對 draft gold**：

| | HIGH recall／precision | MEDIUM recall／precision | MEDIUM role |
|---|---|---|---|
| Opus, score | 0.65／1.00 | 0.91／0.98 | 0.92 |
| Haiku, tier | 0.62／0.95 | 0.94／0.90 | 0.82 |
| Haiku, structure | 0.69／1.00 | 0.92／0.93 | 0.81 |

**跨改寫穩定度**（亂改 benchmark，F1）：

| | S1 HIGH | S1 MEDIUM | S2 HIGH | S2 MEDIUM |
|---|---|---|---|---|
| Opus, score | 0.940 | 0.953 | 0.786 | 0.832 |
| Haiku, tier | 0.748 | 0.839 | 0.776 | 0.808 |
| Haiku, structure | **0.898** | **0.857** | 0.764 | 0.784 |

另外試過提高分數門檻來濾掉多選的 anchor，MEDIUM 只從 0.880 升到 0.892。門檻是在這批資料上挑的，有過擬合風險，所以不採用。

## Conclusion
- 弱模型的 HIGH 主要失準在「重要度判斷」，量化分數（structure 模式）可以補回來：
  - 與 Opus 的 HIGH 一致度 0.80 → 0.88；
  - 在 gold 上的 HIGH precision 回到 1.00；
  - 扁平改寫（S1）的 HIGH 穩定度 0.75 → 0.90。
- 結構分數補不了的是兩件事，這也是之後要補強的方向：
  - **role**：Haiku 一致度 0.77，Opus 約 0.92；
  - **多選 anchor**：Haiku 的 MEDIUM precision 約 0.84。
- 建議做法：
  - 弱 annotator 或 student 用 `--importance structure`，再加上 k=2 獨立投票（Haiku 的投票效果尚未實測）；
  - 量產仍以強 teacher 為主，再 distill。
