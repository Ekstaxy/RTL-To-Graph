# RTL → Block Diagram 第三層（製圖層）設計空間：調研、變因與方案

> 日期：2026-10-02　範圍：只談 block diagram 的**第三層（製圖）**；FSM 與 timing diagram 不在本文。
> 已定案的前提：(1) 中間層 spec 給的 component **全部要畫**；(2) 結果**可人工修改**；(3) 無 AI 版重美感、AI 版重正確性。
>
> **標記慣例**
> - 【實測】＝我在本次工作中實際跑過（Graphviz 2.43.0、示意圖幾何量測）。
> - 【推測】＝沒有找到來源、或是我依來源所做的推論，請當成待驗證假設。
> - 其餘敘述都附來源連結；連結編號對應文末參考資料。
> - 圖 N1–N5、A1–A5 是**手排座標的示意圖**，用來呈現各方案「會長成什麼樣」，不是 ELK 等引擎的實際輸出（本環境無法安裝 elkjs）。圖下的交叉、彎折數字由程式從示意圖的線段幾何量出。

---

## 0. 摘要

1. **兩個版本可以共用同一份核心圖與同一個確定性渲染器。** 差別只在「版面語義」（stage、lane、回授、成束）由誰填：無 AI 版必須由第二層以受控詞彙給齊；AI 版可以留空讓 AI 提議，但每筆提議要帶來源、審核狀態，且 AI 只能寫進一個獨立的 hints／overrides 檔，碰不到 block／port／net。
2. **無 AI 版建議路線：N1 → N2 → N4。** 先用 ELK Layered 做出可驗證的基線（N1），對有 stage 語義的設計套「stage × lane 格線樣板」（N2），再用多候選＋字典序評分把「美感」變成可回歸測試的數字（N4）。N5（具名樁＋成束）當成可切換的呈現政策，N3（固定畫布約束最佳化）最後做。
3. **AI 版建議路線：A1 + A4 先做，A5 離線跑，A2 等指標成熟再加，A3 風險最高。** A1（AI 只提偏好）與 A4（自然語言編輯只產生 override patch）在結構上就讓 AI 無法改接線。A5 把 AI 放在開發期調參，線上完全不呼叫模型。
4. **調研中對提案書想法的主要補充：**
   - 時脈／重置在多個工具裡被當成「屬性或過濾條件」而不是連線（§1.5 第 2 點）；在範例電路上，把 clk／rst 畫成實線就佔了 9 個交叉中的 8 個【實測】。
   - 固定長寬比的正交排版在 2026 年才有專門演算法（ARCOL），「固定畫布」不是現成功能。
   - Graphviz 的正交走線不支援 port，在範例電路上箭頭直接落在方塊內部【實測】；不適合當主力引擎。
   - 硬體逆向工程領域有不靠 LLM 就能分辨 state／data register、還原高階暫存器的方法，可供第二層產生 stage 提示。
   - 沒有找到直接做「RTL → 文件用 block diagram」的 LLM **論文**，但有一個做法很接近的開源**工具** RTLViz（見 §1.4 末的補充）。
5. **需要團隊先定的一件事：**「component 全部要畫」是否也規定 net 的呈現形式。N2、N5 把 clk／rst 或 en 畫成標記或具名樁，沒有畫成完整連線；資訊都在，但不是一條線。

---

## 1. 調研發現

### 1.1 商用 EDA 的 schematic／block 檢視器

| 工具 | 與本案相關的做法 | 來源 |
|---|---|---|
| Concept Engineering Nlview | 專門賣給 EDA 廠商內嵌的 schematic 產生引擎，涵蓋 gate、RTL、block 層級；版面可由人介入、再由演算法最佳化；支援增量式產圖。廠商的說法是 EDA 公司自行開發 schematic 產生器太貴太慢。 | [C1][C2][C3] |
| Synopsys Verdi（nSchema） | 使用手冊目錄列出「產生部分 schematic」「產生 fan-in cone」「trace driver／load」等功能：重點是**從一點往外長**，不是一次畫全圖。 | [C4][C5] |
| Intel Quartus Netlist Viewer | 提供 schematic 過濾、節點移動、把 schematic 切成多頁、跨頁追 net、fan-in／fan-out cone 追蹤。 | [C6][C7] |
| AMD Vivado | 區分 Elaborated RTL schematic 與綜合後 schematic（既有研究文件已整理）。 | [C8] |
| AMIQ DVT Eclipse IDE | 可產生 schematic、flow、block 三種圖並輸出 SVG；用「diagram filter」隱藏或標示元素，每行是「動作＋正規表示式」，內建「只看 clock 與 reset」的過濾器。 | [C9][C10] |
| Sigasi | 曾有純文字的 Graphics Configuration 語言，可對 block diagram 分組、過濾、上色、折疊；**4.16 起棄用、5.3 移除**。 | [C11][C12] |
| yFiles（商用函式庫） | 階層、正交、port、bus、增量排版與編輯器（既有研究文件已整理）。 | [C13] |

觀察：
- 商用檢視器的共同策略是**過濾、局部展開、分頁**，而不是把整張圖排漂亮。這印證提案書的痛點，也說明「文件用圖」是不同的產品定位。
- Sigasi 把「用設定語言客製圖面」這條路做出來後又拿掉。移除原因官方頁面沒寫；【推測】維護一套圖面 DSL 的成本高於使用量。對本案的啟示是：人工修改優先走「直接拖拉＋override 檔」，不要再發明一套給人手寫的設定語言。

### 1.2 開源工具

| 工具 | 與本案相關的做法 | 來源 |
|---|---|---|
| Yosys `show` / `write_json` + netlistsvg | 網表 → JSON → elkjs → SVG；偏網表 schematic（既有研究文件已整理）。 | [O1][O2] |
| Yosys `viz`（0.26 新增） | 把資料流圖的節點依一系列越來越積極的策略合併，用來看大型設計的 big-picture 資料流；`-x` 可把 reset 這類全域訊號排除在外；輸出交給 Graphviz。 | [O3][O4][O5] |
| d3-hwschematic | D3 + ELK 的硬體 schematic 檢視器：分層＋正交走線、階層元件可點擊展開、輸入是帶 `hwMeta` 的 ELK JSON、節點渲染器可註冊。README 另列出 netlistsvg、sphinxcontrib-hdl-diagrams、HAL 等相關專案。 | [O6] |
| HDElk | 用簡單的 JS 物件描述 HDL 方塊圖，底層是 ELK；支援 highlight、bus 標記。SpinalHDL 有 PR 用它從設計直接產圖；討論中的共識是 **clk 不必畫出連線，改用 clock domain 顏色**，並建議中間加一層 JSON。 | [O7][O8] |
| ELK Layered / elkjs | 正交走線時遵守任意 port 約束，官方明說適用於 block diagram 與電路圖；支援跨階層邊的複合圖。可用 `layerConstraint`（首／末層）、`partitioning`（指定層）、model order（保留輸入順序）、interactive（沿用舊位置）來約束結果。演算法清單中也包含 Libavoid。 | [O9][O10][O11][O12] |
| Graphviz `dot` | `splines=ortho` 官方載明不處理 port、在 dot 中也不處理 edge label；社群有以 gvpr 修補的權宜做法。 | [O13][O14] |
| D2 + TALA | D2 內建 dagre、ELK、TALA 三個引擎。TALA 是為軟體架構圖設計的正交引擎，支援「部分節點給座標、其餘自動」的混合模式；作者自述長流程圖他常偏好 dagre／ELK，且大圖執行時間非線性成長。TALA 已隨 D2 v0.9.0 內建並開源；二手報導稱授權為 MPL-2.0、預設跑多個 seed 取評分最高者。 | [O15][O16][O17][O18] |
| TL-Verilog / Makerchip | 語言本身就有 pipeline 與 `@stage` 的概念；Makerchip 的圖把每個 pipe stage 畫成一個框，框內是該 stage 的訊號。 | [O19][O20] |
| IP-XACT（IEEE 1685）/ Kactus2 | `busInterface` 是「與某功能相關的一組 port」，由 bus definition 與 abstraction definition 定義，port map 把實體 port 對到邏輯 port；Kactus2 是以此為基礎的開源圖形化工具。 | [O21][O22][O23] |
| libavoid（Adaptagrams） | 節點固定後的避障正交走線，可做 nudging（把重疊路徑推開）與 hyperedge 走線；同專案的 libdialect 實作 HOLA。 | [O24][O25] |

**【實測】同一份範例 spec 丟給 Graphviz 2.43.0：**

- 預設曲線：port 有接對，但畫布 1302 × 708 pt，資料主幹呈階梯狀下降，30 條邊各自繞行。

  ![Graphviz dot 實際輸出（預設 spline）](svg/ref_graphviz_dot_actual.svg)

- `splines=ortho`：線變成直角，但 port 被忽略，多條邊的箭頭落在方塊內部或邊框中央，與官方文件的限制一致。

  ![Graphviz dot 實際輸出（splines=ortho）](svg/ref_graphviz_dot_ortho_actual.svg)

  注意 2.43 是舊版；新版行為可能不同，但官方文件至今仍載明此限制 [O13]。

### 1.3 Graph drawing 學術研究

- **分層法（Sugiyama）與 port 約束**：既有研究文件已整理 Sugiyama、Gansner、Brandes–Köpf、KLay port constraints、Tamassia、ASG、SPAR [P1–P7]，此處不重複。
- **哪些美學準則真的影響理解**：Purchase 的實驗結果是減少交叉影響最大，減少彎折與呈現對稱次之，角解析度與格線對齊未達顯著 [P8]；後續提出七項可計算的美學指標（0–1 連續值），可直接當成本函數 [P9]。另有研究指出，在找最短路徑的任務中，重要的是**該路徑上**的交叉數，而非整張圖的總交叉數 [P10]。對本案的意義：交叉要依 net 重要性加權，主資料路徑上的交叉最貴。
- **人會怎麼排**：HOLA 先做使用者研究再設計演算法；結果顯示人偏好緊湊、格線化、對稱，而交叉、彎折、線段長度的影響沒有傳統假設那麼大，HOLA 在使用者研究中勝過 yFiles 的正交排版 [P11][P12]。注意這與 Purchase 的結論方向不同：一個量「理解任務表現」，一個量「偏好」。**文件用圖兩者都要顧。**
- **固定長寬比**：ARCOL（2026）建立在 HOLA 上，自稱是第一個針對指定長寬比最佳化的正交排版演算法，動機正是既有正交排版無法控制圖的寬高 [P13]。
- **避障正交走線**：Wybrow 等人的演算法在避開物件的前提下，最小化長度與彎折數的單調函數，速度足以互動時即時重繞 [P14]。
- **版面穩定（mental map）**：Misue 等人提出以 orthogonal ordering、proximity、topology 三種模型刻畫「改圖後使用者還認得」，後續研究認為 orthogonal ordering（節點的左右、上下相對順序不變）最能代表 [P15]。另有工作討論 Sugiyama 排版中以 model order 取得可控且穩定的結果 [P16]。對本案的意義：RTL 小改後重生圖，至少要保住相對順序。
- **機器學習排版**：DeepGD（GNN）與 SmartGD（GAN）可同時最佳化多種美學指標，SmartGD 還能處理不可微的指標或模仿好例子 [P17][P18]；也有用 CNN 從圖片預測人類偏好的模型 [P19]。【推測】這些方法針對一般 node-link 圖，沒有 port、正交走線與固定畫布的概念，不能直接用，但「學一個偏好模型當評分器」的想法可借。
- **硬體逆向工程的結構還原**：DANA 以 flip-flop 之間的資料流把扁平網表還原成高階暫存器，不需要使用者設門檻值 [P20]；ReIGNN 用 GNN 加強連通分量分析區分 state register 與 data register [P21][P22]。這是「不靠 LLM 也能得到 stage／暫存器分組」的確定性路線。

### 1.4 以 AI 產生圖表的研究與產品

| 類別 | 代表 | 重點 | 來源 |
|---|---|---|---|
| 文字 → 結構化圖（多代理） | DiagramAgent（CVPR 2025） | 規劃、寫圖程式、檢查、圖轉程式分工（既有文件已整理）。 | [A1] |
| 圖程式合成 | DeTikZify（NeurIPS 2024） | 由草圖或既有圖產生 TikZ 程式；用 MCTS 在推論時反覆修正，不需重新訓練。 | [A2] |
| 多代理＋自我評審 | PaperBanana（ICML 2026） | Retriever、Planner、Stylist、Visualizer、Critic；迭代修正；以 VLM 當評審。【推測】其輸出依賴影像生成模型，不保證逐線正確，不適合直接畫網表。 | [A3][A4] |
| LLM 直接產 draw.io | next-ai-draw-io | LLM 輸出原生 draw.io XML，可用自然語言修改；README 提醒這需要能產生長且格式嚴格輸出的強模型。 | [A5] |
| LLM 與圖的可讀性 | Graph Drawing for LLMs | 以圖片餵模型時，排版範式與可讀性會明顯影響模型回答圖結構問題的表現。 | [A6] |
| VLM 能否評美感 | AesEval-Bench（ICLR 2026） | 系統性評測後，VLM 在美感評估上與細緻需求仍有明顯落差。 | [A7] |
| 模型提關係、求解器定位 | Holodeck、LayoutVLM | LLM／VLM 產生空間關係，再由搜尋或可微最佳化決定位置；另有研究指出大模型在需要精確座標的版面推理上仍會出現空間幻覺。 | [A8][A9] |
| 重新解析再比對 | DiagramEval、Schemato、Weave | 把輸出圖轉回圖結構比對節點與路徑（既有文件已整理；後兩者為類比電路 preprint）。 | [A10][A11][A12] |
| LLM × RTL | DeepRTL2、Verilog 生成綜述 | 文獻重心在 RTL 生成與理解；**本輪搜尋沒有找到直接做 RTL → 文件用 block diagram 的 LLM 論文**（不代表不存在）。 | [A13][A14] |
| 自主實驗迴圈 | autoresearch | agent 只改一個檔、跑固定預算的實驗、看指標決定保留或還原。 | [A15][A16] |

**補充（後續查證）：最接近本案的既有嘗試是 RTLViz。** 它是 MIT 授權、標示為 alpha 的 PyPI 套件，定位是從 Verilog 產生 block diagram。0.3.6 版 README 描述的架構是「程式解析器抽出連線與階層 → LLM 補語義（例如這是 IF stage、這個模組是 ALU）→ 驗證器檢查版面密度、上色與連線」，並有 pipeline stage 偵測、依功能分群、正交走線、可縮放的 HTML 輸出 [A17]。較早的 0.2.x 版則是讓 AI 直接寫 Graphviz DOT，README 自己提醒可能出錯、要對照設計檢查 [A18]。也就是說它走過「LLM 直接畫 → 改成程式抽連線、LLM 只加語義」這條路，與本案的結論一致。與本案的差別（依 README 判斷，我沒有執行或讀原始碼，也沒讀最新的 0.9.0 版）：後端是 Graphviz；輸出是互動 HTML／SVG，沒有提到可逐物件編輯的 draw.io；沒有公開的中間層契約與 view profile；沒有提到固定畫布、人工修改回收或 round-trip 比對；樣式預設偏 CPU。另有論文評估 LLM 由 RTL 產生**文字**規格，並指出硬體規格生成的研究仍少 [A19]。

### 1.5 相對於提案書的重新發散

提案書的第三步是「確定模組與接線後，針對給定圖表大小做一次排版」。調研後，我認為有七個方向值得放進設計空間：

1. **排版不是一步，而是「語義 → 版面意圖 → 座標 → 走線 → 檢查」五步**，AI 能安全介入的只有第二步（版面意圖）。
2. **全域訊號不一定要畫成線。** DVT 用過濾器、Yosys `viz` 用 `-x`、SpinalHDL 用 clock domain 顏色。
3. **固定畫布要當成一級需求設計**，包含換行、分頁、`layout_infeasible` 回報；ARCOL 顯示這在學界也是新題目。
4. **設計型態資訊要下放到每個 block 與每條 net**，全域 tag 只能選樣板。TL-Verilog 的做法是語言層級就有 stage。
5. **stage／register 分組可以不靠 LLM**（DANA、ReIGNN 的路線），這讓「無 AI 版」也拿得到版面語義。
6. **AI 可以只在開發期出現**（autoresearch 式離線調參），線上產品維持零模型呼叫。
7. **介面成束可沿用 IP-XACT 的 busInterface 詞彙**，不必自創。

---

## 2. 變因表

每個變因列出 2–5 個選項並給代號，§3、§4 的方案用代號組合。

### V1 中間層 spec 需要哪些資訊／label

| 代號 | 內容 | 說明 |
|---|---|---|
| S1 | **最小拓撲**：block（id、label、parent_id）、port（owner、direction、width）、net（source、targets） | 沒有它畫不出圖；也是 round-trip 驗證的唯一基準。 |
| S2 | **語義標籤**：block `kind`／`role`、port 與 net 的 `class` | 決定形狀、線型、顏色；受控詞彙。 |
| S3 | **版面語義**：`stage_index`／`stage_boundary`、`lane`、每個 (net, sink) 的 `flow_role`、`importance`、`group` | 決定「誰在左、誰在上、哪條線走外圈」。美感的主要來源。 |
| S4 | **介面成束**：`bundles`（成員、協定、所在側）、全域訊號束、每條 net 的 `presentation`（wire／stub／implicit） | 決定哪些線合併畫、哪些不畫成線。 |
| S5 | **溯源與鎖定**：`source_refs`、`reason_included`、`description`、provenance、`lock_level`／AI 可動範圍、核心圖 hash | 給驗證、審核與 AI 使用。 |

### V2 圖的大小

| 代號 | 內容 |
|---|---|
| Z1 | 固定 16:9（投影片） |
| Z2 | 固定 4:3 或 A4 橫向／文件欄寬 |
| Z3 | 自由尺寸，只限制最大長寬比與最小字級 |
| Z4 | 分頁＋跨頁 connector（Quartus 式）[C6] |
| Z5 | 互動式畫布，階層可展開（d3-hwschematic 式）[O6]；不適合靜態文件 |

### V3 顏色數量

| 代號 | 內容 |
|---|---|
| K1 | 單色＋線型（粗細、虛線）；黑白列印安全 |
| K2 | 2–3 色，依 signal class（data／control／clock-reset） |
| K3 | 5–7 色，class 全分色。【推測】超過 7 色後難以靠圖例記憶，且色盲安全配色更難選 |
| K4 | 底色表達 stage 或 group，連線用中性色 |

### V4 形狀

| 代號 | 內容 |
|---|---|
| H1 | 全矩形＋kind 文字 |
| H2 | 慣用符號：mux 梯形、register 窄條＋時脈三角、其餘圓角矩形 |
| H3 | 投影片卡片風（圓角、圖示、陰影）。【推測】觀感佳但偏離工程圖慣例，且 port 位置較難規範 |

### V5 擺放方式與 layout 演算法

| 代號 | 內容 | 依據 |
|---|---|---|
| L1 | 分層（Sugiyama）：ELK Layered 或 dot | [O9][P1] |
| L2 | 樣板格線：由 stage × lane 直接算格位 | [O19]；可用 ELK partitioning 近似 [O10] |
| L3 | 約束最佳化：HOLA／ARCOL 類，或自建 ILP／CP 模型 | [P11][P13] |
| L4 | schematic 專用 placer：依邏輯層級排欄＋通道（ASG、SPAR、Nlview 類） | [P6][P7][C1] |
| L5 | 多候選＋評分挑選（可疊在 L1–L4 之上） | [P9]；TALA 的多 seed 做法 [O18] |

### V6 連線可否交叉

| 代號 | 內容 |
|---|---|
| X1 | 允許交叉；只用 junction dot 區分「相接」與「跨過」 |
| X2 | 允許交叉，但畫成缺口或橋 |
| X3 | 依重要性加權最小化；**資料線零交叉列為硬限制**，control × control 可接受 [P8][P10] |
| X4 | 用具名樁、跨頁標籤取代長線，從源頭消除交叉 |

### V7 繞線方式

| 代號 | 內容 |
|---|---|
| R1 | 分層引擎內建的正交走線 [O9] |
| R2 | 節點定位後用 libavoid 避障＋nudging [O24][P14] |
| R3 | 通道／軌道分配，fan-out 走主幹再分支 |
| R4 | 曲線或折線（dot 預設）；【實測】port 接得對但主幹不直 |
| R5 | 介面成束：一組 net 畫成一條粗線，標成員數 |

### V8 抽象層級（第三層要支援到哪）

抽象由第二層決定；第三層的變因是「看得懂哪些 `kind`」。

| 代號 | 內容 |
|---|---|
| G1 | 只有 module 方框 |
| G2 | module＋pipeline／state register |
| G3 | 再加 mux、ALU 等資料路徑元件（各自有形狀與 port 排列慣例） |
| G4 | 巢狀複合節點（parent_id），可整組折疊或展開 |

未知的 `kind` 一律退回矩形並回報，不可猜形狀。

### V9 設計型態資訊對排版有無幫助

| 代號 | 內容 | 評估 |
|---|---|---|
| D0 | 不使用 | 只能得到通用分層圖（N1）。 |
| D1 | 全域 tag（pipeline、cpu…）選樣板 | 便宜，但同一設計內常混有不同型態的子塊，容易選錯。 |
| D2 | 每個 block 的 `stage_index`／`lane` | **幫助最大**：直接決定左右與上下。 |
| D3 | 每個 (net, sink) 的 `flow_role` | 決定回授走外圈、控制線走控制道。 |
| D4 | 第三層自行由圖推導（SCC 找回授、register 切層） | 不需額外欄位，但等於在第三層做語義分析，與分層原則衝突。 |

各型態的具體用法：
- **pipeline**：stage → 欄，register 壓在欄界上；TL-Verilog／Makerchip 即如此 [O19]。
- **combinational**：沒有 stage，用邏輯深度當層（ASG 的做法）[P6]。
- **CPU**：【推測】沿用教科書五級管線圖的慣例（stage 由左到右、forwarding 與 stall 走上下外圈）最不違反讀者預期。
- **GPU／大量平行通道**：【推測】需要「重複 N 份」的表示法（疊框＋×N），spec 要有 `replication` 欄位，否則「全部要畫」會讓圖爆量。

結論：**有幫助，但要 D2 + D3 的粒度**；D1 單獨使用不足。

### V10 技術棧

| 代號 | 內容 | 取捨 |
|---|---|---|
| T1 | TypeScript：elkjs＋自寫 SVG 與 `.drawio` 匯出 | ELK 原生生態；與瀏覽器編輯器共用程式碼。 |
| T2 | Python：Graphviz、networkx、OR-Tools | 與第一、二層（多半是 Python）同語言；【實測】Graphviz 正交＋port 不可用。 |
| T3 | Web 編輯器：React Flow＋elkjs | 互動最好；多一個前端專案要維護。 |
| T4 | 以 D2 為後端（ELK／TALA） | 少寫排版程式；受限於 D2 的表達力與 port 模型。【推測】D2 對「固定 port 位置」的支援不如直接用 ELK。 |
| T5 | 商用函式庫（yFiles、Nlview） | 功能最完整；授權費與開源發佈衝突（提案書要在 GitHub 開源）。 |

### V11 技術債

| 代號 | 來源 | 緩解 |
|---|---|---|
| TD1 | schema 演進 | `schema_version`＋遷移腳本；核心圖與 hints／overrides 分檔。 |
| TD2 | 排版引擎升版改變輸出 | 釘選版本；golden 圖回歸測試；輸出記錄 `layout_engine_version`。 |
| TD3 | 人工修改回收 | 以 override 檔為準、`.drawio` 為交付副本；ID 消失時的 override 垃圾回收。 |
| TD4 | LLM 漂移、成本、機密外洩（AI 版） | 把 AI 輸出固化成檔、記錄模型與 prompt 版本；提供去識別化視圖。 |
| TD5 | 沒有測試語料就無法談美感 | 及早建立 10–20 個手工審核的 spec 與「工程師偏好」標註。 |

### V12 AI 在第三層的角色（僅 AI 版）

| 代號 | 內容 |
|---|---|
| M1 | 提版面偏好（hints） |
| M2 | 看渲染結果當評審，回傳參數建議 |
| M3 | 撰寫圖的 DSL |
| M4 | 把自然語言編輯指令轉成 override patch |
| M5 | 離線調整排版參數與啟發式（線上不出現） |

### V13 驗證手段

| 代號 | 內容 |
|---|---|
| Q1 | schema 驗證：ID 唯一、端點存在、方向與位寬一致 |
| Q2 | round-trip：把輸出重新解析成 block／port／net，以穩定 ID 與 spec 逐一比對 |
| Q3 | 幾何檢查：線不穿方塊、標籤不相撞、最小字級、畫布邊界 |
| Q4 | mutation test：故意注入錯誤，確認檢查器抓得到 |
| Q5 | 人工審核（抽象是否恰當只能靠人） |

### 共用範例電路 `pipe4`

所有方案都畫同一份 spec：4-stage valid／ready pipeline，stage 3 前有 forwarding mux，由一個 controller 產生 `en` 與 `fwd_sel`。

- 10 個 block：S1–S4 四個組合邏輯塊、P1–P4 四個 pipeline register、FWD MUX、Pipe Ctrl。
- 48 個 port（含 8 個頂層 boundary port）、18 條 net；`en` 一對四、`clk`／`rst_n` 各一對五、`p3_q` 一對二（一個前饋、一個回授）。
- 檔案：[`example/pipe4.v`](example/pipe4.v)（子模組為黑盒，未模擬）、[`example/pipe4.diagram.json`](example/pipe4.diagram.json)（依目前 spec 3.2–3.4 的欄位，另加 `scope`）、[`example/pipe4.layout-hints.json`](example/pipe4.layout-hints.json)（版面語義，獨立一檔）、[`example/pipe4.dot`](example/pipe4.dot)。

---

## 3. 不可用 AI 的 5 個方案（重美感）

這裡的「不可用 AI」指第三層執行時不呼叫任何模型。正確性由 Q1–Q3 保證，所以設計重點放在版面品質。五個方案不互斥：N1 是地基，N2／N3 是擺放策略，N4 是挑選機制，N5 是呈現政策。

### N1　分層基線：ELK Layered，所有 net 畫實線

![N1](svg/n1_layered_baseline.svg)

- **變因組合**：S1+S2｜Z3｜K2｜H2｜L1｜X1 或 X2｜R1｜G3｜D0｜T1｜Q1–Q3。
- **spec 欄位**：只需核心圖。block 的 `id`、`label`、`kind`、`parent_id`；port 的 `owner_block_id`、`direction`、`width`、`class`、`scope`；net 的 `source`、`targets`、`width`、`class`。選用 `preferred_side`。
- **優點**：工最少；ELK 成熟且懂 port 與複合節點 [O9]；任何設計型態都畫得出來，是其他方案的退路；輸出可重現。
- **缺點**：沒有設計意圖。示意圖中 controller 落在第一層、`in_ready` 橫越整張圖到東側、`clk`／`rst_n` 的扇出與資料線交錯。固定畫布不保證。引擎升版會改變輸出（TD2）。
- **實作難度**：低，約 2–3 人週【推測】。工作項：schema 驗證、轉 ELK JSON、文字量測、SVG 與 `.drawio` 匯出、round-trip 檢查。
- **美感評估**：建立幾何指標基準值（加權交叉、彎折、線長、標籤碰撞、長寬比誤差）；之後每個方案都回報「相對 N1 的改善」。
- **示意圖量測**：交叉 9（其中 4 個涉及資料線）、彎折 10、線長 6654 px、18 條 net 全以實線畫出。9 個交叉中有 8 個涉及 `clk` 或 `rst_n`。

### N2　Stage × Lane 格線樣板

![N2](svg/n2_stage_lane_grid.svg)

- **變因組合**：S1+S2+S3（+S4）｜Z1｜K4｜H2｜L2｜X3｜R3｜G3｜D2+D3｜T1。
- **spec 欄位**：核心圖之外，必要：組合邏輯塊的 `stage_index`、register 的 `stage_boundary`、`lane`（data／control／feedback）、每個 (net, sink) 的 `flow_role`。注意 `p3_q` 這條 net 有兩個 sink，一個是前饋、一個是回授，所以 `flow_role` 不能只掛在 net 上。選用：`bundles`、`clk`／`rst_n` 的 `presentation: implicit_marker`。
- **優點**：符合讀者對 pipeline 的心智模型（stage 為欄、register 壓在欄界，與 TL-Verilog／Makerchip 的畫法一致 [O19]）；主幹全直；格位由語義決定，RTL 小改後相對順序不變，天然保住 mental map [P15]；結果可預期。
- **缺點**：只適用有 stage 語義的設計；`stage_index` 要可靠（retiming、分岔管線、多週期路徑時第二層不一定給得出）；給不出就退回 N1；lane 佔垂直空間；`clk`／`rst_n` 不畫線需要政策同意。
- **實作難度**：中，約 4–6 人週【推測】。可先用 ELK 的 partitioning＋layerConstraint＋model order 近似 [O10]，不夠再自寫格線 placer 與通道走線。
- **美感評估**：主幹直線率（前饋資料線零彎折的比例）、stage 單調性、對齊率；與 N1 做工程師兩兩偏好比較；記錄拿到圖後在 draw.io 需要移動幾個物件。
- **示意圖量測**：交叉 1（`fwd_sel` × `en`，control × control）、資料線交叉 0、彎折 5、線長 3202 px。

### N3　固定畫布的約束最佳化（含換行）

![N3](svg/n3_constraint_fixed_canvas.svg)

- **變因組合**：S1–S3｜Z2（硬限制）｜K2｜H2｜L3｜X3+X2｜R2｜G3｜D2｜T2 或 T1。
- **spec 欄位**：再加 `canvas_preset`、最小字級、`importance`（交叉權重）、`wrap_allowed`（可在哪些 stage 邊界換行）、`lock_level`、`group`。
- **優點**：正面處理「固定比例＋字要夠大」；目標以字典序明寫（先硬限制，再資料線交叉，再其他）；排不進去時能回報 `layout_infeasible` 與原因。
- **缺點**：演算法最複雜；固定長寬比的正交排版在學界也才剛有專門方法 [P13]；求解時間可能隨圖變大而非線性成長；換行破壞由左到右的閱讀流；彎折變多。【推測】HOLA／ARCOL 原本針對無 port 的一般網路，套到帶 port 的方塊圖需要改造。
- **實作難度**：高，約 8–12 人週【推測】。
- **美感評估**：畫布容納率（基準集有多少張能在最小字級下塞進指定畫布）、長寬比誤差、空白率，加上 N1 的指標；另記求解時間。
- **示意圖量測**：720 × 540，交叉 1（control × control，以缺口表示）、資料線交叉 0、彎折 13、線長 4403 px。

### N4　多候選＋字典序美感評分

![N4](svg/n4_portfolio_scoring.svg)

- **變因組合**：L5 疊在 L1／L2／L3 之上｜X3｜Q3 的量測擴充為評分｜其餘同底層方案。
- **做法**：對同一份 spec 產生 K 個**合法**候選（只改允許變動的自由度：方向、controller 放上或下、回授走廊、port 側、分層策略、seed），逐一量測，依字典序挑選。
- **spec 欄位**：`importance`、`class`（決定交叉權重）、`lock_level`（哪些自由度可動）。評分設定本身要版本化（`style_version`）。
- **優點**：把「美感」變成可回歸測試的數字；與引擎無關；是 A2、A5 的前置條件。
- **缺點**：指標不等於美感（Purchase 的指標只驗證了部分 [P8][P9]，HOLA 顯示人還看重緊湊與對稱 [P12]）；執行時間乘以 K；需要全序的決勝規則才可重現；候選可能全都普通。
- **實作難度**：中，在 N1 之上約 3–5 人週【推測】。
- **美感評估**：這個方案本身就是評估工具。要驗證的是**評分與人的一致性**：收集工程師兩兩偏好，計算評分排序與人工排序的相關，據此調整字典序與權重。
- **示意圖量測**：三個候選的硬限制違規皆 0、資料線交叉皆 0、總交叉皆 1；彎折 6／5／5；線長 3600／3052／3202 px。依字典序由 B 勝出（彎折同為 5 時比線長）。這個例子也顯示：只看交叉數分不出高下。

### N5　具名訊號樁＋介面成束（單色、全矩形）

![N5](svg/n5_stubs_and_bundles.svg)

- **變因組合**：S1+S2+S4｜Z1 或 Z4｜K1｜H1｜L1 或 L2｜X4｜R5+R1｜G3｜D1｜T1。
- **spec 欄位**：`bundles`（成員、協定、所在側）、全域訊號束、每條 net 的 `presentation`（wire／stub／implicit）、`short_label`；圖例自動產生。成束詞彙建議沿用 IP-XACT 的 busInterface 概念 [O21]。
- **優點**：交叉歸零；黑白列印安全；能撐到 SoC 等級（全域訊號很多時）；符合 EDA 圖面慣例（net label、跨頁 connector [C6]）。
- **缺點**：連線不能用眼睛沿線追，要對標籤，對「追路徑」類任務不利 [P10]；容易濫用；成束後個別成員的方向要另外標；必須先確認這不違反「全部要畫」。
- **實作難度**：低到中，在 N1 之上約 3–4 人週【推測】。
- **美感評估**：追線任務的正確率與時間（使用者研究）；標籤數量；灰階列印後的可辨識度檢查。
- **示意圖量測**：交叉 0、彎折 3、線長 1652 px；畫成線的只有 13 條視覺邊（10 條資料線、`fwd_sel`、2 條介面束），`en`、`clk`、`rst_n` 以具名樁表示。

---

## 4. 可用 AI 的 5 個方案（重正確性）

共同原則：**AI 的輸出永遠不是最終圖。** 最終圖一律由確定性程式依核心圖畫出，並通過 Q2 round-trip。AI 能寫的只有三種東西：hints、白名單參數、override patch；A3 是唯一讓 AI 碰到拓撲描述的方案，因此風險最高。

### A1　AI 提版面偏好，確定性引擎排版

![A1](svg/a1_ai_hints_engine_layout.svg)

- **變因組合**：M1｜S1+S2+S5 必要、S3／S4 由 AI 補｜L1 或 L2｜Q1+Q2+Q3｜T1＋LLM API。
- **流程**：LLM 讀核心圖（加 `description`、`reason_included`，必要時加 RTL 片段）→ 輸出受 schema 限制的 `layout-hints.json`（stage、lane、flow_role、bundle、port 側）→ 驗證器檢查：只能引用既有 ID、列舉值合法、不含任何拓撲欄位、內部一致（例如沿資料邊的 stage 不可倒退）→ 引擎排版 → round-trip。
- **spec 欄位**：`source_refs`、`description`、`reason_included`（AI 的輸入）；AI 可動範圍或 `lock_level`；每筆 hint 的 `proposed_by`（模型與 prompt 版本）、`review_status`；hints 檔的 hash。
- **優點**：AI 在結構上改不了接線；hints 存檔後重生圖不必再呼叫模型，可重現；hint 不合法就丟掉，最差退化成 N1；token 成本低；與無 AI 版共用渲染器。做法與「模型提關係、求解器定位」的研究一致 [A8]。
- **缺點**：錯的 hint 會得到「正確但難看」的圖；需要可機器檢查的一致性規則；hint schema 限制了表達力；label 與描述會送到模型（機密性）。
- **實作難度**：中，在 N1／N2 之上約 2–3 人週【推測】。
- **正確性評估**：round-trip 通過率必須 100%；逐欄位比對 AI hint 與人工標註 hint 的準確率；非法 hint 比例；凍結 hints 後同輸入是否逐位元相同；相對 N1 的美感分數差。
- **示意圖說明**：三個被採納的 hint 與一個被拒絕的 hint（把 P1–P4 合併成 register bank，會少畫 spec 元件）。量測同 N2：交叉 1、彎折 5。

### A2　VLM 評審迴圈（只能回傳白名單參數）

![A2](svg/a2_vlm_critic_loop.svg)

- **變因組合**：M2｜底層為 N4｜Q2+Q3｜VLM。
- **流程**：引擎出圖 → 渲染成圖片 → VLM 依結構化格式指出問題並建議參數（層位、port 側、是否啟用隱含時脈標記）→ 只套用白名單內的參數 → 重排 → round-trip → 最多 3 輪。
- **spec 欄位**：`importance`、`lock_level`、可調參數白名單；評審輸出的 schema。
- **優點**：能指出幾何指標量不到的問題（閱讀順序、分組語義、標籤是否誤導）；「產生 → 評審 → 修正」在論文插圖領域已有成果 [A3]；模型對圖的可讀性敏感 [A6]。
- **缺點**：每輪都要渲染與呼叫模型，成本與延遲高；評審可能前後不一或來回震盪；VLM 的美感評估能力與人仍有落差 [A7]。【推測】VLM 對 RTL 方塊圖的偏好是否貼近硬體工程師，目前沒有證據，需自行驗證。
- **實作難度**：中到高，在 N4 之上約 3–4 人週【推測】。
- **正確性評估**：每輪 round-trip；評審建議中「超出白名單」的比例（應被全部擋下）；VLM 排序與工程師排序的一致性；收斂輪數；每輪指標變化；無效建議比例。
- **示意圖說明**：第 1 輪是 N1 的輸出，四個被圈出的問題與對應的參數建議；套用後交叉由 9 降到 1。

### A3　LLM 撰寫圖 DSL，LVS 式比對與修復

![A3](svg/a3_llm_dsl_lvs_repair.svg)

- **變因組合**：M3｜S1+S2+S5｜DSL 後端（T4：D2＋ELK／TALA，或自訂 JSON）｜Q1+Q2+Q4。
- **流程**：LLM 輸出受限 DSL（block、port、edge、group、near，不含座標）→ 解析成圖 → 與 spec 以穩定 ID 比對，列出多畫、漏畫、接錯 → 把差異回饋給 LLM 修正 → 超過迭代上限就改由程式直接從 spec 產生 DSL。
- **先講清楚一個限制**：DSL 的拓撲部分其實可以由程式從 spec 直接生成，讓 LLM 來寫只增加風險。LLM 真正的貢獻只剩版面指令與註解，這時 A3 會退化成 A1。只有當團隊需要「AI 自由加說明框、巢狀分組、非電氣註解」時，A3 才比 A1 多出價值。
- **spec 欄位**：核心圖的正規化形式與 hash；能在 DSL 往返後存活的 ID 命名規則；允許 AI 新增的 `annotation` 類別（明確標為非電氣）。
- **優點**：表達力最高；可借用現成 DSL 生態；可加入解說性註解。
- **缺點**：正是提案書指出的問題（多接、少接、幻想接線），完全依賴比對器；token 隨圖變大；修復迴圈可能不收斂；輸出不可重現。
- **實作難度**：中，約 4–6 人週【推測】；核心是比對器。
- **正確性評估**：首次輸出完全相符率；修復後完全相符率（不到 100% 就走退路）；迭代次數；**比對器本身的 mutation test 偵測率必須 100%**；每張圖成本。「重新解析再比對」的做法已有先例 [A10][A11][A12]。
- **示意圖說明**：一條被攔下的多餘連線（`b.s2.y → b.s3.a`）與一條被補回的漏線（`n.fwd_sel`）。

### A4　自然語言編輯 agent，只產生 override patch

![A4](svg/a4_nl_edit_override_patch.svg)

- **變因組合**：M4｜S5（`lock_level`）＋ override 檔｜支援位置約束的引擎｜Q1+Q2。
- **流程**：使用者以自然語言描述修改 → AI 輸出 `layout-overrides.json` 的 patch（`preferred_region`、`preferred_side`、`route_corridor`、`align_with`…）→ 驗證只含白名單鍵且 ID 存在 → 重排 → 確認拓撲差異為 0。
- **spec 欄位**：穩定 ID、`aliases`／`short_label`（讓「那個控制器」對得到 ID）、override schema、`lock_level`。
- **優點**：直接服務「結果可人工修改」；AI 碰不到拓撲；patch 可 diff、可回放，並與 draw.io 拖拉產生的 override 合併；任務範圍小，容易做穩。TALA 的「部分給座標、其餘自動」正是這種使用情境 [O15]。
- **缺點**：自然語言指涉有歧義；override 會累積並互相衝突，RTL 改版後 ID 消失要回收（TD3）；引擎要能遵守約束。ELK 現成的約束手段主要是首末層、partition、model order 與 interactive [O10]，【推測】任意區域擺放可能需要自寫 placer。
- **實作難度**：中，在 override 機制之上約 3–5 人週【推測】。
- **正確性評估**：拓撲差異恆為 0；指令達成率（把意圖寫成可檢查的述詞，例如「ctrl 的 y 大於所有 register 的 y」）；之後還需手動調整的步數；RTL 改版後 override 的存活率。
- **示意圖量測**：交叉 1、彎折 5、線長 3052 px（與 N4 的候選 B 相同版面）。

### A5　離線 autoresearch 式調參，線上純確定性

![A5](svg/a5_offline_autoresearch_tuning.svg)

- **變因組合**：M5（僅開發期）｜線上為 N2＋N4｜Q2 作為 guard。
- **流程**：agent 只允許改一個檔（排版參數、評分權重或某個啟發式）→ 在基準集上跑評分 → 主指標變好且 guard 通過才保留，否則還原 → 重複 [A15][A16]。guard：round-trip 差異為 0、硬限制違規為 0、執行時間不超標。
- **spec 欄位**：執行期不需要任何額外欄位。需要的是**基準語料**（一組 spec，最好附工程師偏好標註）與 `importance`。
- **優點**：線上零模型呼叫，正確性與可重現性等同無 AI 版；產物是可審查的 git 歷史；執行期零 AI 成本。**這個方案同時可用於「不可用 AI」的部署情境**，因為 AI 只在開發期出現。
- **缺點**：會最佳化指標而不是美感（指標設錯就學歪）；需要 N4 的評分與足夠的語料；可能對基準集過擬合；agent 改出來的啟發式要有人審。
- **實作難度**：N4 完成後屬低到中，約 1–2 人週設置【推測】。
- **正確性評估**：guard 全數通過；保留集（未參與調參）上的分數；保留集上的工程師偏好；每次變更的 diff 是否可讀。
- **示意圖說明**：上半是線上輸出（與 N2 同一支程式）；下半的實驗曲線是**示意資料，不是實測**。本次沒有實際執行 autoresearch，因為它需要一個可量測的程式碼庫，而排版程式與評分都還不存在。

---

## 5. 兩個版本需要的 spec：審慎比較

### 5.1 逐欄位比較

| 欄位群 | 無 AI 版 | AI 版 | 差異的原因 |
|---|---|---|---|
| 核心圖 S1（id、port、net、width、direction） | 必要 | 必要 | 相同。這是唯一的事實來源，也是 round-trip 的基準。 |
| 語義標籤 S2（kind、role、class） | 必要，**封閉列舉** | 必要；可容忍 `unknown` | 無 AI 版遇到未知值只能退回矩形。AI 版可提議分類，但提議要標記來源。 |
| 版面語義 S3（stage、lane、flow_role、importance、group） | **必要，否則美感無從談起** | 選用；缺的由 AI 提議 | 無 AI 的第三層沒有理解能力，意圖必須由第二層明確給。這是兩版最大的差異。 |
| 成束與呈現 S4（bundles、presentation） | N5 必要，其餘選用 | 選用；AI 可提議成束 | 同上。 |
| `source_refs` | 選用（放進 draw.io metadata 供查閱） | **必要** | AI 需要回頭看 RTL 才能判斷 stage；審核者要能追溯每個 AI 提議的依據。 |
| 自由文字（`description`、`reason_included`） | 渲染器**完全不讀** | **重要輸入** | 對 AI 是主要線索；同時是機密外洩與 prompt injection 的入口。 |
| provenance、`review_status` | 選用 | **必要**（每筆 hint 一份） | 要分得出「第二層給的」「人審過的」「AI 猜的」。 |
| `lock_level`／AI 可動範圍 | 只用於人工鎖定 | **必要** | 界定 AI 能改什麼；A2、A4 的白名單由此而來。 |
| 核心圖 hash、不變量 | 選用 | **必要** | 確認 AI 流程前後核心圖未被動過。 |
| `aliases`、`short_label` | 選用（縮小時用） | A4 必要 | 自然語言指涉要對得到 ID。 |
| 可重現資訊 | 引擎版本、style 版本、seed | 再加模型名稱、prompt 版本、**固化的 hints 檔** | AI 版的可重現性靠「把 AI 輸出存成檔」。 |
| 去識別化視圖 | 不需要 | 外部模型時需要 | 可只送 ID 與 kind、不送真實訊號名；【推測】這會降低 AI 提議的品質，需實測取捨。 |

### 5.2 幾點容易忽略的差別

1. **「無 AI 版的 spec 比較簡單」是錯覺。** 它需要的欄位更多、更嚴格，因為第三層沒有任何補洞能力。AI 版的核心 spec 可以較薄，但要多一層信任管理。
2. **`flow_role` 的粒度要到 (net, sink)。** 範例中 `p3_q` 同時有前饋與回授兩個 sink；只掛在 net 上，兩版都會畫錯走廊。
3. **第二層本身就用了 LLM（提案書的第一步）。** 所以「第三層不可用 AI」不等於整條管線沒有 AI。無 AI 版的版面語義可以由第二層的 LLM 產生，但那樣它就繼承了同樣的可信度問題。也可以走 §1.3 的確定性路線（由 register 與資料流推導 stage）。**建議在 spec 裡對版面語義一律記錄來源**，不分版本。
4. **兩版不該有差別的地方**：ID 規則、「全部要畫」的檢查、override 檔格式、round-trip 的定義。這些一旦分岔，兩版就無法共用測試語料。
5. **未知值的處理方向相反**：無 AI 版遇到缺欄位應該退回通用排版並回報；AI 版可以補，但補的值預設是 `needs_review`，正式文件只用審過的。
6. **評估的重心相反**：無 AI 版的正確性是既定的，要花力氣量美感（指標、偏好、修圖成本）；AI 版的美感可沿用同一套量法，要多花力氣量「AI 有沒有越界」。

### 5.3 建議的檔案切分

| 檔案 | 誰寫 | 第三層能否修改 | 兩版差異 |
|---|---|---|---|
| `diagram.json`（核心圖＋語義標籤） | 第二層 | 否 | 無 |
| `layout-hints.json`（版面語義，每筆帶來源） | 無 AI 版：第二層或人；AI 版：AI 提議、人審 | 僅 AI 版可寫 | **只有作者不同，schema 相同** |
| `layout-overrides.json`（位置、側、走廊、waypoint） | 人（draw.io 拖拉）或 A4 | 是 | 無 |
| `.drawio`／SVG／PDF | 渲染器 | 輸出物 | 無 |

這樣切的好處：AI 版＝無 AI 版＋「hints 與 overrides 多了一位作者」。兩版用同一個渲染器、同一套 golden 圖與同一個 round-trip 檢查器。

### 5.4 待決事項

1. 「全部要畫」是否限定 net 必須畫成線？還是允許 `implicit`、`stub`、成束三種呈現？（影響 N2、N5、A1、A2）
2. 頂層 output 能否放在西側（例如 `in_ready` 跟著輸入介面）？
3. 版面語義由誰負責產生與審核？確定性推導、第二層 LLM、還是人工？
4. 固定畫布排不進去時的順序：換行、分頁、成束、還是直接回報失敗？
5. AI 版若用外部模型，哪些欄位可以外送？

---

## 6. 參考資料

URL 皆為本次搜尋實際取得或既有研究文件已引用者。標「二手」者不是原始出處。

### 商用 EDA

- [C1] Concept Engineering 產品說明（Nlview）：https://www.etesters.com/catalog/5319B444-1422-08DF-AAF6-0347282CB55C/concept-engineering-gmbh/ （二手，產品目錄）
- [C2] Concept 與 JEDAT 的 OEM 新聞：https://www.embedded.com/?p=4135670
- [C3] NlviewJS 報導：https://www.techdesignforums.com/?p=7107 ；Nlview 與 Verific 連結套件：https://www.verific.com/?p=724
- [C4] Verdi 3 User Guide and Tutorial（目錄；第三方上傳）：https://studylib.net/doc/25730716/pdfslide.net-verdi-3-user-guide-and-tutorial
- [C5] Verdi Basic Training 投影片（第三方上傳）：https://picture.iczhiku.com/resource/eetop/sYKerlaHiASidvvV.pdf
- [C6] Intel Quartus Prime Pro 使用指南（Netlist Viewer 章節目錄）：https://www.intel.com/content/www/us/en/docs/programmable/683641/23-3/design-visualization-tools.html ；本次實際看到章節目錄的頁面（同一份指南）：https://intel.com/content/www/us/en/docs/programmable/683641/23-2/modify-io-delay-chain.html
- [C7] Intel Quartus Connectivity Tracer：https://intel.com/content/www/us/en/docs/programmable/683236/23-2/connectivity-tracer.html
- [C8] AMD UG906（Schematic Window）：https://docs.amd.com/r/2023.2-English/ug906-vivado-design-analysis/Using-the-Schematic-Window
- [C9] DVT Eclipse IDE：HDL Diagram Filters 教學：https://eda.amiq.com/tutorials/dvt-eclipse-ide-diagrams-how-to-use-hdl-diagram-filters
- [C10] AMIQ 新聞稿（design-oriented diagrams）：https://eda.amiq.com/press-releases/amiq-eda-unveils-new-verilog-and-vhdl-design-oriented-diagrams ；產生圖教學：https://eda.amiq.com/tutorials/dvt-eclipse-ide-diagrams-how-to-generate-hdl-diagrams
- [C11] Sigasi Graphics Configuration（legacy 文件）：https://insights.sigasi.com/legacy/eclipse/graphics
- [C12] Sigasi：Using Graphics Configuration：https://insights.sigasi.com/tech/using-graphics-configuration/ ；語法：https://insights.sigasi.com/tech/graphics.ebnf
- [C13] yFiles EdgeRouter：https://docs.yworks.com/yfiles-html/dguide/automatic-layouts-main-chapter/polyline_router.html ；授權類型：https://www.yworks.com/products/yfiles-for-html/license-types

### 開源工具

- [O1] Yosys `write_json`：https://yosyshq.readthedocs.io/projects/yosys/en/0.46/cmd/write_json.html
- [O2] netlistsvg：https://github.com/nturley/netlistsvg
- [O3] Yosys `viz` 指令說明：https://yosyshq.readthedocs.io/projects/yosys/en/0.40/cmd/viz.html
- [O4] Yosys 0.26 release notes：https://github.com/YosysHQ/yosys/releases/tag/yosys-0.26
- [O5] `viz` 的原始 commit（鏡像）：https://git.libre-chip.org/mirrors/yosys/commit/c9f4b06cb2256fc26b9a5c4a4070985e615388dd
- [O6] d3-hwschematic：https://github.com/nic30/d3-hwschematic
- [O7] HDElk：https://github.com/davidthings/hdelk
- [O8] SpinalHDL PR #1079（以 HDElk 產圖）：https://github.com/SpinalHDL/SpinalHDL/pull/1079
- [O9] ELK Layered：https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html
- [O10] ELK blog：Layered – Constraining the Model：https://eclipse.dev/elk/blog/posts/2023/23-01-09-constraining-the-model.html
- [O11] ELK model order 選項：https://eclipse.dev/elk/reference/options/org-eclipse-elk-layered-considerModelOrder-strategy.html ；port constraints：https://eclipse.dev/elk/reference/options/org-eclipse-elk-portConstraints.html ；wrapping：https://eclipse.dev/elk/reference/options/org-eclipse-elk-layered-wrapping-strategy.html
- [O12] ELK 選項群組頁（演算法清單含 Libavoid）：https://eclipse.dev/elk/reference/groups/org-eclipse-elk-layered-wrapping.html ；ELK JSON：https://eclipse.dev/elk/documentation/tooldevelopers/graphdatastructure/jsonformat.html
- [O13] Graphviz `splines` 屬性：https://www.graphviz.org/docs/attrs/splines/
- [O14] Graphviz 論壇：ortho 與 port 的權宜做法：https://forum.graphviz.org/t/ortho-edges-and-ports-a-partial-work-around/1937
- [O15] D2 blog：TALA is open-source：https://d2lang.com/blog/tala-is-open-source/
- [O16] D2 layout engines：https://d2lang.com/tour/layouts/
- [O17] TALA 開源報導（二手，含授權）：https://runtimewire.com/article/terrastruct-open-sources-tala-alexander-wang-winds-down-business
- [O18] TALA 開源報導（二手，含多 seed 說明）：https://ecosistemastartup.com/?p=105463
- [O19] RISC-V MYTH workshop（TL-Verilog／Makerchip 圖例）：https://www.github.com/aronsonj52/riscv_myth_workshop
- [O20] Formally Verifying WARP-V（TL-Verilog pipeline stage）：https://arxiv.org/pdf/1811.12474.pdf
- [O21] IP-XACT 設計階層說明（Agnisys，二手）：https://agnisys.com/?p=11497
- [O22] Intro to IP-XACT and Kactus2：https://github.com/kactus2/kactus2dev/files/14384168/Intro-to-IP-XACT-and-Kactus2.pdf
- [O23] Kactus2 介紹（二手）：https://www.linuxlinks.com/kactus2-graphical-eda-tool/
- [O24] libavoid：https://www.adaptagrams.org/documentation/libavoid.html
- [O25] libdialect（HOLA 實作）：https://www.adaptagrams.org/documentation/namespacedialect.html
- draw.io 檔案格式：https://www.drawio.com/docs/manual/editor/save-file-formats/ ；waypoints：https://www.drawio.com/docs/manual/connectors/waypoints-connectors/

### Graph drawing 論文

- [P1] Sugiyama et al., 1981：https://doi.org/10.1109/TSMC.1981.4308636
- [P2] Gansner et al., 1993：https://doi.org/10.1109/32.221135
- [P3] Brandes–Köpf 勘誤：https://arxiv.org/abs/2008.01252
- [P4] KLay Layered port constraints：https://doi.org/10.1016/j.jvlc.2013.11.005
- [P5] Tamassia, 1987：https://doi.org/10.1137/0216030
- [P6] ASG（1991）：https://scholars.lib.ntu.edu.tw/bitstreams/3f42ecd5-fc48-4b38-b397-618156a8f351/download
- [P7] SPAR（1993）：https://ieeexplore.ieee.org/document/238032/
- [P8] Purchase, Which aesthetic has the greatest effect on human understanding?（1997）：https://eprints.gla.ac.uk/35804
- [P9] Purchase, Metrics for Graph Drawing Aesthetics（2002）：https://research.monash.edu/en/publications/metrics-for-graph-drawing-aesthetics/
- [P10] An Eye Tracking Study into the Effects of Graph Layout（相關研究一節）：https://arxiv.org/pdf/0810.4431
- [P11] HOLA: Human-like Orthogonal Network Layout：https://ialab.it.monash.edu/~dwyer/papers/hola2015.pdf
- [P12] VIS 2015 會議報告投影片（HOLA 使用者研究摘要，二手）：https://www.idc.cs.mdx.ac.uk/wp-content/uploads/2015/12/2015-12-01-VIS-report.pdf
- [P13] ARCOL: Aspect Ratio Constrained Orthogonal Layout（2026）：https://arxiv.org/pdf/2603.29618
- [P14] Wybrow, Marriott, Stuckey, Orthogonal Connector Routing：https://findanexpert.unimelb.edu.au/scholarlywork/863594-orthogonal-connector-routing
- [P15] Orthogonal Order Preserving Layout Adjustment（mental map 文獻回顧）：https://arxiv.org/pdf/1502.03847
- [P16] Diagram Control and Model Order for Sugiyama Layouts：https://www.arxiv.org/pdf/2406.11393
- [P17] DeepGD：https://arxiv.org/pdf/2106.15347
- [P18] SmartGD：https://arxiv.org/abs/2206.06434v2
- [P19] Human Preference for Graph Drawings（JGAA）：https://jgaa.info/index.php/jgaa/article/download/paper603/2347
- [P20] DANA：https://tches.iacr.org/index.php/TCHES/article/view/8685
- [P21] ReIGNN：https://ar5iv.arxiv.org/html/2112.00806
- [P22] RELIC-GNN：https://arxiv.org/html/2512.15037v1
- 其他：Graph Layout Aesthetics in UML Diagrams：https://jgaa.info/index.php/jgaa/article/view/paper54 ；The Multi-Dimensional Landscape of Graph Drawing Metrics：https://par.nsf.gov//servlets/purl/10493393 ；OpenROAD global placement：https://openroad.readthedocs.io/en/latest/main/src/gpl/README.html

### AI 產圖

- [A1] DiagramAgent（CVPR 2025）：https://openaccess.thecvf.com/content/CVPR2025/html/Wei_From_Words_to_Structured_Visuals_A_Benchmark_and_Framework_for_CVPR_2025_paper.html
- [A2] DeTikZify（NeurIPS 2024）：https://neurips.cc/virtual/2024/poster/94474
- [A3] PaperBanana（ICML 2026）：https://icml.cc/virtual/2026/poster/65206
- [A4] PaperBanana 論文摘要頁（二手）：https://www.alphaxiv.org/abs/2601.23265.md
- [A5] next-ai-draw-io：https://github.com/DayuanJiang/next-ai-draw-io/wiki
- [A6] Graph Drawing for LLMs: An Empirical Evaluation：https://arxiv.org/html/2505.03678v1
- [A7] Can Vision–Language Models Assess Graphic Design Aesthetics?（ICLR 2026）：https://mlanthology.org/iclr/2026/an2026iclr-visionlanguage/
- [A8] LayoutVLM（含 Holodeck 的比較）：https://arxiv.org/abs/2412.02193
- [A9] AutoLayout（空間幻覺）：https://web3.arxiv.org/pdf/2507.04293
- [A10] DiagramEval：https://arxiv.org/abs/2510.25761
- [A11] Schemato（preprint）：https://arxiv.org/abs/2411.13899
- [A12] Weave（preprint）：https://arxiv.org/abs/2607.03835
- [A13] DeepRTL2：https://aclanthology.org/2025.findings-acl.336.pdf
- [A14] LLM for Verilog Code Generation 綜述：https://arxiv.org/abs/2512.00020
- [A15] autoresearch README（fork，保留原作說明）：https://github.com/jackneil/autoresearch
- [A16] autoresearch HPC fork（說明其追蹤 karpathy/autoresearch）：https://github.com/dmbala/autoresearch
- [A17] RTLViz 0.3.6（PyPI）：https://pypi.org/project/rtlviz/0.3.6/
- [A18] RTLViz 0.2.5（PyPI，早期架構）：https://pypi.org/project/rtlviz/0.2.5/
- [A19] Assessing Large Language Models in Generating RTL Design Specifications：https://arxiv.org/pdf/2512.00045
- 其他：DiagramGPT-Llama3（AAAI 2026）：https://ojs.aaai.org/index.php/AAAI/article/view/40286 ；LLM graph layout 評估：https://doi.org/10.1016/j.visinf.2025.100285 ；Eraser AI：https://docs.eraser.io/ai-diagrams ；Miro AI：https://miro.com/ai/flowchart-ai/

### 本次未能做到的事

- firecrawl、Exa、autoresearch 等外掛在此環境無法執行（沙盒無對外網路、無 Exa 連接器、autoresearch 需要既有程式碼庫與指標），調研改用內建網頁搜尋。
- 沒有實際執行 ELK／elkjs；N1–N5、A1–A5 為手排示意。唯一的引擎實測是 Graphviz 2.43.0。
- 各方案的人週數皆為粗估【推測】，未依團隊實際速度校準。
- 部分商用工具資訊來自第三方上傳的手冊或產品目錄（已標「二手」或「第三方上傳」），未能取得原廠最新文件。
