# e9_protocol_templates

**Owner:** L1　**Date:** 2026-10-24

時序圖（timing diagram）管線的 Stage 1（`docs/plan_fsm_timing.md` §3）：從 top module 的所有邊界 port 出發，
用 L1 的 typed dependency graph 做「先配對、再套模板」的介面辨識，加上 clock domain、reset、
內部 lane 選擇，輸出 `signals.json`（格式見 `pipeline/experiments/x4_fsm_timing/FORMATS.md`）。

```bash
# 在 repo 根目錄
uv run --package rtl2d-l1 python layers/l1_extract/experiments/e9_protocol_templates/e9_select.py \
    --files F... --top T [--name N] [--include-dir D...] [--define D...] [--out DIR]
# 預設輸出 runs/e9_protocol_templates/<name>/signals.json
```
程式庫用法（x4 以 `x4_tools.load()` 載入，不走 `sys.path`）：
`select(run, design=None, notes=True) -> dict`（`notes=False` 時只輸出 FORMATS.md 定義的鍵），`run` 是
`annotate_design(..., cfg=RunConfig(mode="heuristic", targets=frozenset({"block","fsm","timing"})))`。

| 檔案 | 內容 |
|---|---|
| `e9_select.py` | `select()`、CLI、內部 lane / other_inputs / dropped、與 L1 prefix bundle 的比對 |
| `templates.py` | `Matcher`：配對與 7 個步驟的模板（見下） |
| `clock_domains.py` | `Domains`：register 的 clock domain、port domain、clocks、resets |
| `e9_graph.py` | 有界的圖走訪（`walk_regs`、`gaters`、`reg_distances`）、計數器／loop index 判斷、原始碼行查詢、唯一的 `sibling()` loader |
| `e9_regress.py` | 5 個內嵌的小 RTL 回歸案例（chain、timer、ser_shift、ser_index、loopidx），輸出到 `runs/e9_protocol_templates/_regress/` |

## Hypothesis
L1 的 `heuristic.port_bundles` 依名稱前綴分組，會把 wb2axip `skidbuffer` 配成 `i={i_valid,i_ready,i_data}`、
`o={o_ready,o_valid,o_data}`，也認不出 afifo 是 FIFO。如果改成「名稱只決定 port 屬於哪一類（valid/ready/req/ack、
wr/rd、full/empty、addr/we），是否成立由圖上的結構證據決定」，就能得到正確的握手配對與資料成員，
時序圖才不會畫出錯的 handshake。

## Measurement
- 設計（top module）：`examples/rtl/sync_fifo.sv`、`data/rtl/wb2axip/rtl/skidbuffer.v`、
  `data/rtl/verilog-axis/rtl/axis_register.v`、`data/rtl/wb2axip/rtl/afifo.v`、`examples/rtl/uart_tx.sv`、
  `examples/rtl/cache_ctrl.sv`、`data/rtl/verilog-uart/rtl/uart_rx.v`、`data/rtl/verilog-axis/rtl/axis_async_fifo.v`；
  另外抽查 `verilog-wishbone/wb_ram`、`wb2axip/sfifo`、`verilog-axi/axil_ram`、`verilog-axi/axil_register_rd`、
  `darkriscv/darkram`、`examples/rtl/soc_top.sv`（階層設計）。
- 人工逐一檢查每個介面的成員、角色、domain 與 evidence 行號；比較 L1 prefix bundle。
- 決定性：同一設計跑兩次 `select()`，JSON sha256 相同。

### 演算法
步驟依序執行，每一步只看前面沒被認領的 port：
1. **握手配對**（VALID_READY / REQ_ACK）：valid 類（`valid|vld|_v_`）配對方向相反的 ready 類（`ready|rdy`），
   req 類（`_req|req$|stb|strobe`）配 ack 類（`ack|gnt|grant`）。結構證據（walk 最多 4 hop，只穿過組合節點，停在第一個 register）：
   - valid 是 input：valid 到得了 register X（gate 或當值），且 ready 也 gate X，或 X 驅動 ready；
   - valid 是 output：ready 到得了 X 且 X 驅動 valid（或 valid 在內部被讀，兩者都作用在 X）。
   候選依（名稱 stem 相似度、證據 register 數）排序後 greedy 一對一配對，所以前綴不一致時（skidbuffer）照樣配對。
2. **STREAM**：沒有配對的 valid，只要到得了（input）或被 register 驅動（output）就成立。
3. **資料成員**：方向相同（REQ_ACK 另有反向的 rdata）、未被認領、不是 status 名稱的 port，其「值路徑」（無 CONTROL 邊）
   到達或來自 register X，而 X 的 gater（決定 X 是否寫入的來源）分級：1 = 握手 port；2 = 握手相關 register；
   3 = 和驅動握手的 register 共用 gater（同一條件，例如 uart_rx 的 tdata_reg 與 tvalid_reg）；4 = X 本身驅動握手
   （例如 `mem_we = state_q==WB`）。一個 port 符合多個介面時，先比名稱相似度，再比分級。
   input handshake port 經由前向走訪（可穿過 output port，例如 `in_ready = !v_q || out_ready`）gate X 也算第 1 級，
   所以「在 input 握手下載入、再送到 output」的一級 pipeline register 會成為 output 介面的資料成員（review 的 chain.v）。
   名稱像 we / cyc / en / sel / strb 的 1-bit input，若與 valid/req gate 同一個 register，成為 `we` / `enable`；
   byte strobe（`strb`/`wstrb`/`be`）可以是多 bit（AXI-Lite `s_axil_wstrb` → W 通道的 `enable`）。
4. **FIFO**：有 depth 的節點 M，其寫入位址只來自內部 register（否則是 MEMORY_BUS），1-bit input gate M 的寫入（wr）、
   另一個 1-bit input gate 讀指標或讀出 register（rd）、output 的值來自 M（rdata）、gate 寫入或讀出的 1-bit output（full / empty，
   結構優先，名稱次之）。confirmed = wr、rd 都在，且至少有 full 或 empty。
5. **MEMORY_BUS**：input 經 ADDR 邊進入 M 或其讀出；we、wdata、rdata 同上。
6. **SERIAL**：1-bit、非 status 的 port，值路徑（無 CONTROL）上的 register，或再往外一個 register hop 的 register，需滿足其一（全部是有向邊）：
   (a) shift register（自己到自己的 DATA 邊、不在 `arith_srcs`、寬度 ≥ 2）且其寫入被計數器 gate（CONTROL，可經組合節點）；
   (b) 計數器經 ADDR 邊（bit-select `q[idx]`）進入該路徑，且路徑上有寬度 ≥ 2 的非計數器 register。
   計數器 = 寬度 ≥ 2、`k in node.arith_srcs`、非 memory、非 for-loop index。單純被計數器旁邊的邏輯驅動的 1-bit 暫存 output
   （review 的 timer.v `expired`）不再算 SERIAL。
7. 剩下有握手名稱的 port → `SIMPLE`，`confirmed=false`，`demoted_reason` 說明原因
   （包括「這個 port 在此次 elaboration 中沒有任何連線」，例如被參數關掉的 pause_req）。

**Clock domain**：register 的 CLOCK 前驅沿單一來源的 DATA/PORT 鏈往回追到根（afifo 的 `assign wclk = i_wclk`），
domain id = `d.<根的名字>`；edge 從 sensitivity list 讀。port 的 domain = 3 hop 內所驅動（input）／驅動它（output）的
register 的 domain，多個 → `cdc`；找不到時：設計只有一個 domain 就用它，否則繼承同介面其他成員的 domain，再不然為 null，都寫進 `notes`。
**Reset**：RESET 邊來源追到根；極性先看使用方式（`negedge r`、`if (!r)`、`r == 0`、經過 `~` 的 assign），沒有才看名稱
（`_n`、`n` 結尾等）；sync/async 看每個寫入 procedure 的 sensitivity list 是否含 reset，混合 → `sync=null` 並列出行號。
**內部 lane**：FSM state register（`run.fsms`）一律加入；其他 top register 依「register hop」距離（經過組合節點不計）
≤ 2，輪流從每個介面取最近的，最多 4 個；其餘（含 memory、超出上限、太遠、子模組內部）寫入 `dropped` 並附理由與行號。
for-loop index（L1 的 `loop_var`，或原始碼中 `for (i = ...` 使用的 `integer`/`genvar`；L1 會把 module 層級的 `integer i` 報成
is_state=True、loop_var=False）不列入，並寫進 `notes`。
**other_inputs 的 kind**：1-bit → control；多 bit 只經 CONTROL 到 register → control；其他多 bit（包括沒有到任何 register 的）→ data。

`signals.json` 比 FORMATS.md 多一個 top-level 鍵 `notes`：所有假設與簡化（domain 推定、reset 混合、
與 L1 prefix bundle 不同之處、loop index 排除等）都記在這裡，不會靜默處理。需要嚴格符合 FORMATS.md 時用 `select(run, notes=False)`
（FORMATS.md 不在本實驗的範圍內，沒有改它；x4 目前的讀取端都用 `.get()`，不受影響）。

## Pass / abandon criteria
- 通過：skidbuffer 恰好 2 個 VALID_READY（`i_valid/o_ready/i_data`、`o_valid/i_ready/o_data`）；afifo 有 FIFO 介面且為 2 個 domain；
  axis_async_fifo 分成 s_clk / m_clk 兩個 domain；8 個設計人工檢查 0 個錯誤的 confirmed 介面；兩次執行結果相同。
- 放棄：需要靠前綴才能配對（換名稱就壞）或需要改 L1 `src/`。

## Results
輸出：`runs/e9_protocol_templates/<design>/signals.json`（2026-10-24）。

| design | clocks | resets (極性, sync) | interfaces（protocol, domain, confirmed: members） | internal lanes | other_inputs | dropped |
|---|---|---|---|---|---|---|
| skidbuffer | i_clk | i_reset (H, sync) | `if.i` VALID_READY d.i_clk ✓: i_valid, o_ready, i_data；`if.o` VALID_READY d.i_clk ✓: o_valid, i_ready, o_data | r_valid, r_data, ro_valid | – | 0 |
| sync_fifo | clk | rst_n (L, async) | `if.in` VALID_READY ✓: in_valid, in_ready, in_data；`if.out` VALID_READY ✓: out_valid, out_ready, out_data | wptr_q, rptr_q, count_q | flush_i | mem_q (memory), count_o (status) |
| axis_register | clk | rst (H, sync) | `if.s_axis` VALID_READY ✓: tvalid, tready + 6 資料；`if.m_axis` VALID_READY ✓: tvalid, tready + 6 資料 | s_axis_tready_reg, m_axis_tdata_reg, m_axis_tkeep_reg, m_axis_tvalid_reg | – | 11 |
| afifo | i_wclk, i_rclk | i_wr_reset_n (L, async), i_rd_reset_n (L, async) | `if.fifo` FIFO **cdc** ✓: i_wr (wr), i_wr_data, i_rd (rd), o_rd_data, o_wr_full (full), o_rd_empty (empty)；成員 domain 分別為 d.i_wclk / d.i_rclk | rd_addr, wr_addr, rd_wgray, wr_rgray | – | 5 |
| uart_tx | clk | rst_n (L, async) | `if.tx` VALID_READY ✓: tx_valid, tx_ready, tx_data；`if.tx_o` SERIAL ✓: tx_o | baud_cnt_q, shift_q, bit_idx_q + state_q (FSM) | – | busy_o (status) |
| cache_ctrl | clk | rst_n (L, async) | `if.cpu_req` VALID_READY ✓: valid, ready, cpu_we (we), cpu_addr (addr), cpu_wdata；`if.cpu_resp` STREAM ✓: cpu_resp_valid, cpu_rdata；`if.mem` REQ_ACK ✓: mem_req, mem_ack, mem_we, mem_addr, mem_wdata, mem_rdata (rdata) | valid_bits, rdata_q, addr_q, wdata_q + state_q (FSM) | – | 4 |
| uart_rx | clk | rst (H, sync) | `if.m_axis` VALID_READY ✓: tvalid, tready, tdata；`if.rxd` SERIAL ✓: rxd | m_axis_tdata_reg, rxd_reg, m_axis_tvalid_reg, busy_reg | prescale (data) | 8 |
| axis_async_fifo | s_clk, m_clk | s_rst (H, mixed), m_rst (H, mixed) | `if.s_axis` VALID_READY **d.s_clk** ✓: tvalid, tready, tdata, tlast, tuser；`if.m_axis` VALID_READY **d.m_clk** ✓: tvalid, tready + 6 資料；4 個 SIMPLE（s/m_pause_req/ack，PAUSE_ENABLE=0 沒有連線） | rd_ptr_reg, wr_ptr_reg, rd_ptr_gray_reg, wr_ptr_commit_reg | s_axis_tkeep, s_axis_tid, s_axis_tdest（參數關閉，未連線） | 64 |

- skidbuffer：恰好 2 個結構介面；`notes` 記錄 L1 prefix bundle `i`/`o` 「NOT followed」。
- cache_ctrl：L1 的 `cpu` bundle 把 `cpu_req_*` 與 `cpu_resp_valid` 混在一起；這裡拆成 VALID_READY + STREAM。
- axis_async_fifo：reset 在 370／357 行（reset 同步器）是 async，其他 20 多處 sync，所以 `sync=null`（`notes` 有行號）。
- 抽查：wb_ram → REQ_ACK（stb_i/ack_o + we_i、cyc_i (enable)、adr_i、dat_i、dat_o）；sfifo → FIFO ✓；
  axil_ram → 5 個 AXI-Lite 通道（aw/w/b/ar/r 分開命名），W 通道含 `s_axil_wstrb`（enable）；axil_register_rd → 4 個通道；
  soc_top（階層）→ VALID_READY + SERIAL；rr_arbiter → REQ_ACK `if.i`（req_i/gnt_o）+ STREAM `if.gnt_valid_o`（不再叫 `if.gnt_o`，避免和 port 同名）；
  axis_srl_register → 2 個 VALID_READY，`integer i` 不再是 lane。
- 回歸（review 後新增，`e9_regress.py`）：5/5 通過。chain：`if.out` 含 `out_data`；timer：沒有介面（`expired` 不再是 SERIAL）；
  ser_shift / ser_index：SERIAL ✓（shift register / 計數器索引的 bit-select）；loopidx：`i` 不是 lane。
- Review 修正後，8 個目標設計的介面、成員、lane 與修正前完全相同（逐一 diff）；只有 axis_async_fifo 的 `s_axis_tid`/`s_axis_tdest`
  （多 bit、參數關閉、沒有到 register）kind 由 control 改為 data，以及 evidence 字串：反向走訪的路徑原本順序顛倒：反向走訪的路徑原本順序顛倒
  （例如 axis_async_fifo `m_axis`），現在一律由來源到終點，via 行號落在正確的箭頭上。
- 決定性：afifo 經 importlib 載入，`select()` 兩次 sha256 相同；CLI 兩次輸出逐位元相同。
- 執行時間：axis_async_fifo 27.5 s、64 MB（幾乎都花在 L1 `annotate_design` 的 FSM semantic 階段）。

## Conclusion
保留（實驗內）。8/8 設計的介面經人工檢查都正確，skidbuffer 與 axis_async_fifo 達到預期，afifo 產生 cdc 的 FIFO 介面。
與 plan M2a 的差異：**sync_fifo 是兩個 VALID_READY，不是 FIFO**。它沒有 wr/rd enable port（寫入條件是內部的
`do_push = in_valid && in_ready`），用 VALID_READY 驅動測試平台比較精確；介面的 evidence 會記錄
「memory mem_q is written/read under this handshake」。是否要把它算成 FIFO，交給 M2a 決定（review 也把這點列為
需要使用者決定的未結事項：改 plan M2a，或另加一個把兩個握手合併成 FIFO 的 overlay；目前兩者都沒做）。

已知限制：
- 名稱 hint 決定 port 屬於哪一類。換名成 `a`/`b` 這種沒有 hint 的名字，握手會被當成一般 port（M5 用 e7 測名稱獨立性）。
- 狀態類 output（busy、err、full、count…）用名稱排除在資料成員之外，換名後可能被收進介面。
- MEMORY_BUS 只做 input 方向（設計本身是 RAM）；當 master 的記憶體匯流排沒有 req/ack 時不會成立。
- serv `serv_rf_ram`：L1 graph 把 memory 看成 width 0、沒有 depth、沒有 CLOCK 邊，所以不會產生介面（L1 src 的問題，不在這裡修）。
- 只處理 top module；子模組的 register 不會成為 lane（在 `dropped` 留一筆摘要）。
- SERIAL 需要 shift register 或計數器索引；用 FSM 狀態（不是計數器）決定移位時機的序列埠不會被認出。
- 名稱類別仍是本實驗自己的 regex（`templates.CLASS_RE`），沒有直接呼叫 L1 的 `trace._PAIR`／`heuristic.port_bundles`：
  `_PAIR` 只有 4 組字串替換（valid/ready、vld/rdy、req/ack、req/gnt），沒有 stb/strobe/grant 與 `_v_`；
  prefix bundle 只拿來在 `notes` 裡比較。
- `axis_register` / `axis_async_fifo` 中被參數關掉的 tkeep/tid/tdest：output 端因為有 mux 的 DATA 邊仍算資料成員，input 端則落在 other_inputs。
