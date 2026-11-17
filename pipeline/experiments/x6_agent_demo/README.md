# RTL-To-Graph Agent（demo）

用一句話要圖。Claude 讀懂需求與設計，決定要畫哪種圖、看哪些訊號，再呼叫專案自己的管線把圖畫出來：

| 工具 | 背後的管線 | 圖上的東西憑什麼 |
|---|---|---|
| `analyze_design` | L1 標註（slang）+ e8/e9 | 時脈、reset、握手介面與每個訊號的角色；啟發式，agent 要用 `read_source` 確認 |
| `draw_block` | x1 bridge + x2 adapter + e3 版面引擎 | 論文版取交叉最少的版面；畫完從 SVG 反查連線 |
| `draw_fsm` | x5 證明器 + 獨立檢查器 | 每條轉移有模擬器重播的軌跡，沒畫的都證明不可能發生 |
| `draw_timing` | x4 模擬 + 波形繪製 + 五項檢查 | 波形來自模擬器，重播比對 |

## 啟動

1. 把 `.env.example` 複製成 `.env`（已經有就直接打開），在 `ANTHROPIC_API_KEY=` 後面貼上 key，存檔。`.env` 不會被提交進 git。
2. Windows 雙擊 `start_demo.bat`（WSL 裡則是 `bash start_demo.sh`），瀏覽器會打開 http://localhost:8765 。
3. 點一個範例或自己輸入，例如「spimemio 的狀態機怎麼運作？畫出來並解釋每個狀態」。

模型設定在 `config.json`：目前是 `claude-sonnet-5-5`、effort `medium`，並開了伺服器端 fallback：安全分類器拒絕時，API 改用備援模型重跑。要更強可改成 `claude-opus-5-5`。

不呼叫 API 也能先測工具：`python test_tools.py`。

## 用自己的設計

把 design 寫成 `dir:/絕對路徑#頂層模組`，例如「畫 dir:/home/me/myip#uart_top 的架構圖」。語料庫裡的 30 個設計直接取用已經跑好、已稽核的結果，所以很快；新設計要現場跑管線，幾分鐘。

## 每次對話的紀錄

`runs/<session>/transcript.jsonl` 記下每一步：使用者輸入、agent 的思路摘要、每次工具呼叫與結果、每張圖、最後回答。做簡報時用它對照截圖。
