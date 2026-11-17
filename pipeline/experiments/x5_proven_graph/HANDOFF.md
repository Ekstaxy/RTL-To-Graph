# x5 交接：先求一定正確的狀態圖

寫於 2026-11-17。這份文件讓新的 session 打開就能接手。程式在同一個資料夾，演算法細節另見 `README.md`。

---

## 0. 新 session 的開場白，直接貼

```
接手 RTL-To-Graph 的 x5 工作。請先讀 RTL_\docs\x5_proven_graph\HANDOFF.md 與同資料夾的 README.md，
再依「第 6 節 待辦與排查方向」從第一項做起。原則：正確性第一，每個圖上的元素都要有證據，證不出來就標未定；
LLM 與啟發式只能當提議者，由檢查器裁決。全程用繁體中文回報。做完一項就更新 HANDOFF.md 的現況表。
```

---

## 1. 目標與原則

使用者的要求，原話的意思：一直迭代到找到能保證輸出一定正確的演算法；要做的是值得信任的工具；先有準確才談好讀易懂；
可以用 LLM，不要求純演算法；要找到後段能接受的表達式，以及夠穩的演算法。

落實成三條規則：

1. 圖上每個元素都是一條宣稱，必須帶證據：可重播的實際軌跡，或不可能發生的證明。
2. 證不出來的標成未定，用不同畫法，絕不當成事實。模型處理不了的設計直接拒絕，不輸出。
3. 提議與裁決分開。要觀測哪些訊號、狀態叫什麼、條件怎麼寫、刺激怎麼給，都可以由 L1、人或 LLM 提議。提議再差只會讓圖變醜，不會讓圖變錯。

---

## 2. 規格：憑證 `proven-graph-0.1`

`prove.py` 輸出的 `cert.json`。後段 L2 與 L3 應該吃這個格式，而不是 x4 的 FsmGraph v0.1。

| 欄位 | 內容 |
|---|---|
| `design`, `top` | 設計名與設計頂層 |
| `scope` | `instance` 實例路徑、`module` 原始模組名、`parameters` 該實例的參數值。證明的範圍是這個模組 |
| `observation` | 觀測向量：`[{signal, width}]`，可以是一個狀態暫存器、數個暫存器合起來、或注入的述詞線 |
| `assumptions` | 時脈與邊緣；reset 埠、極性、保持幾拍、放開後不再拉起；輸入不設限；未知值可為任意值；上電值；組態為合成組態，定義 SYNTHESIS 與 YOSYS；`source_order` 檔案順序；`macros` 巨集跨檔案延續 |
| `states` | `[{value, status: witnessed 或 undetermined, entry}]`。witnessed 只在有模擬器確認的邊碰到它時才成立 |
| `edges` | `[{src, dst, status, trace, step, replay, needs_power_up?}]`，status 見下表 |
| `completeness` | `status: proven 或 bounded 或 refuted`、`k`、`method`、`depth`、`undetermined`、`tightened`、`relay` 快照接力統計、`support` 輔助觀測下較細的邊集合、`invariant` PDR 找到的歸納不變量（`signals` 位寬、`blocked` 子句、`removed_edges`）、`pdr` 執行紀錄 |
| `traces` | `[{obs[], inputs{埠: 每拍的值}, init_regs{}, init_mems{}, origin}]`，只靠這個就能在模擬器重播。上電值只在需要它的軌跡上出現 |
| `widths`, `replay`, `engine` | 重播所需的位寬與記憶體；重播結果與 `same_design` 結構對照；工具版本、查詢次數、`code` 證明器雜湊 |

每種元素的宣稱與證據：

| 元素 | 宣稱 | 證據 |
|---|---|---|
| `witnessed` 邊 | 從 reset 出發的實際執行裡會發生 | 輸入軌跡；iverilog 在指定那一拍看到同一對觀測值。軌跡必須符合假設：每個輸入每拍都有值、reset 只在開頭 |
| `witnessed` 且 `needs_power_up` | 以軌跡列出的上電狀態開機時會發生 | 上電值只寫進 RTL 沒給初值的位元；和 RTL 初值衝突的軌跡由模擬器回報並拒絕 |
| `support` 投影 | 輔助觀測下證明完整，投影回來仍完整 | 檢查器重證較細的邊集合，自己重算投影 |
| 沒列出的邊 | 永遠不會發生 | 任意狀態一步後繼的閉包，`k = 0`；或 k 步歸納；閉包允許但到不了的邊由 PDR 證明，憑證附歸納不變量，檢查器用 Yosys SAT 把不變量和邊集一起重證 |
| `undetermined` 邊 | 不知道 | 一步之內可能，但沒有軌跡，PDR 也證不了到不了 |
| `model-witness` 邊 | 模型有軌跡但模擬器沒重現 | 代表兩個工具不一致，或軌跡依賴未知值。要追查，不能當事實 |
| 狀態名稱 | 這個名字的 RTL 表達式等於這個值 | 編譯進模組後證明相等，`post.py: verify_names` |
| 條件標籤 | 條件成立時就走這條邊，且只有這時走 | 對提議的原子做真值表窮舉，`guards.py: guard_tables` |
| 圖檔 | 畫的節點與邊和憑證一致 | SVG 讀回來比對，`post.py` 的 `render_roundtrip` |

拒絕條件，丟 `Refuse` 不輸出：鎖存器、多個時脈網、雙邊緣觸發、黑盒子、觀測狀態超過 64 個、Yosys 讀不了。

演算法六步：

1. 建模：`read_verilog; hierarchy; prep -flatten; async2sync; dffunmap; setundef -anyseq; write_smt2`。子模組用 `hierarchy -top <衍生模組>; rename -top x5_scope` 切出來，參數從衍生模組讀回。
2. 起始狀態：reset 放開後第一拍所有可能的觀測值，all-SAT。
3. 上界：每個觀測值從任意狀態的一步後繼，從起始狀態取閉包。真實狀態必是任意狀態之一，所以不受深度限制。超過狀態上限就退回 BMC 加 k 歸納。
4. 下界：隨機模擬，每個輸入八種驅動方式，可由提議指定；從 reset 的 BMC；快照接力，把模擬器某一拍的暫存器與記憶體倒出來交給求解器往後找，找到的接續整段從 reset 只用輸入重播，重現才採用；以已有軌跡為固定前綴往後延伸的 BMC。模擬看到閉包以外的轉移就把憑證判成 `refuted`。
5. 差距：閉包裡沒軌跡的邊標未定；再用 k 歸納試著證明到不了。提議可以帶 `aux` 輔助觀測訊號，在組合狀態上取閉包後投影回來，計數器這類只看自己排除不了的轉移靠這個排除。
5b. PDR（`pdr.py`）：剩下的未定邊，把檢查器自己的網表加監視器寫成 AIGER，交給 ABC 的 `pdr`。證明成功就把 ABC 的不變量翻成具名暫存器上的子句寫進憑證、刪掉那些邊；只有檢查器的歸納接受了才保留。
6. 重播：所有當作證據的軌跡先只用輸入重播；不夠的才帶上電值重播，並在邊上標 `needs_power_up`。另做結構對照：模型的每個具名暫存器與記憶體都要在模擬器裡找得到。
7. 二值模擬（`_fill`、`_xcheck`、`_x_as_zero`）：所有模擬（隨機、快照、重播）在上電時把 RTL 沒給初值的暫存器與記憶體位元補成確定值（軌跡給的，否則 0），RTL 寫的 x 換成 0（含 `casex` 的檔案不換），每拍檢查沒有暫存器是 x，出現 x 之後的拍不算數。

獨立檢查器 `check.py`：不匯入 z3，不共用編碼。軌跡重新模擬，補值與檢查用的暫存器清單由檢查器自己從 Yosys 列出（`own_state`），不用憑證的；邊集合寫成 Verilog 監視器，接到攤平後的觀測訊號，用 Yosys 內建 SAT 做時序歸納，預設上限 16 步；憑證帶不變量時，不變量一起寫進監視器、一起證。歸納證不出來時，檢查器自己用 ABC 找反例，交給模擬器重播（`refute`），重播出沒列出的轉移才記成「反例在模擬器重播成立」。
攻擊 `attack.py`：竄改憑證對原 RTL，含刪邊、加邊、改指向、未定升格、軌跡再拉 reset、軌跡少一個輸入、不變量改成假的；原憑證對突變後的 RTL，先證突變體自己的圖來判定憑證是否失真。失真還通過就是漏網。每一張都攻擊，重證超過 90 秒的每類 2 例，其餘每類 6 例。

稽核 `audit.py`：只讀結果檔，九項驗證逐張判定通過、未通過、未跑。結果檔帶憑證雜湊與程式雜湊，對不上就算未跑。成果頁 `make_proof.py` 只吃稽核檔，沒有稽核就不產生。
自我測試 `selftest.py`：十個答案已知的小設計，42 項預期，約五分鐘。改了程式先跑它。t8 測上電未知值的 x 假象，t9 測 RTL 寫的 x，t10 測子模組裡的暫存器。
一鍵入口 `x5.py`：`doctor` 檢查環境、`selftest`、`design` 對單一設計跑完全程並出頁面、`batch` 跑整批語料。環境安裝 `install.sh`。
開源對標 `bench_fsm.py`：Yosys FSM、Pyverilog（先過 sv2v）、TerosHDL、Verilator `--coverage-fsm`，拿已證明的圖當標準答案評分。

信任基礎：完整性依賴 Yosys 對 RTL 的解讀加上 z3 與 MiniSat 一致（PDR 刪掉的邊則是 ABC 與 MiniSat 一致）；軌跡依賴 iverilog 的二值模擬；slang 完全沒參與。

---

## 3. 環境

| 項目 | 位置 |
|---|---|
| 程式，固定位置 | `RTL_\docs\x5_proven_graph\` |
| 程式，WSL 執行用的副本 | `~/rtl2d-demo/x5w/src26/`，定版，雜湊在 `src26.sha256` 與 `out17/code_post.sha256`。改了程式就開新資料夾 `src27` 再複製，不要覆蓋 |
| 輸出 | `~/rtl2d-demo/x5w/out17/<design>/<id>/`，內有 `cert.json`、`spec.json`、`check.json`、`attack/`；`out17/audit.json` 是最終判定。`out16` 以前是舊版程式的結果，不能引用 |
| Python | `~/rtl2d-demo/proofenv/bin/python`，已裝 z3-solver 5.4.1 |
| iverilog 與 vvp 包裝 | `~/rtl2d-demo/x5w/bin`，執行前要加進 PATH |
| RTL 與 x4 結果 | `~/rtl2d-demo/branchcheck_99e0c78`，清單 `runs/all30.json`，x4 結果 `runs/x4_fsm_timing/all30/designs` |
| 其他工具 | Yosys 0.33（含 `yosys-abc`，PDR 用它）、Graphviz dot，系統已有。對標用的工具在 `~/rtl2d-demo/tools/`：OSS CAD Suite 2026-11-16（新版 Yosys、Verilator）、TerosHDL、sv2v；Pyverilog 在 `~/rtl2d-demo/benchenv`。沒有 sudo |
| Git | `RTL_\RTL-To-Graph`，使用者的工作目錄在 main。x5 程式與成果頁 zip 在已推送的分支 `feat/x5-proven-graph-showcase`；之後的提交與推送先問使用者 |

每次開工先設好：

```bash
wsl -e bash -lc 'export PATH=$HOME/rtl2d-demo/x5w/bin:$PATH; cd ~/rtl2d-demo/x5w; ls'
```

已知的坑：

- bash heredoc 會吃掉 Python 字串裡的反斜線。改程式一律用 Write 工具寫補丁檔再執行，不要用 heredoc 塞含 `\n`、`\d` 的程式。
- wsl 指令裡含 `rm -rf` 會被安全檢查擋下，不要繞過，改用新的資料夾名稱。
- Windows 主控台是 cp950，印中文會錯，寫檔用 UTF-8。
- 設計本身會 `$write` 字元到標準輸出，例如 darkuart，所以測試台輸出用 `X5O...;` 與 `X5S...;` 標記，不要用行首比對。
- 背景跑的 `run.py` 會被整體 timeout 砍掉，每個候選的 `--budget` 只在階段之間檢查，實際可能超過。
- 記憶體只有 7.7 GB。後處理超過 3 個平行工作時，picorv32 的 Yosys 各吃 2 GB，WSL 會整個沒回應並回 `WSAETIMEDOUT`。
- `pgrep -f "某字串"` 放在 `bash -lc` 裡會比對到自己這個 bash，迴圈永遠不會結束。
- iverilog 不能帶 `-u`：那會讓每個檔案各自一個編譯單元，前一個檔案的巨集傳不到下一個，picosoc 就因此變成另一個設計。

---

## 4. 指令

最簡單的入口是 `x5.py`：`python x5.py doctor` 檢查工具，`python x5.py selftest WORK`，`python x5.py design --files a.v b.v --top TOP --observe state --out OUT` 單一設計全程，`python x5.py batch ...` 整批。下面是整批時一步一步的指令。開源對標：`python bench_fsm.py OUT BENCH`，成果頁 `make_proof.py OUT GALLERY BENCH/bench.json`。

完整流程四步，順序不能換。輸出資料夾每次用新的名字，舊結果不會混進來；稽核也會擋掉對不上雜湊的結果。

```bash
# 0. 自我測試，約五分鐘，42 項必須全過
wsl -e bash -lc 'export PATH=$HOME/rtl2d-demo/x5w/bin:$PATH; cd ~/rtl2d-demo/x5w && ~/rtl2d-demo/proofenv/bin/python src26/selftest.py st_new'
```

```bash
# 1. 證明 23 張，約 15 分鐘
wsl -e bash -lc 'export PATH=$HOME/rtl2d-demo/x5w/bin:$PATH; R=~/rtl2d-demo/branchcheck_99e0c78; cd ~/rtl2d-demo/x5w && ~/rtl2d-demo/proofenv/bin/python src26/run.py $R $R/runs/all30.json $R/runs/x4_fsm_timing/all30/designs out18 --proposals src26/proposals.json --jobs 6 --budget 420'
```

```bash
# 2. 後處理：第二引擎、名稱、條件、圖檔、攻擊。每一張都攻擊。--jobs 不要超過 3
wsl -e bash -lc 'export PATH=$HOME/rtl2d-demo/x5w/bin:$PATH; cd ~/rtl2d-demo/x5w && ~/rtl2d-demo/proofenv/bin/python src26/post.py out18 --jobs 3 --attack 6 --attack-heavy 2 --heavy-seconds 90'
```

```bash
# 3. 稽核，結束碼 0 才代表全部跑完且全部通過
wsl -e bash -lc 'cd ~/rtl2d-demo/x5w && ~/rtl2d-demo/proofenv/bin/python src26/audit.py out18'
```

```bash
# 4. 成果頁，只吃稽核結果，輸出 docs/gallery/proof.html
wsl -e bash -lc 'cd ~/rtl2d-demo/x5w && ~/rtl2d-demo/proofenv/bin/python src26/make_proof.py out18 RTL_/docs/gallery'
```

只跑一個候選：`run.py` 加 `--only 設計名或候選id --tag summary_x`，`post.py` 加 `--only 子字串`。

`proposals.json` 的格式：每個設計一串提議 `{id, observe[], scope[]?, reset?, names?, note?, options?}`；`_hints` 用 `設計名/候選id` 當鍵，給 L1 候選補 `options`。
`options.stim` 指定輸入的驅動方式，數字 0 到 7 或 `{"value": 常數}`，另有 `sim_cycles`、`sim_runs`。

---

## 5. 現況

### 5.A 最新：11 月 17 日下午，補齊缺口、開源對標、一鍵入口、agent demo，取代本節以下所有數字

程式 `src26`，證明、後處理與稽核都用它，輸出 `out17`。（src24 加了 PDR 與二值模擬，src25 加了 x 字面值改寫，src26 改成逐層列出暫存器；out15、out16 是中間版本，作廢。）

#### 5.A.1 做了什麼

1. **未定的邊歸零**：新增 `pdr.py`。閉包允許但沒有軌跡的邊，交給 ABC 的 `pdr` 證明到不了；ABC 的歸納不變量翻成具名暫存器上的子句寫進憑證（`completeness.invariant`），
   檢查器把不變量寫進監視器、用 Yosys SAT 和邊集一起做歸納（通常 1 步）。spimemio 兩張各 14 條、cpu_state 兩張各 2 條，全部證明不可能。
   反面測試：拿掉一半子句、刪一條真的邊、加一個空子句（假不變量），檢查器都拒絕。
2. **Icarus x 缺口**：所有模擬改二值。上電把沒初值的暫存器與記憶體補成確定值（`_fill`），RTL 寫的 x 換成 0（`_x_as_zero`，含 casex 的檔案不換），每拍檢查沒有暫存器是 x（`_xcheck`）。
   檢查器補值與檢查用的暫存器清單由自己從 Yosys 列（`check.own_state`），不用憑證的。picorv32 有二十幾處 `'bx`，不改寫的話 mem_state 的 10 條軌跡全部失效，這是第一次試跑抓到的。
3. **拒絕要有反例**：檢查器歸納失敗時，自己用 ABC 找反例、交給模擬器重播（`check.refute`），重播出沒列出的轉移才記成「反例在模擬器重播成立」。
4. 檢查器預設 `maxsteps` 16。攻擊多一類：不變量造假。
5. 自我測試 42 項（新增 t8 上電 x、t9 RTL 的 x、t10 子模組暫存器、PDR 與反例的測試）。
6. **一鍵**：`x5.py doctor / selftest / design / batch`、`install.sh`。`x5.py design --files ... --top ... --observe ... --out ...` 單一設計約 90 秒跑完證明、檢查、攻擊、稽核、頁面。
7. **開源對標** `bench_fsm.py`：Yosys FSM 流程（系統的 0.33 與 OSS CAD Suite 的新版）、Verilator `--coverage-fsm`、TerosHDL 的 FSM 解析器（無頭）、Pyverilog（先過 sv2v）。
   工具放在 `~/rtl2d-demo/tools/`，Pyverilog 在 `~/rtl2d-demo/benchenv`。以已證明的圖為標準答案，多畫的邊一定是錯的、漏畫的有軌跡的邊一定是錯的。成果頁有對照表。
8. **agent demo**：`RTL_\agent_demo\`，見該資料夾 README。Claude（使用者指定 `claude-sonnet-5-5`，不要 Haiku）用六個工具呼叫既有骨幹畫三種圖。
   實測發現的兩個問題已修：解釋轉移時跟證明打架（改成把已證明的轉移清單交給它並規定以證明為準）、描述它看不到的波形（改成交給它實際畫出的拍數與數值）。

9. **補值清單改成逐層列出**（`prove.hier_state`）：攤平後的模型用上層的線名稱呼子模組的輸出暫存器（picosoc 的 `pcpi_mul_wr` 等四個），
   線不能被補值，暫存器整場是 x，證明器的軌跡默默依賴了 x。提前稽核時檢查器擋下 picosoc 的 cpu_state 才發現。現在證明器與檢查器都從不攤平的網表
   逐模組列出暫存器，用實例路徑加上它在自己模組裡的名字。模擬器拒絕的名字都是 `assign` 出來的別名，真正的暫存器都有補值與監看（逐一查過 picorv32、i2c、serv、axidma）。
   因為改了證明器，out16 作廢，最終結果是 out17。

#### 5.A.2 最終結果，`out17`，稽核乾淨

`audit.py out17` 結束碼 0，23 張 × 10 項，條件標籤 4 格不適用。程式 `src26`，雜湊在 `out17/code_post.sha256`。成果頁 `docs\gallery\proof.html` 由稽核檔與 `bench_out17.json` 產生。

| 項目 | 數字 |
|---|---|
| 狀態圖 | 23 張全部完整，188 個狀態 |
| 轉移 | 469 條，全部有二值重播的軌跡；未定 0、模型與模擬器不一致 0、需要上電值 0 |
| PDR | 32 條看似可能的轉移證明不可能，4 張圖，不變量合計 995 個子句，檢查器全部獨立重證 |
| 第二引擎 | 歸納長度 1 或 2；i2c 位元計數器 10，上限已提高到 16 |
| 竄改憑證 | 505 份全擋：宣稱的邊重播不出來 171、軌跡不符假設 138、重播的軌跡走了沒列出的邊 123、**反例在模擬器重播成立 58**、第二引擎證不出完整 11、假不變量在基本情形就失敗 4 |
| RTL 突變 | 讓圖失真 41 個全擋；圖不變但軌跡失效 25 個被擋；圖不變照常通過 70；保守拒絕 1；讀不了 1；漏網 0 |
| x4 的圖 | 多畫 82 條證明不可能的轉移（PDR 多證了 32 條，所以比 out13 的 50 多），少畫 12 條 |
| 條件標籤 | x4 的 386 個中 240 精確；真值表導出 373 條中 332 精確 |
| 開源對標，16 張單一狀態暫存器的圖 | 完全正確：TerosHDL 8.0.5 2 張、Yosys 0.33 / 0.71 0 張、Verilator 5.055 0 張、Pyverilog 1.3.0 0 張；本專案 16 張 |

開源對標的細節：Yosys 兩版在 spimemio 都多畫那 14 條不可能的跳轉，在 picorv32 多畫 2 條不可能的 trap；兩版在 picosoc 都在 `fsm_export` 段錯誤崩潰，0.33 在 picorv32 也崩潰；
0.71 只在 `-q` 時崩潰，所以對標不加 `-q`。Verilator 只認得用命名常數寫的狀態機，axisgfsm 認出 8 個狀態但推不出任何轉移。Pyverilog 經 sv2v 後 picorv32 仍解析失敗。
TerosHDL 是語法比對，i2c 兩張主狀態機完全正確，計數器與巢狀條件會漏畫。darkuart、i2c 位元計數器、uart_rx 計數器五個工具都沒抓到。

#### 5.A.3 agent demo 與簡報

- `agent_demo\`：見其 README。四個範例請求的對話紀錄在 `agent_demo\runs\demo_*`。
- 階段成果簡報 `docs\RTL-To-Graph_Agent_成果簡報.pptx`，13 頁，由 `agent_demo\deck\make_deck.js` 從 `data.json` 產生；`collect_deck_data.py` 只讀稽核檔與對標檔。

### 5.0 11 月 17 日清晨的驗證收尾，已被 5.A 取代

最終結果在 `out13`，以 `out13/audit.json` 為準。數字見 5.0.2。

#### 5.0.1 這一段抓到並修掉的問題

1. **picosoc 內模型與模擬器是兩個設計**。`picosoc.v` 先 `define PICORV32_REGS picosoc_regs`，`picorv32.v` 才照它選暫存器堆。Yosys 照清單順序讀會失敗，退回頂層優先；模擬器卻照清單順序讀，而且帶 `-u`，巨集傳不到下一個檔案。結果 Yosys 用 `picosoc_regs` 子模組，模擬器用 picorv32 內建陣列。cpu_state 兩張的 `model-witness` 都是這個造成的，之前另一張碰巧重播成功是運氣。修法：模擬器用模型的檔案順序，不帶 `-u`，定義 YOSYS；憑證記下 `source_order`。另加結構對照 `same_design`：模型的每個具名暫存器與記憶體都要在模擬器裡找得到。自我測試 t6 專測這件事。
2. **axivfifo 的 reset 選錯**。L1 靠名字選了 `i_reset`，那是軟體重設請求；真正的 AXI reset `S_AXI_ARESETN` 被當成任意輸入。憑證在它寫明的假設下仍成立，但那組假設不是設計者的本意。修法：提議明確指定 reset；憑證列出 `reset_like_inputs_left_free`；稽核新增「reset 協定」一項，靠名字猜而旁邊還有像 reset 的輸入被放任意時判未通過。全部 23 張只有 axivfifo 兩張有這個情況。
3. **攻擊程式的 `KeyError`**。另一個 session 回報的 `KeyError('i_alu_cmp')` 是本 session 正在改的 `attack.py` 新增的「軌跡少一個輸入」竄改，碰上檢查器從第一條軌跡讀輸入清單。修法：檢查器從憑證的 `widths.inputs` 讀輸入；不符合假設的軌跡在重播前就判不合格；格式壞掉的憑證回報拒絕原因，不會讓檢查器當掉。
4. **攻擊原本只跑了 10 張**。現在每一張都攻擊，重證超過 90 秒的每類 2 例，其餘每類 6 例。新增兩種竄改：軌跡裡再拉一次 reset、軌跡少一個輸入。突變體圖不變但原軌跡不再成立的，另列為「被軌跡重播擋下」。
5. **i2c 位元計數器 25 條未定歸零**。提議 `aux: state_reg` 一起觀測，38 個組合狀態上證明完整再投影回來。第二引擎重證的是較細的那組，投影由它自己重算。證出 x4 圖多畫 14 條、少畫 6 條。
6. **axivfifo.phantom_write 2 條未定歸零**。隨機驅動的 `M_AXI_BRESP` 第一次就帶錯誤碼，`o_err` 拉起後寫入永遠被擋。提議照 AXI 協定把回應碼固定成 OKAY、ID 固定為 0。
7. **上電值**。有些轉移只在特定上電值下發生，例如未初始化的暫存器堆內容。軌跡現在帶 `init_regs` 與 `init_mems`，邊標 `needs_power_up`；模擬器只在 RTL 沒給初值的位元上放值，與 RTL 初值衝突的軌跡會被回報並拒絕。自我測試 t2 偽造一條衝突軌跡，必須被擋。
8. **稽核 `audit.py`**。每個結果檔帶憑證雜湊與程式雜湊，對不上就算未跑。成果頁只吃稽核。
9. **攻擊被記憶體不足砍掉卻算成擋下**。axidma 與 axis2mm 的 FIFO 記憶體在第二引擎裡展開成觸發器，「刪一條真邊」的假憑證證不出來，歸納一路推到第 5 步、兩百萬變數，Yosys 被系統砍掉 5 次，原本都記成擋下。修法三件：
   - 檢查器新規則：重播的軌跡是真實執行，經模擬器確認的每一步都必須是憑證列出的邊，否則當場拒絕，不需要求解器。刪真邊的竄改在這裡就被抓到。
   - 新竄改「刪邊並拿掉經過它的所有軌跡」，只有歸納抓得到，專門測第二引擎。
   - 攻擊時第二引擎的歸納上限是原憑證所需步數加 2。上限只會讓接受變拒絕，不會反過來，所以健全；Yosys 沒正常結束記為 `aborted`，稽核把它算未跑，不算擋下。
   教訓：後處理 `--jobs 3` 時記憶體仍可能不夠，攻擊結果一定要分辨「有判定的拒絕」與「沒有判定」。
10. **求解器逾時與工具錯誤也被算成擋下**。axivfifo 的 6 個竄改案例其實是 `sat` 撞到 900 秒上限，Yosys 正常結束但沒有結論；之前一版影響錐裁剪讓 Yosys 內部斷言失敗，也被記成證不出來。修法：判定只認 Yosys 印出的三種結論，其餘一律 `aborted`。標記字串已對照實際紀錄。
11. **影響錐裁剪**。求解前讓設計輸出不再是埠，`opt_clean` 刪掉監視器扇入以外的邏輯。axivfifo 從 5555 個單元降到 196 個，原憑證重證 16.7 秒變 1.1 秒，原本逾時的竄改 1.3 秒就有判定。第一版用 `delete ... %ci* %n` 會讓 Yosys 斷言失敗，自我測試擋下了它。
12. **刪邊竄改對輔助觀測不夠狠**。只刪投影後的邊、沒刪較細那組裡對應的轉移，檢查器靠投影不一致就擋下，沒測到歸納。現在連較細那組一起刪。
13. **攻擊統計的 `KeyError('accepted')`**。突變後 RTL 讀不了的案例沒有 `accepted` 欄位，統計時當掉，後處理沒寫戳記，稽核正確地把 axis2mm 的攻擊判成未跑。修好後整個後處理用同一版重跑，沒有手動補戳記。

#### 5.0.2 最終結果，`out13`，稽核乾淨

`audit.py out13` 結束碼 0：23 張 × 10 項驗證，沒有未通過、沒有未跑；條件標籤 4 格不適用，因為 darkuart 兩張與 serv 兩張沒有人提議標籤。稽核所用的程式雜湊與 `out13/code_post.sha256` 一致。成果頁 `docs\gallery\proof.html` 由稽核檔產生。

| 項目 | 數字 |
|---|---|
| 狀態圖 | 23 張，全部以閉包證明完整 |
| 每條邊都有軌跡 | 19 張 |
| 轉移 | 501 條：469 條有重播確認的軌跡，其中 1 條需要特定上電值；32 條未定；0 條模型與模擬器不一致 |
| 未定的分布 | spimemio 兩張各 14 條、picorv32.cpu_state 兩張各 2 條 |
| 第二引擎 | 23 張全部重證完整，歸納長度 1 或 2；i2c 位元計數器要 10，**剛好等於預設上限，沒有餘裕** |
| 竄改憑證 | 512 份全擋，每份都有判定：宣稱的邊重播不出來 182、軌跡不符假設 138、重播的軌跡走了沒列出的邊 123、第二引擎證不出完整 69 |
| RTL 突變 | 讓狀態圖失真 32 個全擋；圖不變但原軌跡不再成立 29 個被重播擋下；不改變狀態圖 76 個照常通過；突變後讀不了 1 個；漏網 0；保守拒絕 0 |
| x4 的圖 | 多畫 50 條證明不可能的轉移，少畫 12 條實際會發生的轉移 |
| x4 的條件標籤 | 386 個：240 精確、19 只是充分、101 有反例、7 無法編譯、19 沒有標籤 |
| 真值表導出的條件 | 405 條邊：364 精確、4 部分、23 還依賴其他訊號、14 沒有提議原子 |
| 狀態名稱 | 提議 177 個，80 個證明與 RTL 常數相等後採用 |

這些數字的信任基礎與限制：

- 「第二引擎證不出完整」的 69 份是刪邊並拿掉所有相關軌跡的假憑證，反例在很深的地方，引擎在步數上限內沒有找到反例，只是證不出來。它們沒有被接受，但不是被反例擊倒。
- Icarus 對未知值 x 的運算規則和硬體不同，暫存器還是未知值時看到的轉移是可信、但未經證明。README 已寫明。
- 以模組為範圍的證明，軌跡是該模組單獨執行的軌跡。

#### 5.0.3 試過但沒成功

- spimemio 的 14 條未定全是「跳轉到狀態 4 或 5」，需要 `rd_valid = 1`。只加 `rd_valid` 排除不掉，因為從任意狀態出發，傳輸子模組手上可能剛好有一筆標籤 4 的回應。再加 `xfer.xfer_tag`、`xfer.xfer_tag_q` 後組合狀態太多，閉包做不出來，退回有界檢查，只得到 40 拍內沒看到，不是證明，沒有採用。下一步：觀測述詞而不是原值，例如 `xfer.xfer_tag_q == 4`、`dout_valid`，狀態數會小很多。
- picorv32.cpu_state 兩張各 2 條未定，都是進入 trap 狀態 128，還沒查。
- 下一輪建議：第二引擎預設 `maxsteps` 從 10 提高到 16。接受只會變多不會變錯，i2c 位元計數器就不會卡在上限邊緣；攻擊時的上限仍是原憑證所需步數加 2。

#### 5.0.4 歷史數字

以下 5.1 起是之前版本程式的結果，留作紀錄，不能引用。

### 5.1 之前的版本

23 個候選，**全部拿到完整性證明**，方法都是閉包。其中 **17 個每條邊都有實際軌跡**，等於圖是精確的。其餘 6 個還有未定的邊。

| 候選 | 狀態 | 邊 | 有軌跡 | 未定 | 和現有工具 x4 的圖比較 |
|---|---|---|---|---|---|
| axisgfsm.sgstate | 6 | 18 | 18 | 0 | x4 多畫 4 條，來自到不了的狀態 1 與 3 |
| axivfifo.phantom_read | 2 | 3 | 3 | 0 | 一致 |
| axivfifo.phantom_write | 2 | 3 | 1 | 2 | 一致 |
| axis2mm.phantom_start | 2 | 3 | 3 | 0 | 比對鍵有問題，見待辦 9 |
| axidma.phantom_read、phantom_write | 2 | 3 | 3 | 0 | 同上 |
| serv_state.lifecycle，頂層與 serv_top 內各一 | 7 | 25 | 25 | 0 | x4 沒抓到，這是提議的三訊號觀測 |
| simpleuart.recv_state，獨立與 picosoc 內各一 | 11 | 22 | 22 | 0 | 一致 |
| simpleuart.send_bitcnt | 16 | 33 | 33 | 0 | 一致 |
| picorv32.mem_state，獨立與 picosoc 內各一 | 4 | 10 | 10 | 0 | 一致 |
| uart_rx.bit_cnt | 11 | 23 | 23 | 0 | 一致 |
| darkuart.UART_RSTATE | 12 | 23 | 23 | 0 | x4 沒抓到 |
| darkuart.UART_XSTATE | 12 | 23 | 23 | 0 | x4 沒抓到。模擬器改吃合成組態後，原本 2 條不一致與 20 條未定全部消失 |
| spimemio.state，獨立與 picosoc 內各一 | 13 | 61 | 45 | 16 | 一致，48 條非自環邊完全相同 |
| picorv32.cpu_state | 7 | 22 | 19 | 2 | x4 多畫 4 條不可能的邊。另 1 條不一致 |
| picorv32.cpu_state 在 picosoc 內 | 6 | 19 | 16 | 2 | x4 多畫 6 條。另 1 條不一致 |
| i2c_master.state_reg | 12 | 33 | 33 | 0 | x4 多畫 8 條。給了刺激提議後 30 秒內全部找到軌跡 |
| i2c_master.phy_state_reg | 16 | 35 | 35 | 0 | x4 多畫 14 條。同上 |
| i2c_master.bit_count_reg | 16 | 46 | 21 | 25 | x4 **少畫 6 條實際會發生的轉移**。未定的 25 條多半是計數器到不了的值，待證 |

只在 axisgfsm 上完整跑過後處理，結果：

- 第二引擎確認完整性，2 步歸納。
- 攻擊：20 份竄改憑證全擋；8 個 RTL 突變中 4 個讓憑證失真，全擋；另 4 個不改變狀態圖，照常通過。漏網 0。
- 條件：x4 圖上 18 個標籤，8 個精確、1 個只是充分條件、9 個有反例，都是漏了優先權，例如標 `i_start` 的邊在中止條件成立時不會走。真值表導出後 18 條邊全部證明精確，自環也有條件。

wb2axip 的 6 張另外跑過後處理：第二引擎全部確認完整性，圖檔反查全部一致。

**11 月 17 日稍晚補記，第 6 節第 1 項已完成**：`post.py` 對 out7 全部 23 張跑完，被總時限砍掉後用 `collect.py` 從各資料夾重建 `out7/post.json`；成果頁在 `docs\gallery\proof.html`，`all.html` 已加連結。結果：

- 第二引擎 23 張全部確認完整性，包含 picorv32 的 cpu_state，沒有超時。圖檔反查 23 張全部一致。
- 攻擊跑了 10 張，其餘因耗時跳過或被時限砍掉：竄改憑證 140 份全擋；讓憑證失真的 RTL 突變 13 個全擋；不改變狀態圖的突變 33 個照常通過；另有 14 個突變被檢查器拒絕但無法判定憑證是否失真，屬於保守拒絕。漏網 0。
- 條件標籤：x4 圖上 386 個，239 個精確。真值表導出 430 條邊，362 條精確；剩下的多半是沒有提議原子，或原子不足以決定去向，i2c 位元計數器 46 條全部導不出來。
- 狀態名稱：提議 177 個，80 個通過相等證明。沒通過的多半是 `S_3` 這類 x4 自己編的名字，本來就不是 RTL 常數。
- 合計 526 條轉移：461 條有重播確認的軌跡，63 條未定，2 條模型與模擬器不一致。
- 已修：`check.py` 在子模組範圍時要把監視器模組一起交給範圍解析；`post.py` 帶 `--only` 時另存檔名不覆蓋總表。
- 新問題：`attack.py` 對 serv_top 內的 serv_state 丟出 `KeyError('i_alu_cmp')`，還沒查。
- 注意：這個資料夾在同一時間有另一個 session 在改，`prove.py`、`check.py`、`attack.py`、`make_proof.py`、`README.md`、`proposals.json` 都比本檔新，並多了 `selftest.py`。以那邊的程式為準；本節的數字是用當時的版本跑出來的。

抓到的實例，值得放進簡報：darkuart 有 `ifdef __ICARUS__`，在 iverilog 下會切到模擬專用路徑，發送狀態機根本不動。
Yosys 模型與模擬器看到的是兩個設計，工具用 `model-witness` 把它標了出來。對策已寫進 `sim_files`：模擬器改吃合成組態，定義 SYNTHESIS，把 `__ICARUS__` 換掉，連 include 目錄裡的標頭一起處理。

---

## 6. 待辦與排查方向，依優先序

> 11 月 17 日清晨更新：第 1、2 項已完成；第 3 項 i2c 與 axivfifo 已歸零，剩 spimemio 與 cpu_state；第 5 項的 reset 檢查已做成稽核項目。詳見 5.0。

### 1. 把後處理跑完並出成果頁

對 out7 跑 `post.py`，先不帶攻擊，確認 23 個都有 `check.json`、`graph.svg`；再帶 `--attack 6 --attack-max-seconds 60`。然後跑 `make_proof.py`，檢查 `docs/gallery/proof.html`，從 `all.html` 加連結。
要看的數字：第二引擎通過幾張；攻擊漏網是否為 0；x4 標籤精確比例；`render_roundtrip` 是否全對。
風險：第二引擎用 `memory_map`，picorv32 與 picosoc 可能超時。超時要如實寫成「第二引擎未完成」，不能算通過。

### 2. 追 `model-witness`

picorv32.cpu_state 兩個版本各有 1 條。做法照 darkuart 那次：找出第一個對不上的拍，比對模型與模擬器的觀測值。
先懷疑三件事：重播沒有 deposit 上電值；軌跡依賴被 `setundef -anyseq` 放開的未知值；還有別的模擬專用巨集。
每找到一類原因，要嘛修掉，要嘛在憑證裡寫明。

### 3. 提高軌跡覆蓋率，把未定降到零

目前未定的邊：i2c 位元計數器 25 條、spimemio 16 條、cpu_state 各 2 條、axivfifo.phantom_write 2 條。已經驗證有效的一招是刺激提議：i2c 兩張主狀態機與 darkuart 都靠它從個位數補到全滿。方向：

- 快照接力：模擬跑到深處時把所有具名暫存器的值倒出來，用那組值當 SAT 的起點往後找幾拍，找到後整段丟回模擬器重播確認。不具名暫存器與記憶體放任意，重播會擋掉假的。這是最有希望的一招，還沒寫。
- 刺激提議：讓 LLM 讀埠名與協定，產生 `stim`。已支援常數與八種方式，還缺「握手成對」與「序列」。
- 加大 `windows` 與 `max_len`，但 z3 在長展開上很慢。
- 未定的邊也可能真的到不了：加輔助觀測訊號讓歸納變強，例如把計數器歸零的述詞一起觀測，再投影回來。

### 4. 好讀：在已證明的圖上做有證明的化簡

- 計數器摺疊：把一串狀態分成一類，商圖的邊由成員邊決定，這個運算本身不會出錯。分法由提議者給。
- 述詞抽象：超過 64 個狀態時改觀測述詞，例如 `cnt == 0`、`cnt == MAX`。核心已經支援任意觀測向量，缺的是把述詞注入成線的入口，`guards.py` 的注入方式可以直接用。
- 條件標籤太長：給原子取別名，別名只是代換所以不影響正確性。沒有 L1 提議的機器目前沒有標籤，例如 darkuart 與 serv，要從次態邏輯的錐裡自動找原子，或讓 LLM 提議。

### 5. 還沒補的洞

- reset 極性靠名字猜。猜錯時圖會變成「一直被 reset 壓住」的單一狀態，宣稱仍為真但沒意義。要加健全性檢查：圖只有一個狀態、反極性卻有多個時發出警告。
- 註解形式的合成指示，例如 `// synopsys full_case`，Yosys 不理，別的合成工具會理。
- `x` 的語意：目前是任意值，比硬體寬鬆所以安全；但 `proc` 可能先把 don't-care 化簡掉，要找一個反例設計驗證。
- 模組範圍的軌跡不是 SoC 內的軌跡。要在卡片上寫清楚，或在頂層再找一次。
- 加第三方意見：x4 語意引擎執行到的邊必須落在閉包內，否則是 slang 與 Yosys 不一致。

### 6. 把時序圖與架構圖搬到同一套做法

- 時序圖：波形來自 iverilog，已有重播檢查。缺的是第二個獨立來源，可以把同一段輸入丟進 Yosys 的 SMT 模型逐拍比對。因果箭頭目前只證明路徑存在，要改成反事實檢查：翻轉來源那一拍，目的端必須改變。
- 架構圖：連線來自 slang，已有畫圖反查。缺的是用 Yosys 網表獨立重算單元之間的依賴，兩邊必須一致。單元的名稱與分組是提議，成員歸屬必須是完整的分割。

### 7. 接進專案

- 開分支提交，建議 `feat/x5-proven-graph`，放 `pipeline/experiments/x5_proven_graph/`。提交用 git plumbing，不要動使用者的 main 工作目錄。要不要推上去先問使用者。
- 寫測試：小設計的憑證、三種竄改必被擋、一個 `__ICARUS__` 設計。
- 定義 `proven-graph-0.1` 與 FsmGraph v0.1 的對應，讓 L3 的畫圖直接吃憑證。
- 把 z3-solver 加進相依。

### 8. 回報給 L1 的問題

這些是 x5 證出來的 x4 錯誤，應該開 issue 或直接修：

- 條件標籤不含優先權，後面的 `if` 會蓋掉前面的。
- i2c 的轉移標成 `always 1`，實際上有條件。
- 到不了的狀態與它們的邊照樣畫出來。
- i2c_master.bit_count_reg 少了 6 條實際轉移；picorv32.cpu_state 與 i2c 兩張圖有證明為不可能的轉移。
- darkuart 的兩個狀態暫存器與 SERV 的生命週期完全沒抓到。

### 9. 小問題

- `run.py` 比對 x4 的一位元旗標時，x4 的轉移只有自環，所以顯示成「證明多出 2 條」。這是比對方式的問題，不是 x4 的錯，要修比對或在頁面上說明。
- `make_proof.py` 會合併 `summary_*.json`，後面的覆蓋前面的。
- 軌跡很長時 `cert.json` 會到數 MB，可以改成外部檔。

---

## 7. 其他交付物的位置

- 競賽簡報與報名表文字：`docs\RTL-To-Graph_成果簡報.pptx`、`docs\報名表文字內容_v2.docx`。
- 官方圖對照圖廊：`docs\gallery\index.html`。
- 30 個設計三種圖的完整成果：`docs\gallery\all.html`。裡面狀態機的評級是 x4 的結果，x5 的結論出來後要更新。
- WSL 裡 `~/rtl2d-demo` 底下有多個工作目錄，刪除要由使用者自己做。
