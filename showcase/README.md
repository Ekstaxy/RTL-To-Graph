# RTL-To-Graph 成果頁

打開方式：Windows 雙擊 `start.bat`；macOS / Linux / WSL 執行 `sh start.sh`。

腳本會把 `RTL-To-Graph-showcase.zip` 解壓到旁邊的 `RTL-To-Graph-showcase/`，然後用預設瀏覽器打開
`proof.html`。之後 `git pull` 拿到新版 zip 時，再執行一次就會重新解壓。整個頁面都是本機靜態檔，
不需要網路，也不需要架伺服器。

三個頁面互相有連結：

| 頁面 | 內容 |
|---|---|
| `proof.html` | x5 可證明狀態圖：23 張圖、10 項驗證全部通過的稽核結果 |
| `all.html` | 30 個設計的方塊圖、狀態圖、時序圖，逐張評分 |
| `index.html` | 與五個開源專案官方圖的並排比較，28 張卡片 |

zip 裡也附了 x5 的程式和交接文件 `x5_proven_graph/HANDOFF.md`；同一份程式也放在
`pipeline/experiments/x5_proven_graph/`，可以直接在 git 裡看。

同一個資料夾還有：

- `RTL-To-Graph_Agent_成果簡報.pptx`：階段成果簡報，用 AI agent 一句話產生三種圖的完整操作歷程、和開源工具的比較、目前限制。
- agent demo：雙擊 `pipeline/experiments/x6_agent_demo/start_agent.bat`（macOS 或 Linux 用 `start_agent.sh`），第一次會打開 `.env` 讓你貼上 Anthropic API key，之後就會打開 http://localhost:8765 。只需要 Python 3.10 以上，語料庫 30 個設計的結果已經打包在裡面。
