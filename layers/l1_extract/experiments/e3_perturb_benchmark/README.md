# e3_perturb_benchmark

**Owner:** L1（薛晏閎）　**Date:** 2026-10-02

## Hypothesis
同一個電路被亂改寫，但功能不變時（名稱、FSM 編碼、always 拆合、模組階層全換），Stage 1 仍然應該抽出相同或相近的資訊：FSM 狀態圖要同構，anchor 要對應到相同的物理訊號。

## Measurement
- `data/designs.json`：14 個原始設計，記錄 reset 訊號、電位和參數。
- `data/<design>/{S1,S2}/`：改寫結果和 `mapping.json`（新舊名稱對照）。規則見 `data/REWRITE_RULES.md`。
- 指令（在 `layers/l1_extract/` 下執行；需要 Yosys，Windows 上用 WSL）：
  - 嚴格 reset 模式下的 bounded 等價檢查：
    ```bash
    python experiments/e3_perturb_benchmark/perturb_equiv.py
    ```
  - FSM 同構比對（不使用名稱對照表）：
    ```bash
    python experiments/e3_perturb_benchmark/perturb_compare.py fsm
    ```
  - teacher anchor 的物理訊號比對，需要 Run Store 裡已經有 e2 匯入的標註：
    ```bash
    python experiments/e3_perturb_benchmark/perturb_compare.py physical
    ```

## Pass / abandon criteria
- 前提：改寫必須 28/28 等價。
- 通過：FSM 同構 ≥ 90%，S1 的 MEDIUM recall ≥ 0.9。

## Results
- 等價檢查 28/28 PASS（26 份跑 12 cycle，ugly_mul 跑 6 cycle）。
- FSM：語法抽取 0/18 → 語意抽取 18/18。
- Anchor MEDIUM recall：S1 1.000，S2 0.95–0.97。
- 結果檔：`data/equiv_results.json`、`fsm_compare.json`、`anchor_compare_*.json`。詳見 `docs/VALIDATION.md` R3.2。

## Conclusion
語意 FSM 引擎已併入 `src/rtl2d_l1/frontend/fsm_semantic.py` 和 `fsm_hybrid.py`（SPEC v1.5 §6c）。
