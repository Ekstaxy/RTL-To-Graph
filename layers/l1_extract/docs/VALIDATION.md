# Stage 1 驗證報告（2026-10-01）

**目的**：確認 Stage 1 在真實資料集上不會壞、輸出不會太細也不會太嚴，以及使用者可以調整詳細程度。

**方法**：不打 API。由 Claude session（主 session 加獨立的 subagent annotator）擔任 teacher，標註透過 `batch plan --units-dir` 與 `batch ingest-session` 寫進 Run Store（model = `claude-session`）。整條流程和 API 版完全相同：同樣的 prompt、validator（`experiments/e2_session_annotation/check_answer.py`）和 Run Store。之後換成 API teacher 時，只要改 `--model`。

重現指令：

```bash
python scripts/build_manifests.py
python -m rtl2d_l1.cli sweep --manifest data/corpus/rtllm.json
python -m rtl2d_l1.cli calibrate examples/corpus.json data/corpus/rtllm.json data/corpus/verilog_eval.json data/corpus/picorv32.json
python -m rtl2d_l1.cli calibrate data/augment2/originals.json data/augment2/variants.json
python experiments/e1_trace_tuning/run.py examples/corpus.json data/corpus/rtllm.json data/corpus/verilog_eval.json data/corpus/picorv32.json
```

---

## 1. 資料集

| 資料集 | 授權 | 設計數 | 用途 |
|---|---|---|---|
| RTLLM（GPT 討論中的 spec→RTL 資料集） | MIT | 50 | 標註；spec 當 teacher 專用資訊 |
| VerilogEval spec-to-rtl | MIT | 156 | 同上 |
| picorv32（RISC-V core，3049 行） | ISC | 3 個 top | 大型扁平設計 |
| examples/（自寫：UART、FIFO、arbiter、cache、醜 Verilog、階層 SoC） | — | 6 | draft gold |
| 改名變體（examples 加 12 個資料集設計，名稱全部混淆） | — | 17 + 6 | 盲測 robustness |

Teacher 標註：共 235 筆，全部通過 validator。其中第二輪（roles-v2）有 84 個 teacher module 計入 calibration，另有 26 對 k0/k1 獨立雙標、23 個改名變體。

---

## 2. 前端穩健性（`sweep`）

| 資料集 | elaborate 成功 | slang error | 有 FSM 的設計 |
|---|---|---|---|
| RTLLM | **50/50** | 0 | 5 |
| VerilogEval | **156/156** | 0 | 28 |
| picorv32（3 種 top） | **3/3** | 0 | 3 |

**FSM 偵測**：在 VerilogEval 上，題名含 fsm/lemmings 且真的有 state register 的題目全部抓到。沒抓到的 4 題，state 是輸入 port（只考 next-state 邏輯），本來就不該標。跟 Yosys `fsm_detect` 交叉比對範例，結果 3/3 一致。

**Annotator 回報後修掉的前端 bug**（詳見 CHANGELOG v1.3）：
- 巢狀的同步 reset（`if(EN) if(Rst)`）沒被認出。
- 寫在 always block 結尾的 reset override 沒被認出。
- `@(posedge clk or negedge arstn) if(!brstn)` 這種寫法會把 `arstn` 誤判成 clock。
- BCD 計數器被誤判成 FSM。
- 1-bit 的兩狀態 FSM 被漏掉。
- `x ? S1 : S0` 這種條件選常數沒被算成常數賦值。

**名稱無關性**：把 17 個設計的所有名稱混淆（module、訊號、parameter、enum、typedef、註解）後，前端算出的結構特徵（auto_role、FSM?、kind、fan-out）**17/17 完全相同**，並已加成測試。

---

## 3. 標註品質

### 3.1 對 draft gold（9 個 module，MEDIUM view）

| | concept recall | precision | role 正確 |
|---|---|---|---|
| **Teacher（MEDIUM）** | **0.91** | **0.95** | **0.94** |
| Teacher（LOW） | 0.94 | 0.90 | 0.94 |
| Heuristic baseline | 0.48 | 0.94 | 0.88 |

> 注意：gold 是 Claude 起草的 draft-v0，**還沒經過團隊審核**；分數只能當相對比較。

### 3.2 Annotator 間一致度（26 對獨立 k0/k1）

| | HIGH | MEDIUM | LOW |
|---|---|---|---|
| Anchor 集合 Jaccard | 0.73 | **0.93** | **0.95** |

另外，雙方都選中的 anchor：role 一致 0.94、importance 一致 0.79。

### 3.3 盲測 robustness（17 個設計：原版有名稱和 spec，盲測版名稱全混淆且無 spec）

| | HIGH | MEDIUM | LOW |
|---|---|---|---|
| **Teacher** 原版 vs 盲測版 Jaccard | 0.73 | **0.88** | **0.91** |
| Heuristic 原版 vs 盲測版 Jaccard | — | 0.56 | — |
| Heuristic 的 gold recall | — | 0.45 → **0.14** | — |

**結論**：盲測的下降幅度跟兩個 annotator 之間的自然差異差不多（0.88 vs 0.93）。teacher 主要靠結構判斷，不是靠名字；heuristic 一旦沒有名字就會崩潰。這也是 Stage 1 需要 LLM 的直接證據。

---

## 4. 太細還是太嚴？（calibration）

### 4.1 Anchor 數量（teacher，84 個 module）

| view | 中位數 | 判準 | 違反數 |
|---|---|---|---|
| HIGH | 3 | 不可為空 | **0** |
| MEDIUM | 5 | ≤ 12（≥ 60 entity 的大模組 ≤ 20）、不可少於 2 | **0 太細，0 太稀疏** |
| LOW | 6 | — | — |

picorv32：HIGH 8、MEDIUM 19、LOW 51（roles-v1 時 MEDIUM 有 42，見 §5）。

### 4.2 Trace region（內部節點 reduction，port 不計）

| view | ≥ 20 節點設計的中位數 | picorv32 |
|---|---|---|
| HIGH | 0.98 | 0.98 |
| MEDIUM | **0.56** | **0.91** |
| LOW | 0.08 | 0.72 |

- 巢狀關係 HIGH ⊆ MEDIUM ⊆ LOW：**0 違反**（`region_for` 保證）。
- gold 概念被 MEDIUM region 覆蓋的比例：0.99。
- 計畫書的「降噪 ≥ 60%」在大型設計的 MEDIUM 達成（0.91）。小型教科書電路本來就幾乎每個節點都是架構，所以 LOW 不會刪什麼，這是預期行為。

### 4.3 閾值怎麼選的（`experiments/e1_trace_tuning/run.py`）

評估指標：「MEDIUM region 已經帶進多少只屬於 LOW 的 minor anchor」（leak 越高代表越鬆），以及 HIGH region 帶進多少 major。

| 設定 | HIGH reduction / leak | MEDIUM reduction / leak |
|---|---|---|
| v1.2（0.45/0.25/0.10, τ=2） | 0.58 / 0.42 | 0.00 / 0.78 |
| **v1.3（0.60/0.40/0.15, τ=1.5，Steiner 關、closure 只在 LOW）** | **0.82 / 0.33** | **0.32 / 0.36** |

拆開測試發現，Steiner 連接節點和 enable closure 是 MEDIUM 太鬆的主因。所以改成：
- Steiner 預設關閉，連線改由 **anchor 間的抽象箭頭**（`region.anchor_edges`）提供。
- enable/select closure 只在 LOW 啟用。

---

## 5. 驗證過程中做的設計變更

| 發現 | 證據 | 變更 |
|---|---|---|
| Taxonomy 有缺口，CONTROL_FLAG 被當萬用類別 | 第一輪 63 個 module 用了 116 次 CONTROL_FLAG；8 個 annotator 都回報同樣的問題 | **roles-v2**：+STATUS、COMMAND、INDEX、HOLDING_REG、DECODE、CLOCK_GEN，加 7 條 tie-break 規則 |
| 大型扁平 core 的 MEDIUM 太細 | picorv32 MEDIUM 有 42 個 | prompt 規定 MEDIUM 不超過 12（大 core 不超過 20）→ 降到 19 |
| Level 由 teacher 決定的話，換 view 就要重付費 | — | Teacher 一律標 LOW，level 改成事後 view（SPEC §4.4） |
| 箭頭太密 | picorv32 standard 207 條 | 合併平行邊，每個目的地最多保留 4 條（可調）→ 62 條 |
| 子模組拿到整個設計的 spec | annotator 回報 RTLLM 多個 spec 和 RTL 不符 | 加上「你是子模組」的說明 |
| 盲測版仍會從名稱外洩資訊 | annotator 回報 module 名、enum 名仍可見 | augment 也混淆 module、enum、typedef、parameter 名 |
| HIGH 最不穩定（0.73） | 分歧集中在 critical 和 major 之間 | k-voting 遇 importance 平手時取較高一級；建議 HIGH view 正式使用時跑 k=2 |

---

## 6. 使用者調控（實測：picorv32，皆免費）

| 設定 | anchors | 箭頭 | region / 225 | 內部 reduction |
|---|---|---|---|---|
| `--preset overview` | 6 | 13 | 30 | 0.98 |
| `--preset standard` | 19 | 62 | 44 | 0.91 |
| `--preset detailed` | 51 | 179 | 83 | 0.72 |
| `--preset control` | 8 | — | 34 | 0.96 |
| `--preset datapath` | 5 | — | 32 | 0.97 |
| `--level MEDIUM --max-anchors 8` | 8 | — | 35 | 0.96 |
| `--preset standard --edge-fanin 2` | 19 | 32 | 44 | 0.91 |

預覽圖：`python -m rtl2d_l1.cli diagram ... --preset standard` 會輸出到 `runs/out/<design>/diagram_<preset>.svg`。

---

## 7. 已知弱點與下一步

1. **HIGH view 的穩定度（0.73）** 是目前最弱的一環，主要是 critical 和 major 的判斷落差。正式產品如果重視 HIGH，用 k=2 voting。或者把 tie-break 規則 6（port 什麼時候算 critical）再寫得更明確。
2. **Gold 還是 draft**：9 個 module，由 Claude 起草，需要團隊審核後擴充到 40–60 個 module。
3. **Taxonomy v2 仍有灰色地帶**（annotator 回報）：
   - 沒帶資料的事件 pulse 算 STATUS 還是 HANDSHAKE_VALID；
   - counter 當 sequencer 用時算 COUNTER 還是 FSM_STATE；
   - port 是暫存器的複本時，該選哪一個當 anchor。
   建議三人討論後定 roles-v2.1。
4. **小型教科書電路**的 LOW region 幾乎不刪節點，這是合理的，但報告裡要說明，免得被誤讀成「沒有降噪」。
5. **Student**：已經有 111 筆 roles-v2 SFT 樣本（`data/sft_roles_v2.jsonl`），student 輸入裡完全沒有 spec。SPEC §9 的門檻是 1,000 筆，需要擴充資料集（加更多開源 RTL，以及改名 augmentation 帶來的免費 label）。

---

# 第三輪：更多資料、等價亂改 benchmark、多輪標註（2026-10-02）

## R3.1 更多資料

| 資料集 | 授權 | 設計 | 結果 |
|---|---|---|---|
| alexforencich/verilog-axis | MIT | 31 | elaborate 47/47（含以下三者） |
| alexforencich/verilog-uart | MIT | 3 | |
| olofk/serv（bit-serial RISC-V） | ISC | 9 | |
| darklife/darkriscv | BSD-3 | 4 | 修正 `` `include "../rtl/config.vh" `` 的 staging 後，slang error 為 0 |

這 40 個單元用多輪協定完成 teacher 標註，共 94 筆紀錄，全部通過驗證。calibration 結果：

| 指標 | HIGH | MEDIUM | LOW |
|---|---|---|---|
| anchor 數中位數 | 5 | 11 | 16 |
| 內部降噪（≥ 20 節點的設計） | 0.95 | 0.82 | 0.44 |

只有 1 個 module 的 MEDIUM view 超過上限（darkuart，13 個）。

## R3.2 「亂改但功能不變」benchmark

- **14 個設計**：UART TX/RX、FIFO、arbiter、cache、乘法器、紅綠燈、width converter、serial2parallel、序列偵測器，以及 VerilogEval 的 4 個 FSM。
- **每個設計 2 種改寫**，由 agent 依照 `experiments/e3_perturb_benchmark/data/REWRITE_RULES.md` 產生：
  - **S1 扁平亂改**：改掉所有內部名稱；FSM 換寫法、換 state 名稱、換編碼（one-hot、gray、亂序 binary）；拆或合 always block；De Morgan；多餘邏輯和 dead register。
  - **S2 階層亂改**：在 S1 的基礎上，把計數器、datapath、next-state、storage 或輸出解碼搬進新的子模組，加上 function 和 generate。
- **等價性**：`scripts/equiv_check.py` 用 Yosys 對 miter 做 SAT BMC，**嚴格模式**下在第一個 cycle 以正確電位真正 assert reset。結果 **28/28 PASS**：26 份跑滿 12 cycle，ugly_mul 的 2 份因為 16×16 乘法器的 SAT 太難，只跑到 6 cycle。

### FSM（確定性抽取）

| 抽取器 | 改寫後仍抽出同構狀態圖（不使用名稱對照表） |
|---|---|
| 語法抽取（v1.4） | **0/18** |
| **語意抽取（v1.5 新增，執行 RTL）** | **18/18** |

語法抽取器只認得 `case(state)` 和 `state == X` 這類寫法，所以 one-hot 逐 bit 方程式、帶複合條件的 if 鏈、搬進子模組的 next-state 邏輯全部失效。

語意引擎（`frontend/fsm_semantic.py`）的做法：在 slang AST 上寫了一個小型的 cycle 直譯器，跨子模組 port 求值；從 reset 開始，對每個 state 取樣大量輸入組合，用 BFS 找出所有可到達的 state 和轉移。等價的電路一定產生同構的狀態圖，跟寫法無關。

**一般 RTL 上的交叉驗證（5 個資料集、262 個設計，包含 verilog-axis、serv、darkriscv、picorv32）**：
- 52 個語法 FSM 全部能執行分析：
  - **47 個 consistent**；
  - **5 個 consistent-subset**：picorv32 的 `cpu_state` 等深層 state 在執行時沒有走到，但走到的每一條轉移都包含在語法結果中；
  - **mismatch 為 0**。
- 語意引擎額外找到 2 個 `semantic-only`：`axis_frame_join.port_sel_reg`（依序輪詢各 port 的選擇器）和 Prob074（循序電路），兩者都是合理的邊界情況。
- 第一版的語意偵測在大型設計上誤抓了 9 個非 FSM（CSR、暫存器編號、grant 向量、reset 同步器）。後來加上三條規則後降到 2 個：
  1. 必須會依輸入分岔；
  2. 不能是從同寬度的資料整值載入（bit-select 讀取例如 `in[3]` 不算載入，依賴圖現在會記錄 partial-read）；
  3. 平均後繼數不超過 3.5。

  加了這些規則之後，亂改 benchmark 仍維持 18/18。

**hybrid 輸出（`--target fsm`）**：
- 語法抽取的 FSM 一律跑語意交叉驗證，結果記在 `semantic_check`：`consistent`、`mismatch` 或 `unsupported`。
- 語意引擎額外找到的 FSM 會補上：state 名稱用數值反查常數；轉移條件對 ≤ 4-bit 的控制輸入窮舉，再用 Quine-McCluskey 化簡。
- 例：亂改後的 reservoir 抽出 `LV_EMPTY → LV_LO_R : s[0]`，與原版逐條對應。

### Teacher 標註（盲標，原版、S1、S2 分別由不同 agent 標）

比對單位是**物理訊號**：透過 mapping.json 對應改名，再沿 instance port 和純複製線合併成別名類別。

| 改寫 | MEDIUM 概念 recall | MEDIUM precision | role 一致 | HIGH recall |
|---|---|---|---|---|
| S1 扁平亂改（14 個設計） | **1.000** | 0.905 | **0.993** | 0.90 |
| S2 階層亂改（14 個設計） | **0.95–0.97** | 0.74 | 0.88 | 0.85 |

S2 的 precision 較低在預期之內：模組拆開之後，「連接子模組的訊號」（例如 FIFO 的 push/pop strobe、cache 的 refill 握手）本身就成為新的架構概念。HIGH 仍然是最不穩的層級，跟前兩輪的結論一致：critical 和 major 的界線最主觀。

## R3.3 多輪標註（self-audit）的實際效果

**協定**：見 `experiments/e2_session_annotation/session/MULTIPASS_PROTOCOL.md`。第一輪標註；之後每一輪依 checklist 對照 RTL 逐條審查，直到某一輪沒有任何變更為止，最多 4 輪。另外加了**證據行號**：每個 anchor 必須引用 1–3 行實際提到該訊號的 RTL，validator 會檢查（`E_EVIDENCE`）。

| 指標 | 數值 |
|---|---|
| 做了多輪審查的單元 | 90 個 |
| 被審查改動的單元 | 27% |
| 被改動的 anchor 比例 | **3.7%**（importance 26、移除 11、role 6、**新增 0**） |
| 最終紀錄中的證據錯誤 | **0 / 629** |
| 亂改 benchmark：第一輪 → 最終輪，S1 MEDIUM recall | 1.000 → 1.000 |
| 亂改 benchmark：第一輪 → 最終輪，S2 MEDIUM recall | 0.973 → 0.949 |
| 亂改 benchmark：第一輪 → 最終輪，S1 HIGH recall | 0.948 → 0.896 |

**結論：「自己掃很多遍」沒有降低幻覺，也沒有提升一致性。**
- 真正擋住幻覺的是**結構性檢查**：ID 和名稱交叉驗證、證據行號、validator retry。這些讓第一輪就沒有錯誤可修。
- 自我審查只在 critical 和 major 之間來回擺盪，從沒找回漏掉的概念，還讓 HIGH 的跨版本一致性略為下降。

**建議**：
- 正式流程用 `passes=1`，加上 validator retry，再加上「只在自動檢查有 finding 時才觸發的 refine」，也就是 v1.3 的行為。
- 需要更高可信度時，用**獨立的第二個 annotator 做 k=2 投票**（MEDIUM Jaccard 0.93），不要讓同一個 annotator 自我審查。
- 多輪功能保留為選項（`--passes`），預設不開。

## R3.4 這一輪修掉的前端問題
- darkriscv 相對路徑 include 的 staging。
- FSM 候選必須是「被整值解碼」的暫存器（`case` 或 `== CONST`），排除 verilog-axis 的 valid pipeline 誤判。
- validator 不再誤報「由子模組輸出驅動的線代表子模組暫存器」這種情況。
- `check_answer.py` 支援 pass 檔。
- 等價檢查改為嚴格的 reset 模式。

---

# 第四輪：大規模資料生成與前端修正（2026-10-03）

## R4.1 資料

**新語料**，全部是寬鬆授權，commit 固定在 `scripts/fetch_corpus.py`：
- alexforencich verilog-i2c／axi／ethernet／wishbone（MIT）
- ZipCPU wb2axip（Apache-2.0）
- biriscv（Apache-2.0）
- pulp common_cells（SolderPad 0.51）
- picosoc

**manifest**：每個 module 各為一個設計，檔案清單依 instance 依存閉包挑選（`scripts/build_manifests3.py`）。
- 共 395 個設計，elaborate 成功 394 個。
- 有 slang error 的 9 個直接剔除，剩 **386 個**。

**標註**：Opus 級 session teacher，只標一輪，交件前必須通過 validator。
- 依子模組先、父模組後的順序分 5 波：362、160、52、21、8 個單元。
- 前幾輪的設計中，有 24 個單元因前端修正需要重新匯入或補標。

**累計**（anchor-v2.1、Opus 級）：
- 683 個標註單元、426 個不同 module、20,342 個 anchor；
- critical 6,168、major 5,757、minor 8,417；
- 21 種 role 全部有出現，最少的 CLOCK_GEN 也有 82 筆。

**SFT 資料**：見 `data/sft/README.md`。
- train 1,552 筆、eval 82 筆，依原始 module 切分；
- 由 teacher 樣本 758 筆（去重後）和改名增強 1,059 筆組成（實際併入 876 筆）。

## R4.2 annotator 回報的前端問題（全部已修，並有回歸測試）
1. **slang 靜默丟掉整個 always 區塊。** 某個分支在當前參數下是死碼、而且不合法（例如反向的 part-select）時，slang 會把整個 always 區塊變成 InvalidStatement，卻**不發任何診斷**。這會讓 alexforencich 系列參數化模組裡的所有資料流消失（例如 `state_reg` 的 fanout 變成 0）。現在改從語法樹救回資料流，包括 reset 和寫在結尾的 `if (rst)`，並記錄在 `DesignGraph.unsupported`。
2. **結構式 sync reset 誤判。** low-power 寫法裡，`i_valid` 會被當成 reset。現在如果它同時被當作資料讀取，就降級回一般控制訊號。
3. **名稱像 reset、但其實是一般邏輯的訊號。** 由 FSM 驅動的 `reset_crc`、接到子模組 `clear` port 的 `dst_valid_o`，現在都降級。
4. **reset 狀態經由 port 運算式外溢。** `.i_reset(i_reset || !i_mcyc)` 這種接法會讓 `i_mcyc` 被標成 reset。現在只有單一訊號直接相連時才會傳遞 reset 狀態。
5. **組合條件裡的訊號全被當成 reset。** `if (!ARESETN || !WVALID)` 會讓 `WVALID` 也變成 reset。現在只有已知的 reset 算 reset，其餘訊號當成一般控制。
6. **AXI 的 `ARESETn` 沒被辨識**，已補上；另外對 timescale 寫法不一致的 repo 一律套用預設 timescale。

**已知但未修：**
- 訊號只接到 repo 外部的 cell（`tc_sync`、`tc_clk_mux2`、MIG）時，fanout 會顯示 0，validator 會發 W_DEAD 警告。annotator 都能正確判斷並保留這些 anchor。
- 名稱為 `*_clear_i` 的頂層輸入，是否算 reset 本來就有歧義。

**rekey 機制**：前端修正會改變 entity table，因此快取 key 也會變，但 entity ID 不變。`experiments/e2_session_annotation/rekey.py` 依（design, module）把舊答案搬到新 key，ingest 時再用新的 entity table 重新驗證；不通過的才重標。本輪共重新驗證 400 多個單元，只有 1 個需要重標：`M_AXI_ARESETN` 改判成 reset 之後，原本把它當 anchor 的答案變成不合法。

## R4.3 重要度 v2
用第 1–4 輪的 9,151 個 anchor（412 個不同 module）重新擬合：
- grouped CV AUC：MEDIUM 0.82、HIGH 0.87。
- 在 v1 沒看過的第四輪 module 上：v1 為 0.79／0.84，v2 為 0.81／0.86。v1 的分布外泛化算可以，v2 再好一些。
- 亂改穩定度（structure 模式）：Opus S1 MEDIUM 0.909 → 0.937；Haiku S1 HIGH 0.898 → 0.930、MEDIUM 0.857 → 0.897。
