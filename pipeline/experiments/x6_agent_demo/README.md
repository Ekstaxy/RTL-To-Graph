# RTL-To-Graph Agent（demo）

用一句話要圖。Claude 讀懂需求與設計，決定要畫哪種圖、看哪些訊號，再呼叫專案自己的管線把圖畫出來。

## 啟動，組員照這樣做

1. 需要 Python 3.10 以上和一把 Anthropic API key。
2. Windows 雙擊 `start_agent.bat`；macOS 或 Linux 執行 `sh start_agent.sh`。
3. 第一次會打開 `.env`：在 `ANTHROPIC_API_KEY=` 後面貼上 key，存檔，再執行一次。`.env` 不會被提交進 git，倉庫裡只有 `.env.example`。
4. 瀏覽器會打開 http://localhost:8765 。點一個範例，或自己打一句話，例如「spimemio 的狀態機怎麼運作？畫出來並解釋每個狀態」。

腳本會建立 `.venv`、安裝 `anthropic`、把 `demo_cache.zip` 解壓到 `cache/`。語料庫的 30 個設計都有現成結果，所以不需要 WSL、Yosys 或模擬器。
模型設定在 `config.json`：`claude-sonnet-5-5`、effort `medium`，開了伺服器端 fallback；要更強可改成 `claude-opus-5-5`。

## 背後是什麼

| 工具 | 背後的管線 | 圖上的東西憑什麼 |
|---|---|---|
| `analyze_design` | L1 標註（slang）+ e8/e9 | 時脈、reset、握手介面與每個訊號的角色；啟發式，agent 要用 `read_source` 確認 |
| `draw_block` | x1 bridge + x2 adapter + e3 版面引擎 | 論文版取交叉最少的版面；畫完從 SVG 反查連線 |
| `draw_fsm` | x5 證明器 + 獨立檢查器 | 每條轉移有模擬器重播的軌跡，沒畫的都證明不可能發生 |
| `draw_timing` | x4 模擬 + 波形繪製 + 五項檢查 | 波形來自模擬器，重播比對 |

`demo_cache.zip` 由 `make_cache.py` 產生：x4 的標註與時序圖、方塊圖、x5 稽核過的憑證與圖（out17，稽核乾淨）。原始碼直接讀倉庫裡的 `layers/l1_extract/data/rtl/`。

## 用自己的設計

把 design 寫成 `dir:/絕對路徑#頂層模組`。這要現場跑三條管線，需要專案的完整環境（WSL、`uv` 的 `rtl2d-l1` 套件、Yosys、Icarus Verilog 12、z3），路徑設定在 `config.json` 的 `x5_python`、`path_extra`、`uv`。

## 紀錄與簡報

每次對話存在 `runs/<session>/transcript.jsonl`。`deck/` 是做階段成果簡報的腳本：`drive.py` 送請求、`shoot.py` 截圖、`crop.py` 裁切、`collect_deck_data.py` 讀稽核與對標數字、`make_deck.js` 產生 pptx。

不呼叫 API 也能先測工具：`python test_tools.py`。
