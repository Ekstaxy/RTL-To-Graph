# Stage 1 架構規劃：Semantic Anchor Extraction（API-first → Distill-ready）

> **注意**：本文件是規劃階段的討論稿。具體決策（schema、taxonomy、front-end、teacher、student base model、trace 演算法）以 [SPEC.md](SPEC.md) 為準；兩者不一致時以 SPEC 為準。

> 對應計畫書「第一階段：語意萃取與抽象化模組開發」。
> 一句話定位：**EDA front-end 負責「真相」，LLM 只負責「哪裡重要」，graph algorithm（Stage 2）負責「連到哪」。**
> 版本：v0.1（2026-10-01）

---

## 0. 結論先講

1. **同意「初期直接上 API 大模型、結果全部存檔、之後再 distill」**。這是現在最對的順序，理由見 §1。
2. 但有三個前提要先講清楚，否則之後 distill 會白做：
   - **Stage 1 的 I/O contract 要從第一天就凍結成「student 也吃得下」的格式**（輸入 = RTL + front-end entity table，輸出 = 只選 entity ID 的 JSON）。API 只是暫時的 backend。
   - **log 的是「訓練樣本」不是「聊天紀錄」**：要記 prompt 版本、entity table 版本、模型、驗證結果、Stage 2 回饋。見 §7。
   - **API 預算（計畫書寫 3000 元 ≈ US$95）只夠做 1–3k 筆 teacher label**，不夠到 10k–20k。所以 API 的角色是「做 gold set + seed set + 定義 label」，量產要靠 bootstrapping 或便宜 teacher。見 §9。
3. 時程現實：計畫書第一階段是九月，現在已經 10/1。**正因為來不及先 train 再用，API-first 才是唯一能讓 Stage 2 下週就有輸入可以用的路。**

---

## 1. 為什麼 API-first 是對的（以及它的邊界）

| 面向 | 先 fine-tune 小模型 | 先用 API 大模型 |
|---|---|---|
| 拿到第一版可用輸出 | 要先有 label → 雞生蛋 | 今天就能跑 |
| 「什麼叫 anchor」的定義 | 會被訓練資料凍結，改定義要重標重訓 | 改 prompt 就好，可以快速迭代 taxonomy |
| Stage 2 開發 | 要等 Stage 1 model | 馬上有真實 anchor 可以 trace |
| 成本 | GPU 時間 | 按 token 付費，預算有限 |
| 私有 RTL / 離線 / 大量 | ✅ | ❌ 業界 RTL 不能外送 → **這是 distill 真正的商業理由** |

GPT 對話裡最大的 research risk 是「anchor 的定義本身不唯一」。這個風險**只能靠快速迭代 prompt + 看 Stage 2 trace 結果**來收斂，而這正是 API 最擅長的。等定義穩定了，distill 只是把它固化成便宜、可離線的模型。

**邊界**：API 版本永遠只是 teacher + baseline。最後要 demo 的「cost down、可離線、可處理機密 RTL」一定要靠 student。

---

## 2. 整體 Pipeline

```
                 RTL project (.v / .sv, filelist, defines)
                               │
              ┌────────────────▼────────────────┐
              │  [A] Deterministic Front-end    │  pyslang (+ Yosys 選配)
              │  parse / elaborate / hierarchy  │
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │  [B] Entity Table Builder       │  每個 signal/reg/mem/inst 給穩定 ID
              │  + cheap structural features    │  (kind, width, dir, fanin/out, FSM candidate…)
              └────────────────┬────────────────┘
                               │  per-module work unit (bottom-up)
              ┌────────────────▼────────────────┐
              │  [C] Anchor Selector (LLM)      │  v1 = API teacher
              │  input : RTL + entity table     │  v2 = distilled student
              │  output: anchors + groups (IDs) │  ← 同一個 I/O contract
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │  [D] Validator                  │  ID 存在？role 與結構矛盾？
              │  (deterministic, 可 retry)      │  → reject / retry / downgrade
              └────────────────┬────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │  [E] Aggregator / Voter         │  k 次取樣投票 → confidence
              └───────┬──────────────────┬──────┘
                      │                  │
         anchors.json ▼                  ▼  全部寫進 Run Store
              ┌───────────────┐   ┌──────────────────────────┐
              │ Stage 2 trace │──►│ [F] Run Store (dataset)  │
              │ (下一個人)     │   │ request/response/valid/  │
              └───────────────┘   │ trace feedback/human fix │
                                  └──────────────────────────┘
                                             │
                                             ▼
                                    之後 distill student
```

對應計畫書的「兩張清單」：
- 清單一「AI 覺得重要的訊號」= `anchors`
- 清單二「覺得需要模組化的」= `groups`（latent functional blocks，只列 anchor IDs，不要求邊界完整，邊界由 Stage 2 trace 補）

---

## 3. [A] Front-end：要不要 EDA？要不要合成？

**要 EDA front-end（parse + elaborate），不要完整 synthesis。**

| 選項 | 用途 | 建議 |
|---|---|---|
| **pyslang**（slang 的 Python binding） | SV-2017 parse/elaborate、parameter/generate/package 都處理、`pip install` 就能在 Windows 跑 | **Stage 1 主力**。entity table 從這裡出 |
| Yosys（OSS CAD Suite）+ `yosys-slang` plugin | `proc` 後的 RTLIL / `write_json`、`fsm_detect` 可標 FSM state reg | 選配：用來產 feature（FSM candidate、mux selector），Stage 2 建 dependency graph 很可能會用 |
| Surelog + UHDM | 也可，但安裝重、Windows 不友善 | 不建議當第一選擇 |
| 自己 regex / 手寫 parser | — | **不要**，會死在 macro / generate / parameter |

**跑到哪裡停**：elaborate → (`proc`, `opt_clean` 等輕量) 為止。**不要** `synth`、`abc`、`flatten`、tech mapping —— 會把人類可讀的架構線索最佳化掉。

> Front-end 跟 Stage 2 共用：entity ID 的命名規則兩邊必須一致，建議由 Stage 1 擁有 entity table 的定義，Stage 2 直接引用。

---

## 4. [B] Entity Table

LLM **只能從這張表選 ID**，從結構上杜絕幻覺訊號（對應計畫書「100% 零幻覺」目標）。

每列欄位（v1）：

```json
{
  "id": "m3.E017",
  "module": "cache_ctrl",
  "name": "state_q",
  "hier_path": "top.u_cache.state_q",
  "kind": "reg",              // port | reg | net | mem | inst | param
  "dir": null,                // in | out | inout | null
  "width": 3,
  "src": "cache_ctrl.sv:88",
  "driven_in": "always_ff",   // always_ff | always_comb | assign | port | inst
  "fanin": 6,
  "fanout": 11,
  "feat": {
    "fsm_candidate": true,     // Yosys fsm_detect 或 self-loop + case 判斷
    "enum_typed": true,
    "used_as_mux_sel": true,
    "name_hint": ["state"]     // valid/ready/req/ack/en/stall… 名稱 heuristic
  }
}
```

設計要點：
- **ID 要穩定**：同一份 RTL 重跑必須得到同樣 ID（用 `module + 宣告順序` 或 hash），不然 log 下來的 label 會對不回去。
- **名稱 heuristic 只是 feature，不是答案**：augmentation 會改名（§8），模型要能在名字被混淆時仍靠結構判斷。
- 表太大時（數百個 temp wire）：先用規則濾掉 `fanout==1 && driven_in==assign && 無 name_hint` 之類的純中間線，但**保留在 store 裡**，Stage 2 trace 還要用。

---

## 5. [C] Anchor Selector：Prompt 與 Output Schema

### 5.1 工作單位：per-module, bottom-up

大型設計不要一次丟整個 SoC：

1. 依 hierarchy 由葉往根處理。
2. 每個 module 一次 call，輸入 = 該 module 的 RTL + entity table + **子模組的已完成摘要**（子模組的 anchors / groups / ports role，不是子模組原始碼）。
3. 單一 module 過大（> ~30k tokens）才切 chunk（以 always block 為單位切），最後 merge。

這同時解決 context 長度、成本，也讓 student 之後面對的是「一個 module」這種固定大小的任務。

### 5.2 Output schema（用 structured outputs 強制）

```json
{
  "abstraction_level": "MEDIUM",
  "anchors": [
    {
      "id": "m3.E017",
      "role": "FSM_STATE",
      "importance": 0.97,
      "trace": "control_backward",
      "why": "main controller state; drives stall_o and refill_req"
    },
    { "id": "m3.E002", "role": "HANDSHAKE_VALID", "importance": 0.95, "trace": "interface",        "pair": "m3.E003" },
    { "id": "m3.E003", "role": "HANDSHAKE_READY", "importance": 0.95, "trace": "interface",        "pair": "m3.E002" },
    { "id": "m3.E041", "role": "STORAGE",         "importance": 0.85, "trace": "data_backward" }
  ],
  "groups": [
    {
      "name": "refill_control",
      "kind": "CONTROLLER",
      "anchors": ["m3.E017", "m3.E022", "m3.E031"],
      "confidence": 0.8
    }
  ],
  "port_roles": [
    { "id": "m3.E002", "role": "HANDSHAKE_VALID", "bundle": "cpu_req" }
  ]
}
```

### 5.3 Role taxonomy（v1 固定 enum，之後改要升版號）

| 類別 | role |
|---|---|
| 控制 | `FSM_STATE`, `CONTROL_FLAG`（stall/flush/busy/pending）, `ENABLE`, `MUX_SELECT` |
| 介面 | `HANDSHAKE_VALID`, `HANDSHAKE_READY`, `REQ`, `ACK`, `INTERFACE_DATA`, `INTERFACE_ADDR` |
| 資料路徑 | `DATAPATH_MAJOR`, `PIPELINE_REG`, `ACCUMULATOR` |
| 儲存 | `STORAGE`（mem/array/regfile）, `FIFO_PTR`, `COUNTER` |
| 其他 | `CLOCK_RESET`（通常要排除，但標出來）, `CONFIG_REG`, `OTHER` |

`trace` hint enum：`control_backward`, `data_backward`, `forward`, `interface`, `none`。

Group `kind` enum：`CONTROLLER`, `DATAPATH`, `ARBITER`, `BUFFER`, `COUNTER_TIMER`, `DECODER`, `SERIALIZER`, `PIPELINE_STAGE`, `MEMORY`, `INTERFACE_ADAPTER`, `OTHER`。

**Taxonomy 是整個專案最該花時間討論的東西**（三人要對齊），它決定 label 一致性。enum 寧可少而清楚。

### 5.4 Prompt 原則

- System prompt 固定、放最前面（可 prompt caching）：role 定義 + 每個 role 2–3 個正反例 + 規則「只能選表中 ID」「寧可少而準，Stage 2 會 trace 補完」「不要被命名騙，以 driven_in / fanout / 結構為準」。
- **Precision 優先於 recall**：因為有 trace engine 往外擴，漏一個中間訊號沒差，選錯一個 anchor 會把 trace 帶歪。但**concept-level recall 要高**（每個功能概念至少要有一個 anchor）。
- 加入 `abstraction_level`（HIGH / MEDIUM / LOW）參數，對應計畫書「使用者要求不同複雜度」，也減少 label 不一致。
- `why` 欄位限一句話：省 output token，也方便人工審查與之後 distill（可選擇要不要讓 student 學 rationale）。

### 5.5 Teacher 設定建議

- 開發期 / gold set：最強的模型（如 Claude Opus 5.5），effort `medium` 起跳，量 `high` 是否值得。
- 量產期：先在 gold set 上量 Sonnet 5.5 / 較低 effort 能不能維持品質，**以數據決定**，不要憑感覺降級。
- 一律走 **Batch API**（不急的資料生成，打五折）+ **prompt caching**（system prompt 與 taxonomy 不變）。

---

## 6. [D] Validator 與 [E] Voting

### 6.1 Deterministic checks（失敗就 retry，最多 2 次，再失敗丟棄並記錄）

| 檢查 | 規則 |
|---|---|
| ID 存在 | 所有 `id` ∈ entity table |
| role ↔ 結構 | `FSM_STATE` 必須 `driven_in=always_ff`；`HANDSHAKE_*` 若為 port，方向要合理；`STORAGE` 應為 mem/array 或寬 reg |
| 非死線 | anchor 不能是 constant-only 或 fanout=0 的非輸出 |
| pair 一致 | valid/ready 的 `pair` 要互相指 |
| group 合法 | group 內 anchors 都在 anchors 清單中 |

### 6.2 Self-consistency voting

同一 module 跑 k=3 次（不同 prompt 變體或順序打亂 entity table），統計每個 ID 被選中的頻率與 role 一致性：

- 3/3 → high confidence
- 2/3 → medium
- 1/3 → low（保留在 log，預設不送 Stage 2）

好處：(1) 免費得到 confidence；(2) 之後 distill 時可以當 **soft label**；(3) 2/3 以下的樣本是人工審查的優先清單。

> 預算不夠時，只對 gold set 和「validator 曾 retry 過」的樣本做 k=3，其他 k=1。

---

## 7. [F] Run Store：為 distill 而設計的 log

**原則：每一筆都要能直接變成一個 SFT 樣本，而且能追溯是怎麼產生的。**

儲存：JSONL（append-only）+ 一個 SQLite/Parquet 索引。原始 RTL 以 content hash 去重。

每筆 record：

```json
{
  "run_id": "2026-10-03T14:22:05Z_7f3a",
  "design": { "source": "picorv32", "license": "ISC", "file_hash": "sha256:…", "module": "picorv32_pcpi_mul" },
  "frontend": { "tool": "pyslang", "version": "x.y", "entity_table_version": "v1", "entity_table_hash": "…" },
  "variant": { "augmentation": "rename+expr_split", "parent_run": "…" },
  "request": {
    "prompt_version": "anchor-v0.3",
    "taxonomy_version": "roles-v1",
    "model": "claude-opus-5-5",
    "effort": "medium",
    "abstraction_level": "MEDIUM",
    "input_tokens_est": 6100
  },
  "response": { "raw": "…", "parsed": { "anchors": [], "groups": [] } },
  "usage": { "input": 6050, "cache_read": 2900, "output": 4200, "usd": 0.051, "batch": true },
  "validation": { "passed": true, "retries": 0, "errors": [] },
  "vote": { "k": 3, "agreement": 0.86 },
  "stage2_feedback": { "trace_coverage": 0.91, "reduction": 0.68, "notes": null },
  "human": { "reviewed": false, "corrected": null, "reviewer": null }
}
```

關鍵：
- **`prompt_version` / `taxonomy_version` 必記**：之後只拿「同一版 taxonomy」的資料去訓練，舊版要嘛丟、要嘛轉換。
- **`stage2_feedback` 回填**：Stage 2 trace 後覆蓋率高的 label = 好 label。這是計畫書「生成 → 驗證 → 修正」閉環的資料面，也是之後 filter distill 資料的依據。
- **`human.corrected`**：人工修正過的樣本權重最高，也是 eval 的來源。
- 記 `usd`：隨時知道預算燒到哪。

---

## 8. 資料來源與 Augmentation

### 8.1 RTL 來源（先挑授權清楚的開源）

- 小型 / 有 spec：RTLLM、VerilogEval 這類 spec→RTL benchmark（spec 只給 teacher 當 privileged info，student 推論時看不到）
- 中型真實設計：picorv32、ibex（lowRISC）、PULP 系列元件、OpenCores 的 UART/SPI/I2C/FIFO
- 壓力測試（計畫書寫的）：RISC-V core、ML accelerator
- 每筆記錄 license，之後開源 dataset 才不會出事

### 8.2 Augmentation（也是 robustness eval）

在 **front-end 之後**做語意保持的改寫，label 透過 entity 對應自動搬移，不需要重新呼叫 teacher：

| 改寫 | 測什麼 |
|---|---|
| 訊號改名（`state_q` → `r17`） | 不靠名字 |
| 插入 alias / 拆 expression | 不被中間線騙 |
| always block 重排、合併 | 不靠位置 |
| 加 wrapper module / 打平 hierarchy | 跨層級 |
| 同 spec 不同實作（comb / iterative / pipelined multiplier） | **不同架構要給不同 anchor**（GPT 提到的好例子，拿來當 eval case） |

> 改名類 augmentation 的 label 可以直接 map，最省錢；「同 spec 不同實作」需要重新 label。

---

## 9. 預算與量：3000 元能做什麼

以 2026-09 Anthropic 價格估算（Batch 五折；1 USD ≈ 31.5 TWD，**皆為估計，實際以 usage 為準**）。
假設每個 module call：input ~6k tokens（其中 ~3k system prompt 可 cache）、output ~4.5k（含 thinking + JSON）。

| Teacher | 單次 call 約 | US$95 可跑 call 數 | k=3 voting 的設計數 |
|---|---|---|---|
| Opus 5.5（batch） | ~US$0.055 | ~1,700 | ~570 |
| Sonnet 5.5（batch） | ~US$0.028 | ~3,400 | ~1,100 |
| Haiku 4.5（batch） | ~US$0.014 | ~6,800 | ~2,200 |

**Output token 是大頭**，所以：rationale 一句話、effort 量測後再定、group 不要寫長描述。

### 建議分配

| 用途 | 量 | Teacher | 預估 |
|---|---|---|---|
| Prompt / taxonomy 迭代 | ~150 calls | 最強模型，非 batch | ~15% 預算 |
| **Gold eval set**（人工審過） | 40–60 modules，k=3 | 最強模型 | ~10% |
| Seed training set | 1,000–2,000 modules | gold set 上驗證過、最便宜且品質持平的模型 | ~65% |
| 保留 | — | — | ~10% |

**要到 10k–20k 筆，API 預算不夠**，三條路（可並行）：
1. **Augmentation 放大**：1.5k 原始 label × 3–5 個改名/改寫變體 → 5k–7k 樣本，幾乎零成本。
2. **Bootstrapping / active learning**：用 seed set 先 LoRA 一版 student → student 標大量資料 → 只把「student 低信心、或 Stage 2 trace 覆蓋率低」的樣本送 teacher 複審。teacher 只花在難樣本上。
3. **Open-weight teacher 做量產**：本地或便宜推論服務跑大型開源 coder 模型，用 gold set 量它跟 API teacher 的一致率，夠高就拿來量產。

---

## 10. Distill（之後的 Stage 1 v2）

**開始條件**（不要太早）：
- taxonomy 已凍結一個版本至少一週沒改
- 同一版 taxonomy 下有 ≥1,000 筆通過 validator 的 label
- gold set 上 API teacher 的指標已經是你們能接受的上限

**做法**：
- Student：Qwen2.5-Coder 3B / 7B（或當時最新的同級 open coder model）+ LoRA；1.5B 當 baseline。3B 若達到 7B 的 ~97% 就選 3B。
- 輸入輸出**與 API 版完全相同**（RTL + entity table → JSON with IDs），推論時用 constrained decoding（JSON schema / grammar）保證格式，ID 也可限制在表內。
- 訓練資料過濾：validator pass ∧ vote agreement ≥ 2/3 ∧（有的話）stage2 trace coverage ≥ 門檻；human-corrected 樣本加權。
- 對比報告：student vs teacher vs 純 heuristic baseline，在 gold set + augmentation set 上。

**⚠️ 授權要先查**：多數商用 LLM API 的服務條款對「用輸出訓練模型」有限制（通常針對開發競爭性模型）。一個只做 RTL anchor 選擇的窄任務模型很可能不構成競爭，但**請在開始 distill 前讀一次你們實際使用的 API 的條款**；若有疑慮，distill 資料改以 open-weight teacher 產生的 label 為主，API label 只用在 eval。

---

## 11. Evaluation（Stage 1 自己的驗收）

Gold set 由三人各自標註後討論定稿（同時檢查 taxonomy 是否清楚：三人一致率太低代表定義有問題）。

| 指標 | 定義 | 目標（v1） |
|---|---|---|
| **Concept recall** | gold 的功能概念（FSM、每組 handshake、主要 storage…）至少命中一個 anchor 的比例 | ≥ 90% |
| Anchor precision | 選出的 ID 中 gold 認可的比例 | ≥ 80% |
| Role accuracy | 命中的 anchor 中 role 正確的比例 | ≥ 85% |
| Hallucination | 不存在的 ID | **0**（結構上保證） |
| Rename robustness | 改名變體 vs 原始的 concept recall 差 | 下降 ≤ 5pt |
| Trace coverage（與 Stage 2 合測） | anchors 經 trace 後覆蓋 gold 架構相關區域的比例 | 先量 baseline |
| 成本 | 每 module 平均 US$ / token | 記錄 |

**一定要有 heuristic baseline**：名字 regex（valid/ready/state…）+ Yosys `fsm_detect` + port 全選。LLM 要明顯贏過它，特別是在改名變體上，才能證明 Stage 1 用 AI 的價值（期末報告/評審也會問）。

---

## 12. 時程（從 10/1 起，約兩週）

| 天 | 產出 |
|---|---|
| D1–2 | pyslang front-end → entity table（含穩定 ID）；選 10 個設計跑通 |
| D2–3 | **三人對齊 taxonomy v1**；標 10 個 module 的 mini gold |
| D3–4 | prompt v0 + structured output + validator；Run Store schema 定案 |
| D5 | heuristic baseline + eval script；第一版數字 |
| D6–7 | prompt 迭代（看 mini gold 錯誤）；**交第一批 anchors.json 給 Stage 2** |
| D8–10 | 擴到 40–60 module gold set；k=3 voting；比較不同 teacher / effort 的品質與成本 |
| D11–14 | batch 跑 seed set；改名 augmentation；Stage 2 feedback 回填欄位接上 |

D7 就交付給 Stage 2 是重點：越早拿到 trace 回饋，越早知道 anchor 定義對不對。

---

## 13. 風險與對策

| 風險 | 對策 |
|---|---|
| Anchor 定義不唯一，label 不一致 | 固定 enum + abstraction_level + 三人一致率檢查 + 以 Stage 2 trace 結果作為客觀回饋 |
| 被命名騙（名字叫 `valid` 但不是 handshake） | entity table 提供結構 feature；rename augmentation eval |
| 大型設計超出 context / 成本爆 | per-module bottom-up + 子模組摘要；濾除純中間線 |
| API 預算不夠量產 | §9 三條路；output token 控制 |
| Front-end 吃不下某些 SV 語法 | 記錄失敗設計當 known-limitation 清單；先支援 synthesizable subset |
| Distill 授權問題 | §10 先查條款；open-weight teacher 備案 |
| Stage 1/2 介面漂移 | entity ID 規則與 `anchors.json` schema 由 Stage 1 擁有並版本化，改版要通知 |

---

## 附錄：交給 Stage 2 的介面（`anchors.json`）

```json
{
  "schema_version": "anchors-v1",
  "design": "picorv32",
  "entity_table": "entity_table.v1.json",
  "abstraction_level": "MEDIUM",
  "modules": {
    "picorv32_pcpi_mul": {
      "anchors": [ { "id": "…", "role": "…", "importance": 0.0, "trace": "…", "confidence": "high" } ],
      "groups":  [ { "name": "…", "kind": "…", "anchors": ["…"], "confidence": 0.0 } ],
      "port_roles": [ { "id": "…", "role": "…", "bundle": "…" } ]
    }
  }
}
```

Stage 2 回傳（寫回 Run Store `stage2_feedback`）：每個 module 的 trace coverage、reduction ratio、被 trace 補進來但 Stage 1 沒選的高重要性節點（→ 可能是漏標，進人工審查佇列）。
