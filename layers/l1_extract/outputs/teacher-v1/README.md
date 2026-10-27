# L1 teacher 輸出 `teacher-v1`（2026-10-03）

這是 L1（Stage 1）以 teacher 模式產生的結果，共 690 個設計。teacher 是 Opus 級的 Claude session，資料直接從 Run Store 取出，沒有額外呼叫 LLM。
- module 結果：teacher 1,021 個，heuristic 315 個。heuristic 的這些都是 trivial module（entity ≤ 4，或沒有狀態也沒有子模組），本來就不呼叫 LLM。
- 輸出格式還不是正式的 Selection 契約（契約仍是草稿，見 `docs/adr/0002`）；這裡是給 L2 先用的資料。

## 路徑
所有路徑都相對於 `layers/l1_extract/`：
- 自寫的範例在 `examples/rtl/`；
- 亂改 benchmark 在 `experiments/e3_perturb_benchmark/data/`；
- 第三方 RTL 在 `data/rtl/<repo>/`（snapshot，已進版控）。

也就是說，clone repo 之後不需要另外下載，就能用 `file` 和 `lines` 對回 RTL 原始碼。

## 檔案
| 路徑 | 內容 |
|---|---|
| `index.json` | 所有設計的清單：top、module 數、teacher／heuristic 各幾個、block 數 |
| `<design>/blocks.json` | **主要檔案**：把每個 module 的 group 展開成 block，詳見下節 |
| `<design>/fsm.json`、`fsm/*.mmd` | FSM：狀態、reset state、帶條件的轉移；Mermaid 圖；`semantic_check` 交叉驗證結果 |
| `raw.tar.gz` | 原始檔：每個設計的 `anchors.json`（MEDIUM view）、`anchors_full.json`（所有 tier）、`entities/<module>.json`（entity table） |

## `blocks.json`（schema `l1-blocks-v1`）
```text
{design, tops, taxonomy_version,
 modules: {<module>: {
   source: teacher | heuristic,
   canonical_instance, file, lines: [start, end], summary,
   blocks: [{name, kind, description,
             anchors: [{id, name, role, importance, score, struct_score, trace, why, lines}],
             instances: [{id, instance, module}],   // 這個 block 包含的子模組 instance
             members:   [{id, name, kind}]}],       // 同概念的其他訊號（例如 _next 那一份）
   ungrouped_anchors: [...],                        // 不屬於任何 block 的 anchor
   instances_not_in_a_block: [{id, instance, module}],
   interfaces: [{name, protocol, direction, member_ids, members}]}}}
```
- `kind`：block 類型，取自 roles-v2 的 GroupKind，例如 CONTROLLER、DATAPATH、BUFFER、ARBITER、SERIALIZER、INTERFACE_ADAPTER。
- `score`：0–100 的量化重要度，HIGH ≥ 70、MEDIUM ≥ 40（SPEC §4.6）。只想要簡化圖時，可以只取 `score >= 40` 的 anchor。
- `lines`：證據行號，是原始 RTL 檔（`file`）的絕對行號。
- 階層：父 module 的 block 透過 `instances` 指向子 module，子 module 本身也在 `modules` 裡、有自己的 block。

## 設計來源
- examples：自己寫的測試設計。
- `orig_*`／`S1_*`／`S2_*`：亂改等價 benchmark。同一個電路有原版、扁平亂改、階層亂改三版，等價性已用 Yosys 驗證。可以拿來測 L2 對寫法的穩健度。
- 開源 repo：verilog-axis／uart／i2c／axi／ethernet／wishbone、wb2axip、serv、darkriscv、biriscv、common_cells、picorv32／picosoc、RTLLM、VerilogEval。RTL 原始碼用 `scripts/fetch_corpus.py` 下載，commit 已固定。

## 重新產生
在 `layers/l1_extract/` 底下執行：
```bash
python -m rtl2d_l1.cli run --manifest <M> --mode teacher --store-only --model claude-session --effort session --target block fsm --out runs/teacher_out
python scripts/export_teacher_outputs.py runs/teacher_out outputs/teacher-v1
```
