# e4_fsm_semantic

**Owner:** L1（薛晏閎）　**Date:** 2026-10-02

## Hypothesis
在一般 RTL 上，語意（執行式）FSM 引擎應該和語法抽取一致，不會有 mismatch；同時不會把 CSR、index、valid pipeline 誤認成 FSM。

## Measurement
在 `layers/l1_extract/` 下執行；corpus 要先用 `scripts/fetch_corpus.py` 抓下來。

- 語法 FSM 的結構檢查：
  ```bash
  python experiments/e4_fsm_semantic/check_fsm.py <manifests>
  ```
- 語意引擎單獨掃描，看抓到哪些 FSM 和多少誤判：
  ```bash
  python experiments/e4_fsm_semantic/fsm_semantic_sweep.py <manifests>
  ```
- hybrid 的 `semantic_check` 分布：
  ```bash
  python experiments/e4_fsm_semantic/fsm_consistency.py <manifests>
  ```

## Pass / abandon criteria
- 通過：mismatch = 0，且 semantic-only 的結果經人工判斷是合理的。

## Results
- 262 個設計中有 52 個語法 FSM：47 個 consistent、5 個 consistent-subset、0 個 mismatch。
- semantic-only 有 2 個，經人工判斷都合理。
- 誤判從 9 個降到 2 個，靠的是三條規則：要有分岔、不能是整值資料載入（partial-read 不算）、平均後繼數 ≤ 3.5。
- 詳見 `docs/VALIDATION.md` R3.2。

## Conclusion
已併入 `src`；`--target fsm` 預設採用 hybrid。
