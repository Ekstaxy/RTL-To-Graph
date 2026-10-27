# e2_session_annotation

**Owner:** L1（薛晏閎）　**Date:** 2026-10-01 – 2026-10-02

## Hypothesis
不打 API，改由 Claude session 加 subagent 當 teacher，就能用和 API 版完全相同的 prompt、validator 和 Run Store 產生合格的標註與 SFT 資料。另外測試「多輪 self-audit」能不能降低單次標註的幻覺。

## Measurement
- `session/`：各 wave 的 prompt（`*.prompt.md`）和答案（`*.answer.json`、`*.passN.json`）。
  - w1–w2e：roles-v1／v2 的 examples、RTLLM、VerilogEval、picorv32；
  - w3blind：改名盲測；
  - w4：draft gold；
  - w5–w6c：perturb benchmark、新 corpora、多輪。
- `MULTIPASS_PROTOCOL.md`：多輪協定。
- `check_answer.py`：annotator 交件前的自我驗證。
- 匯入方式（在 `layers/l1_extract/` 下執行）：
  ```bash
  python -m rtl2d_l1.cli batch plan --manifest M --units-dir D
  python -m rtl2d_l1.cli batch ingest-session runs/batches/plan_*.json
  ```

## Pass / abandon criteria
- 通過：validator 通過率 100%，且 annotator 間 MEDIUM 一致度 ≥ 0.85。
- 多輪的通過條件：一致性或 recall 有可量測的提升。

## Results
- 第一、二輪 235 筆、第三輪 94 筆紀錄，validator 100% 通過。annotator 間 MEDIUM 一致度 0.93，盲測 robustness 0.88。
- 多輪審查改動了 3.7% 的 anchor，但沒有新增任何 anchor。一致性沒有提升，HIGH 0.948 → 0.896。
- 詳見 `docs/VALIDATION.md` §3 和 R3.3。

## Conclusion
- Session 標註：保留，作為沒有 API key 時的 teacher。
- 多輪：放棄當預設（`--passes` 預設 1）；要更高可信度時，改用兩個 annotator 獨立標註再投票（k=2）。
