# Stage 1 SPEC（凍結版）— RTL Semantic Anchor Extraction

| 項目 | 值 |
|---|---|
| Spec 版本 | `stage1-spec-v1.7`（v1.7 = 前端修正（無效 always 區塊的 syntax fallback、reset 誤判）+ 重要度 v2；v1.6 = 量化重要度分數 0–100 + `--importance`；v1.5 = 語意 FSM 抽取 + 證據行號 + 多輪選項；v1.4 = `--target` + FSM）；前版 `stage1-spec-v1.3`（2026-10-01；v1.3 = roles-v2 + 前端 reset/FSM 修正；v1.2 = teacher 固定 LOW + Controls；v1.1 = scored slicing） |
| Taxonomy 版本 | `roles-v2` |
| Entity table 版本 | `entities-v1` |
| Prompt 版本 | 見 `src/rtl2d_l1/llm/prompt.py::PROMPT_VERSION` |
| 擁有者 | Stage 1（本 repo）。Stage 2 只讀，不改 |

> 規則：本文件中標 **[FROZEN]** 的部分，改動必須升版號（minor = 加欄位/加 enum 值；major = 改語意/刪欄位），並在 `docs/CHANGELOG.md` 記錄。舊版 label 不得混入新版訓練資料。

---

## 1. 任務定義 [FROZEN]

**輸入**：一個 module（definition）的
1. 原始 RTL 文字（附行號），
2. front-end 產生的 entity table（§3），
3. 子模組的已完成 annotation 摘要（bottom-up 時才有）。

Teacher 另可拿到 **privileged design spec**（如 RTLLM / VerilogEval 的自然語言規格）；它只附在 teacher 的輸入，不進 Run Store 的 student 輸入，也不進 SFT 樣本。

**輸出**：`ModuleAnnotation`（§4），只能引用 entity table 中存在的 ID。

**不做**：不產生連線、不產生完整 block diagram、不改寫 RTL。連線與完整性由 trace engine（§6）負責。

**設計原則**
- LLM 不負責 correctness；front-end 建立 truth；LLM 給 semantic priority；graph algorithm 負責 completeness。
- 每個 anchor 必須 **grounded**：ID 存在且 `name` 與 ID 對得上（雙欄位交叉驗證，防止 ID 抄錯）。
- **Precision 優先於 entity-level recall，但 concept-level recall 必須高**：每個功能概念至少一個 anchor。

---

## 2. 前端（EDA）決策 [FROZEN]

| 決策 | 內容 |
|---|---|
| Parser / elaborator | **slang（pyslang 12.x）**：完整 IEEE 1800-2017/2023、parameter/generate/package/interface 都能 elaborate，Windows/Linux pip 直接安裝 |
| 編譯選項 | `--disable-instance-caching`（每個 instance 有獨立 body，hier path 才正確）、`--ignore-unknown-modules`（缺 IP/blackbox 時仍可分析） |
| Dependency graph | 由 elaborated AST **自行建構**（不經 synthesis），保留原始名稱與 procedural 控制結構 |
| Synthesis | **不做**。不跑 `synth`/`abc`/`flatten`，避免架構線索被最佳化掉 |
| Yosys | 選配交叉驗證（WSL 內 `yosys`）：`proc; fsm_detect` 比對 FSM 偵測；不在主流程上 |

### 2.1 Typed dependency graph [FROZEN]

節點 = 每個 elaborated value symbol（net / variable / 埠的內部 symbol），以 **hierarchical path** 為 key（例：`top.u_cache.state_q`、`top.g[1].r`）。

邊 `src → dst`，型別：

| type | 意義 | 例 |
|---|---|---|
| `DATA` | dst 的值由 src 計算而來 | `y = a + b` |
| `CONTROL` | src 出現在決定 dst 是否/如何被賦值的條件中（if / case / `?:` / loop 條件） | `if (miss) stall <= 1` → `miss→stall` |
| `ADDR` | src 是 dst 的 index / select | `mem[waddr] <= d` → `waddr→mem`；`x = mem[raddr]` → `raddr→x` |
| `CLOCK` | dst 在 src 的 edge 下更新 | `always_ff @(posedge clk)` |
| `RESET` | src 是 dst 的 async/sync reset 條件 | `if (!rst_n) q <= 0` |
| `PORT` | 跨 hierarchy 的埠連線（input: 外→內；output: 內→外） | `.a(x)` |

節點屬性：`driven_by ⊆ {always_ff, always_latch, always_comb, always, assign, port_in, inst_out, initial}`、`is_state`（在 edge-triggered process 中被賦值）、`const_assigns`（被賦常數/enum 值的次數）、`enum_values`、`width`、`unpacked_dims`。

---

## 3. Entity table [FROZEN: `entities-v1`]

- **範圍**：每個 module definition 取第一個 elaborated instance 為 canonical instance（參數不同的 instance 視為同一 definition，限制記錄在 §9）。
- **Generate 收合**：`g[0].r`, `g[1].r` → 一個 entity `g[*].r`（graph 保留展開）。
- **ID 規則**：`E<n>` 給 signal、`I<n>` 給 sub-instance；`n` 依**原始碼宣告位置**排序後從 1 開始。改名、重排 always block 不影響 ID → augmentation label 可直接搬移。
- **排除**：clock/reset 仍列出但 `auto_role` 標為 `CLOCK`/`RESET`，不可被選為 anchor；parameter/enum 常數不列。

欄位：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | str | `E12` / `I3` |
| `name` | str | 宣告名稱（generate 內為 `g[*].r`） |
| `kind` | enum | `port_in`, `port_out`, `port_inout`, `reg`, `latch`, `comb`, `wire`, `mem`, `local`, `inst` |
| `width` | int | packed 位寬（mem 為 element 位寬） |
| `depth` | int \| null | unpacked 陣列深度 |
| `type_str` | str | 型別文字（含 enum 名） |
| `enum_values` | list[str] | enum 型別時的值 |
| `driven_by` | list[str] | 見 §2.1 |
| `fanin` / `fanout` | int | module 內不同 entity 鄰居數（所有邊型別） |
| `ctrl_fanout` | int | 作為 CONTROL 來源的目標數 |
| `addr_fanout` | int | 作為 ADDR 來源的目標數 |
| `fsm_candidate` | bool | §3.1 |
| `auto_role` | enum \| null | front-end 可確定的角色：`CLOCK`, `RESET`, null |
| `name_hints` | list[str] | 名稱 heuristic（valid/ready/req/ack/state/cnt/ptr/en/sel/data/addr/stall/flush/full/empty/busy/done） |
| `line` | int | 宣告行號 |
| `definition` | str | 僅 `inst`：子模組名 |
| `members` | list[str] | 僅收合 entity：展開後的 graph node keys |

### 3.1 FSM candidate 規則 [FROZEN]
`is_state` ∧ 寬度 ≤ 8 ∧（enum 型別 ∨ 其 next-state cone 中存在對自身的 CONTROL 依賴（直接或經由一個 comb next-state 變數））∧ 被賦常數/enum 值 ≥ 2 次（含 next-state 變數）。

---

## 4. 輸出 schema：`ModuleAnnotation` [FROZEN: `roles-v2`]

```json
{
  "module_summary": "one sentence",
  "anchors": [
    {"id": "E12", "name": "state_q", "role": "FSM_STATE", "importance": "critical",
     "trace": "control_backward", "why": "<= 20 words"}
  ],
  "groups": [
    {"name": "refill_ctrl", "kind": "CONTROLLER", "anchor_ids": ["E12","E15"],
     "member_ids": ["E16"], "description": "<= 20 words"}
  ],
  "interfaces": [
    {"name": "cpu_req", "protocol": "VALID_READY", "direction": "IN", "member_ids": ["E2","E3","E4"]}
  ]
}
```

### 4.1 Anchor `role`（roles-v2）

v2 新增 `STATUS`、`COMMAND`、`INDEX`、`HOLDING_REG`、`DECODE`、`CLOCK_GEN`。原因：第一輪 session 標註（63 個 module）中 CONTROL_FLAG 被當萬用類別用了 116 次，PIPELINE_REG / INTERFACE_ADDR 也被誤用（見 docs/VALIDATION.md）。定義的唯一來源是 `src/rtl2d_l1/taxonomy.py`。

| role | 定義 |
|---|---|
| `FSM_STATE` | Controller state register (incl. one-hot and 2-state machines). If a state_q/state_d pair exists, select only the register. |
| `CONTROL_FLAG` | INTERNAL flag that gates several assignments: stall/flush/pending/hit/miss/full/empty/lock. Not for ports that only report status (use STATUS) and not for command inputs (use COMMAND). |
| `ENABLE` | Write/action enable for a register or path (we, en, load, shift, data-valid chain enabling a stage). |
| `MUX_SELECT` | Select that chooses between data sources (not the FSM state itself). |
| `COUNTER` | Counter or timer (baud counter, bit counter, timeout, cycle counter). |
| `HANDSHAKE_VALID` | valid/req-direction handshake signal. |
| `HANDSHAKE_READY` | ready/ack/grant-direction handshake signal. |
| `INTERFACE_DATA` | Data payload that crosses an interface boundary. |
| `INTERFACE_ADDR` | Address / ID that crosses the module boundary (a port). Internal indices use INDEX. |
| `DATAPATH_MAJOR` | Main computed result or datapath waypoint (alu_result, sum, product). |
| `PIPELINE_REG` | Register separating stages of a real pipeline (new data enters every cycle). Latches held across a multi-cycle operation use HOLDING_REG. |
| `STORAGE` | Memory, register file, buffer array or shift register holding data. |
| `FIFO_PTR` | FIFO/buffer read/write pointer or occupancy count. |
| `CONFIG_REG` | Software-programmable configuration/control register. |
| `ARBITRATION` | Grant vector, priority or round-robin pointer. |
| `STATUS` | Status/observation output or FSM-decoded output (busy, done level, error, mode/state indication, count output). |
| `COMMAND` | Command/mode/opcode input that selects WHAT the module does (start, rw, we-as-command, op, mode, flush request). |
| `INDEX` | Internal address/index/pointer into storage or a table (cache index, regfile rd/rs, hash index). Not FIFO pointers (FIFO_PTR). |
| `HOLDING_REG` | Register latching a request/operand/result and holding it across a multi-cycle operation (addr_q, operand regs, result reg). |
| `DECODE` | Decoded instruction/command flag or decoder output that steers many units (instr_add, is_load, opcode class). |
| `CLOCK_GEN` | Generated/divided clock or clock-enable produced by this module (clk_div, CLK_50, tick used as a clock). |

**Tie-break 規則**（也寫進 teacher prompt）：

1. One concept, one anchor: if a port is just a copy of an internal register, anchor the one a diagram would draw (usually the port for handshakes/data, the register for state/storage) and put the other in a group's member_ids.
2. A 1-cycle done/valid pulse that accompanies result data is HANDSHAKE_VALID; a level 'busy/done/idle' indication is STATUS.
3. External 1-bit condition inputs that only steer FSM transitions (bump, j/k, x) are not anchored by default; they are covered by `interfaces`. Anchor one only if it is a handshake, a COMMAND, or the module would otherwise have fewer than 2 anchors.
4. Replicated / bit-sliced structures (skew registers, per-bit carries, address bits A/B/C): anchor ONE representative and list the rest in the group's member_ids.
5. Logic disabled by parameters/defines (fanin=0 wires, ENABLE_X=0) is at most minor.
6. Ports are critical only when they are the primary handshake or primary data of the module's main function; other ports are major or minor (they are listed in interfaces anyway).
7. Keep the MEDIUM view (critical+major) readable as ONE block diagram: normally <= 12 anchors, <= 20 even for a large core; push the rest to minor.

`importance` ∈ {`critical`, `major`, `minor`} → 數值 1.0 / 0.7 / 0.4。
`trace` ∈ {`control_backward`, `data_backward`, `forward`, `interface`, `none`}。

### 4.2 Group `kind`

`CONTROLLER`, `DATAPATH`, `ARBITER`, `BUFFER`, `COUNTER_TIMER`, `DECODER`, `SERIALIZER`, `PIPELINE_STAGE`, `MEMORY`, `INTERFACE_ADAPTER`, `REGISTER_BANK`, `OTHER`。

- `anchor_ids` ⊆ anchors；`member_ids` 可含非 anchor entity 與 `I<n>`（子模組 instance）。
- Group 是 latent functional block 的 **hint**，邊界不要求完整（trace 會補）。

### 4.3 Interface `protocol`

`VALID_READY`, `REQ_ACK`, `MEMORY_BUS`（addr/we/wdata/rdata）, `STREAM`（data+valid 無 ready）, `SERIAL`, `SIMPLE`（純資料/控制線）, `CLOCK_RESET`, `OTHER`；`direction` ∈ {`IN`, `OUT`, `BIDIR`}（以本 module 為接收端看主要資料流向）。

### 4.4 Abstraction level（v1.2 起：由 importance 推導的 view）

Teacher **一律以完整細節（LOW）標註**，並仔細校準 `importance`。Level 不再是 teacher 的輸入，而是事後的 view：

| level | 取哪些 anchor | groups 上限 | trace 門檻 θ |
|---|---|---|---|
| `HIGH` | critical | 4 | 0.45 |
| `MEDIUM`（預設、gold 的標準） | critical + major | 8 | 0.25 |
| `LOW` | 全部 | 16 | 0.10 |

好處：同一份付費標註可以服務所有 view；anchor 集合保證 HIGH ⊆ MEDIUM ⊆ LOW。

### 4.5 使用者調控（Controls，皆為事後、確定性、免費）

| 參數 | 作用 |
|---|---|
| `level` / `preset`（overview / standard / detailed / control / datapath） | 一次設定一組參數 |
| `max_anchors` | 每個 module 的 anchor 上限（依 score → confidence → fanout 排序保留） |
| `min_confidence` | k-voting 信心下限 |
| `focus` / `exclude` | 只看／排除某些 role |
| `hide_interfaces` | anchors 不列 port 類 role（interface bundle 仍保留） |
| `max_groups` | group 上限 |
| `region_threshold`、`depth`、`reg_hops`、`steiner`、`include_ports`、`max_region_nodes` | trace 的範圍與上限 |
| `importance`（score / tier / structure）、`min_score` | level 怎麼決定（§4.6）；分數下限 |

### 4.6 量化重要度（v1.6 起；v1.7 = `importance-score-v2`）

每個 anchor 除了 tier（critical／major／minor）之外，還有兩個 0–100 的數字。兩者都在標註完成**之後**才計算，不進 prompt，也不影響 Run Store 的快取 key。

- **`struct_score`**：只用 RTL 結構和 role 算出來，不看名稱，改名不會影響。
  - 結構特徵共 17 個：寬度、state／memory、FSM 候選、port 方向、fan-in／fan-out／ctrl／addr fan-out、控制可達比例、任意可達比例、到輸出比例、反向 cone、module 內排名、module 大小。
  - 計算方式：用兩個 logistic 模型估計「teacher 會把它放進 MEDIUM」和「放進 HIGH」的機率 P(MEDIUM)、P(HIGH)，令 raw = 50·P(MEDIUM) + 50·P(HIGH)，再用分段線性校準，讓 teacher 的 HIGH／MEDIUM 比例（第 1–4 輪：27%／56%）剛好落在 70／40。
  - 係數由 `experiments/e5_importance_score` 擬合後凍結。v2 用了 9,151 個 anchor（412 個不同 module），grouped CV AUC：MEDIUM 0.82、HIGH 0.87。v1 沒看過的第四輪 module 上，v1 為 0.79／0.84，v2 為 0.81／0.86。
- **`score`** = 0.3 × 結構分數（raw） + 0.7 × tier 點數（critical 100、major 60、minor 20）。
  - 權重 0.3 是在獨立雙標資料上擬合的；0.1–0.4 的效果都一樣好。
  - 預測一位獨立 annotator 的 HIGH 等級，score 的 AUC 是 0.922，另一位強 annotator 的 tier 是 0.879。
- **門檻**：HIGH ≥ 70、MEDIUM ≥ 40、LOW 全部。三種模式共用同一組門檻，HIGH ⊆ MEDIUM ⊆ LOW 仍然成立。

`Controls.importance` 有三種模式：

| 模式 | level 依據 | 用途 |
|---|---|---|
| `score`（預設） | `score` | 強 teacher：和 tier 的結果 99% 相同，另外提供可排序、可設門檻的數字 |
| `tier` | annotator 的 tier | v1.5 的行為 |
| `structure` | `struct_score`，完全不看 tier | 弱 annotator 或 student。實測見 e6：Haiku 的 HIGH 跨改寫穩定度 0.75 → 0.90，與強 annotator 的一致度 0.80 → 0.88 |

`max_anchors` 的排序依目前模式的分數。Trace 的 seed 權重仍然用 tier，因為 §6 的閾值是依 tier 調出來的。

---

## 5. 驗證 [FROZEN]

Validator（`validate.py`）錯誤等級：

| code | 等級 | 規則 |
|---|---|---|
| `E_UNKNOWN_ID` | error | ID 不在 table |
| `E_NAME_MISMATCH` | error | `name` 與 ID 的 entity 名不符 |
| `E_AUTO_ROLE` | error | 選了 CLOCK/RESET entity 當 anchor |
| `E_GROUP_REF` | error | group.anchor_ids 不在 anchors 中 |
| `E_DUP` | error | 同一 ID 出現兩次 anchors |
| `W_FSM_NOT_STATE` | warn | FSM_STATE 選了非 `is_state` entity |
| `W_STORAGE_SHAPE` | warn | STORAGE 不是 mem 且寬度 < 8 且非 shift 結構 |
| `W_DEAD` | warn | anchor fanout=0 且非輸出埠 |
| `W_MISSED_FSM` | warn | fsm_candidate 未被選中 |
| `W_PORT_DIR` | warn | interface direction 與成員埠方向全部矛盾 |

有 error → 帶錯誤訊息 retry（最多 2 次，同一 conversation 追加 user turn）；仍失敗 → 丟棄並記錄。warn → 進 refine round（§7.3）。

---

## 6. Trace engine（交給 Stage 2 的 region 計算）[FROZEN 介面]

輸入：graph、anchors（含 trace hint、importance、confidence）、`level`。

1. **Cost-bounded typed slicing（Dijkstra）**：每個 anchor 依 trace hint 決定方向與邊型別
   - `control_backward`：反向，CONTROL/DATA/ADDR/PORT；
   - `data_backward`：反向，DATA/ADDR/PORT；
   - `forward`：正向，DATA/CONTROL/ADDR/PORT；
   - `interface`：輸入埠正向、輸出埠反向。
   邊成本：DATA 1.0、CONTROL 1.0、ADDR 1.5、PORT 0（hierarchy 透明）＋ **dilution** `0.5·log2(n_same_type_preds)`（被 20 個巢狀條件控制的暫存器，每個條件各自不重要）；踏上暫存器 +1.0，跨過 `reg_hops`（預設 1）個暫存器後不再展開；碰到其他 anchor 停止展開。
2. **Relevance score**：`score(v) = max_s w_s · exp(-cost(s,v)/τ)`，`w_s = importance × confidence`，τ = 2。保留 `score ≥ θ(level)`：HIGH 0.45 / MEDIUM 0.25 / LOW 0.10。
3. **Seed-to-seed 連接（Steiner 近似）**：terminals = anchors；節點成本 port 0.1、state 0.2、mem 0.3、comb 0.7、wire 1.0、local 1.2；Mehlhorn 近似。
4. **Boundary**：頂層埠全部保留（reason `boundary`），但不當 Steiner terminal。
5. **Semantic closure**（只對 anchors）：anchor 的窄（≤4 bit）CONTROL 前驅在 ≤4 個時全部保留（enable/select）；暫存器 anchor 保留 reset；valid/ready、req/ack、req/gnt 成對保留。
6. 輸出 `Region`：node → 理由（`seed`/`slice:<module>.<id>`/`steiner`/`boundary`/`closure:<rule>`）、score、邊、reduction。

量測（heuristic anchors，picorv32）：reduction HIGH 0.86 / MEDIUM 0.55 / LOW 0.37。

## 6b. 輸出目標 `--target`（v1.4）

Target 只決定**要準備哪種圖的資料**；teacher 標註與 work-unit hash 都不受影響，所以切換 target 不會重新付費。

| target | 狀態 | 輸出 | 怎麼產生 |
|---|---|---|---|
| `block`（預設） | 可用 | `anchors.json`、`region.json`（含 `anchor_edges`）、`diagram_*.svg` | teacher anchors + trace（§6） |
| `fsm` | 可用 | `fsm.json`、`fsm/<module>.<state>.mmd`（Mermaid）、`.dot`/`.svg` | **確定性 AST 抽取，不經 LLM**（`frontend/fsm.py`） |
| `timing` | 預留 | `timing.json`：之後要追蹤的 handshake interface 清單 | 規劃：每個 interface 自動產生 cover property → SymbiYosys trace → WaveDrom |

### FSM 抽取規則
- 抽取對象：前端的 FSM 候選，加上 teacher 標成 `FSM_STATE`、但前端沒偵測到的暫存器。
- states：enum literal、parameter/localparam 名稱，或常數（數值正規化，所以 `2'b0` 和 `2'b00` 是同一個 state）；`'x` 會被濾掉。
- transitions：`case (state)` 的 item 和 `if (state == X)` 決定來源 state；指派常數給 state 或 next 時記錄目的 state 與路徑上的條件；`c ? A : B` 會展開成兩條。`default:` 只套用到沒列出的 state。
- 條件化簡：被 parameter 關掉的分支會剪除，`&&`/`||` 裡的常數項會被化簡（slang constant evaluation）。
- reset state：reset 條件下（第一層、結構判定或名稱判定、結尾 override）賦的值。
- outputs：由 state 驅動的 output port，以及純 state 解碼的內部訊號。從輸入 port 有組合路徑的歸為 Mealy，其餘為 Moore。
- 不支援（會寫進 warnings）：one-hot 的 `case (1'b1) state[X]` 寫法、算術型的 next state、跨模組的 FSM。

驗證：44 個 FSM（examples + RTLLM + VerilogEval + picorv32）結構檢查 44/44 通過，包括目的 state 存在、有 reset state、沒有不明 state。picorv32 的 `cpu_state` 有一個 state（`ld_rs2`）在預設參數下確實到不了，這是正確的資訊。VerilogEval 的馬達控制 FSM 與 spec 文字描述逐條吻合。

### 6c. 語意（執行式）FSM 抽取（v1.5）

`frontend/fsm_semantic.py` 在 slang AST 上執行 RTL：包括 continuous assign、組合／時序 procedural block、function、for 迴圈、case/casez 和 part-select，並且跨 instance port 求值。

- **reset**：以結構偵測到的 reset 為優先。再加上任何 1-bit 頂層輸入：只要它在某個電位時，不管其他輸入是什麼都會把 state 強制成同一個常數，就視為 reset（例如 `rst ? IDLE : nxt` 這種寫法）。
- **狀態探索**：從 reset 值開始做 BFS；每個 state 取樣 300 組（隨機值、設計中的所有常數 ±1、全 1）。
- **偵測規則**：語法候選；或者可到達的 state 數 ≥ 3 且是稀疏編碼（少於 2^width）；或者在任一 port 別名上被整值解碼。
- **hybrid 輸出**：語法 FSM 一律附上 `semantic_check`（consistent / mismatch / unsupported）；語意引擎額外找到的標記為 `semantic-only`，其轉移條件由 ≤ 8 個控制 bit 窮舉後，以 Quine-McCluskey 化簡。
- **保證**：取樣是 sound 的（列出的每條轉移都確實由 RTL 產生），但不是 complete 的（極罕見的條件可能漏掉）。
- **驗證**：亂改等價 benchmark 18/18 同構（語法抽取 0/18）；一般 RTL 37/37 consistent。

### 6d. 證據行號（v1.5，`anchor-v2.1`）

每個 anchor 都附 `lines`（1–3 個絕對行號）。validator 的 `E_EVIDENCE` 規則：引用的行必須落在 module 範圍內，且至少一行包含該 entity 的名稱。這是確定性的反幻覺檢查；在 629 筆最終紀錄中，違規數為 0。

### 6e. 多輪 self-audit（選配，預設關閉）

`--passes N`：第 2 輪起依審查 checklist 逐條檢查，直到某一輪沒有任何變更為止。實測結果見 VALIDATION §R3.3：只改動 3.7% 的 anchor，而且全部是 importance 或移除，沒有新增，也沒有提升一致性。因此**預設 `passes=1`**；要提高可信度時，改用獨立的第二個 annotator 做 k=2 投票。

## 7. LLM teacher 決策 [FROZEN]

| 項目 | 決策 |
|---|---|
| Teacher | **Claude Opus 5.5**（`claude-opus-5-5`），`effort=high`，adaptive thinking |
| 輸出約束 | Structured outputs（`output_config.format = json_schema`），schema 由 `schema.py` 產生 |
| 呼叫模式 | 開發/gold/refine：同步 API（含 server-side refusal fallback）；量產：Batch API（五折） |
| Caching | system prompt（taxonomy + few-shot）固定、放最前面並標 `cache_control` |
| 去重 | work unit hash（RTL + entity table + child summaries + level + prompt 版本）相同 → 直接用 Run Store 結果，不重打 API |

### 7.1 「刀口」政策：哪些 module 才打 API

| 條件 | 處理 |
|---|---|
| entity 數 ≤ 4 或無任何 `is_state` 與子 instance（純組合小 module） | heuristic 標註，`source=heuristic`，不打 API |
| 已有相同 work unit hash 的 teacher 結果 | 重用 |
| 其他 | 打 API |
| gold set | 強制 k=3 voting + refine |
| 量產 | k=1；validator warn 或 heuristic/teacher 差異大 → 才補 k=3 |

### 7.2 Voting
k 次結果以 ID 計票：≥⌈k/2⌉ 進最終結果；role 取眾數；`confidence = votes/k`。

### 7.3 Refine round（計畫書的「生成 → 驗證 → 修正」閉環）
第一輪輸出後跑 validator warn 與 trace 檢查（如：某個 `ctrl_fanout ≥ 3` 的暫存器不在任何 anchor 的 slice 中、fsm_candidate 未選）→ 以同一 conversation 追加一則 user 訊息列出發現，要求修正或明確維持。最多 1 輪。

---

## 8. Run Store [FROZEN: `runstore-v1`]

- 路徑：`runs/store/runs.jsonl`（append-only），`runs/store/index.sqlite`（work-unit hash 索引）。
- 每筆欄位見 `store.py::RunRecord`：`run_id, created_at, design, module, unit_hash, frontend{tool,version,entities_version}, request{prompt_version,taxonomy_version,model,effort,level,k_index,round}, messages, response{raw,parsed,stop_reason}, usage{input,output,cache_read,cache_write,usd_est,batch}, validation{errors,warnings}, source(teacher|heuristic|student|human), stage2_feedback, human`。
- **SFT 匯出**只取：`source ∈ {teacher, human}` ∧ validation 無 error ∧（gold 或 vote confidence ≥ 0.67）∧ 同一 `taxonomy_version`。

---

## 9. Student（distill）決策 [FROZEN for v1]

| 項目 | 決策 |
|---|---|
| 主 student | **Qwen3-8B**（Apache-2.0、原生 32K context、程式能力強、生態最成熟） |
| Cost-down 對照 | **Qwen3-4B** |
| Code-specialized 對照 | **Qwen2.5-Coder-7B-Instruct** |
| 換模型規則 | 只有在 gold set 上 concept recall 高 ≥ 2pt 才換（例如 Qwen3.5 系列）；換了要記錄 |
| 方法 | LoRA（r=64, α=128, all linear），bf16，max_len 16K，3 epochs；推論時 JSON schema 約束解碼 |
| I/O | 與 teacher **完全相同**的 user prompt 與 JSON 輸出（不學 thinking） |
| 開始條件 | 同一 taxonomy 版本下 ≥ 1,000 筆合格樣本（含 augmentation 前 ≥ 300 筆原始 module） |
| 授權 | 開始前確認 API 條款對「以輸出訓練模型」的限制；本 student 為窄任務模型，不提供通用 LLM 服務 |

---

## 10. 評估 [FROZEN]

Gold：`gold/<design>.json`，格式同 `ModuleAnnotation` 但 anchors 可標 `alt_ids`（同一概念的等價 entity，如 `state_q`/`state_d`）。

| 指標 | 定義 | v1 目標 |
|---|---|---|
| Concept recall | gold anchors（以 `{id} ∪ alt_ids` 為一個概念）被命中的比例 | ≥ 0.90 |
| Anchor precision | 預測 anchors 落在任何 gold 概念內的比例 | ≥ 0.80 |
| Role accuracy | 命中概念中 role 相同的比例 | ≥ 0.85 |
| Group recall | gold group 與某預測 group 的 anchor Jaccard ≥ 0.5 的比例 | 量測 |
| Hallucination | 不存在的 ID | 0 |
| Rename robustness | 改名變體 concept recall 下降 | ≤ 0.05 |
| Trace coverage | gold 概念 entity 被 region 覆蓋比例 | 量測 |
| Reduction | `1 - |region| / |graph|` | ≥ 0.60（計畫書目標） |

必須同時報告 **heuristic baseline**。

---

## 11. 已知限制（v1）

- 同一 definition 不同參數的 instance 共用一份 entity table（取第一個）。
- SystemVerilog interface / modport 的連線只做名稱層級，不展開 modport 內部方向。
- Function/task 內部不展開：呼叫的所有引數視為回傳值的 DATA 來源。
- `force`/`release`、DPI、class-based testbench 不支援（本工具處理可合成 RTL）。
