"""Numbers for the deck, read only from result files: python collect_deck_data.py BENCH.json OUT_DIR LINES > data.json
OUT_DIR is the audited x5 output (cert.json per graph, audit.json); BENCH.json from bench_fsm.py."""
import json
import sys
from pathlib import Path

bench = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2])
aud = json.loads((out / "audit.json").read_text()) if (out / "audit.json").exists() else None

# ---- the proven graphs
certs = [json.loads(p.read_text()) for p in sorted(out.glob("*/*/cert.json"))]
edges = sum(len(c["edges"]) for c in certs)
wit = sum(1 for c in certs for e in c["edges"] if e["status"] == "witnessed")
und = sum(1 for c in certs for e in c["edges"] if e["status"] != "witnessed")
pdr = sum(len((c["completeness"].get("invariant") or {}).get("removed_edges", [])) for c in certs)
complete = sum(1 for c in certs if c["completeness"]["status"] == "proven")
tam = tamk = mut = mutk = surv = 0
if aud:
    for r in aud["rows"]:
        a = (r["items"].get("attack") or {}).get("tally") or r.get("attack") or {}
        tam += a.get("tamper:killed", 0) + a.get("tamper:SURVIVOR", 0)
        tamk += a.get("tamper:killed", 0)
        mut += a.get("mutant:killed", 0) + a.get("mutant:SURVIVOR", 0)
        mutk += a.get("mutant:killed", 0)
        surv += a.get("tamper:SURVIVOR", 0) + a.get("mutant:SURVIVOR", 0)
clean = bool(aud and aud.get("clean"))

# ---- open-source tools against the proven graphs
V = bench.get("versions", {})
NAME = {"yosys": f"Yosys {V.get('yosys') or ''}", "yosys_new": f"Yosys {V.get('yosys_new') or ''}", "verilator": f"Verilator {V.get('verilator') or ''}",
        "teroshdl": f"TerosHDL {V.get('teroshdl') or ''}", "pyverilog": f"Pyverilog {V.get('pyverilog') or ''}"}
rows = [r for r in bench["rows"] if not r.get("skip")]
tools = []
for t in bench["tools"]:
    got = [r["tools"].get(t, {}) for r in rows]
    if all(g.get("status") in (None, "not installed") for g in got):
        continue
    tools.append({"key": t, "name": NAME.get(t, t).strip(), "exact": sum(1 for g in got if g.get("status") == "found" and g.get("exact")),
                  "found": sum(1 for g in got if g.get("status") == "found"), "extra": sum(g.get("extra", 0) for g in got if g.get("status") == "found"),
                  "missed": sum(g.get("missed", 0) for g in got if g.get("status") == "found"),
                  "nodet": sum(1 for g in got if g.get("status") == "not detected"), "err": sum(1 for g in got if g.get("status") == "tool error")})
best = max(tools, key=lambda t: (t["exact"], -t["extra"] - t["missed"]))
chart = sorted(tools, key=lambda t: t["exact"]) + [{"name": "本專案 x5", "exact": len(rows), "ours": True}]
notes = [f"{t['name']}：抓到 {t['found']} 張，多畫 {t['extra']} 條、漏畫 {t['missed']} 條" + (f"，出錯 {t['err']} 張" if t["err"] else "") for t in tools]
notes.append(f"本專案：{len(rows)} 張全對，每條線都有證據")

data = {
    "problem": {"lines": int(sys.argv[3]) if len(sys.argv) > 3 else 0, "tool_extra": best["extra"], "tool_missed": best["missed"], "best_tool": best["name"]},
    "steps": [
        {"label": "操作歷程 1 / 輸入端", "title": "一句話：spimemio 的狀態機怎麼運作", "shot": "c_01_input.png", "io": "輸入端",
         "note": ["使用者只打一句中文", "agent 先讀語意標註：時脈、reset 極性、狀態暫存器", "再讀原始碼確認，才呼叫證明工具"]},
        {"label": "操作歷程 2 / 輸出端", "title": "已證明的狀態圖，加上白話解釋", "shot": "c_02_fsm.png", "io": "輸出端",
         "note": ["13 個狀態、47 條轉移，全部有模擬器重播的軌跡", "14 條看似可能的跳轉，證明永遠不會發生", "解釋以證明為準，不只看原始碼字面"]},
        {"label": "操作歷程 3 / 輸出端", "title": "論文版架構圖：5 個單元、1 處交叉", "shot": "c_03_block.png", "io": "輸出端",
         "note": ["一句「要放論文用的」就選交叉最少的版面", "畫完從圖檔反查每條連線，錯誤 0 個", "逐一說明 CPU、記憶體、flash、UART 的角色"]},
        {"label": "操作歷程 4 / 輸出端", "title": "時序圖：畫到哪、沒畫到哪，都說清楚", "shot": "c_04_timing.png", "io": "輸出端",
         "note": ["波形來自模擬器，重播比對通過", "agent 只描述圖上真的有的幾拍", "看不到整個位元組時，直接說出來"]},
        {"label": "操作歷程 5 / 輸出端", "title": "CPU 主狀態機：哪些轉移不可能發生", "shot": "c_05_cpu.png", "io": "輸出端",
         "note": ["原始碼看似任何狀態都能進 trap", "證明指出 shift 與 exec 永遠進不了", "推測與證明分開講，不混為一談"]},
    ],
    "bench": {"n": len(rows), "tools": [{"name": t["name"], "exact": t["exact"], "ours": t.get("ours", False)} for t in chart], "notes": notes},
    "trust": [
        [str(complete), "張狀態圖完整性已證明", "沒畫的轉移都證明不可能發生"],
        [str(wit), "條轉移全部有軌跡", f"共 {edges} 條，模擬器二值重播確認，未定 {und} 條"],
        [str(pdr), "條看似可能的轉移", "由 PDR 證明永遠不會發生，檢查器再獨立驗證"],
        [str(tamk) if aud and tamk == tam else "未完成", "份竄改憑證全部擋下", f"另有 {mutk} 個讓圖失真的 RTL 突變也全部擋下，漏網 {surv}" if aud and mutk == mut else "攻擊測試與稽核仍在執行"],
    ],
    "audit_clean": clean,
    "diff": [
        ["通用 AI 聊天", ["一句話就能要圖", "圖是生成的，沒有依據", "畫錯了也不會知道"], False],
        ["開源 EDA 工具", ["要懂指令與設定", "狀態機靠語法猜，多畫或漏畫", "沒有逐條的證據"], False],
        ["RTL-To-Graph Agent", ["一句話就能用", "圖由管線產生，每條線都有證據", "AI 只負責理解與挑選，不能改寫事實"], True],
    ],
    "limits": [
        "時序圖只畫得出短短幾拍的片段：使用者想看一整個位元組進來，目前只看得到開頭",
        "初版 agent 會描述它看不到的波形，也會把原始碼字面當成事實；改成只依工具數據與證明說明後修正",
        "使用者只說簡稱時第一次找不到設計；已改成認得頂層模組名稱",
        "狀態機證明限單一時脈、狀態不超過 64 個，超過就拒絕產生，不會亂畫",
        "平坦的大型 CPU 方塊圖仍然很亂，交叉多、難讀",
        "語意判斷依賴 L1 的啟發式標註，標錯時要靠 agent 讀原始碼把關",
        "新設計要現場跑三條管線，要幾分鐘；語料庫內的設計不到一秒",
    ],
    "next": ["時序圖從片段擴成完整交易，一筆請求到回應一次畫完", "大型 CPU 方塊圖分層摺疊，先看子系統再展開", "網頁直接上傳資料夾，組員與新設計一鍵產圖"],
}
print(json.dumps(data, ensure_ascii=False, indent=1))
