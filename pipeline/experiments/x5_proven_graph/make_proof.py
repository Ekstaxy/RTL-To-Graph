"""可證明狀態機圖的成果頁：python make_proof.py OUT GALLERY_DIR

只讀 audit.py 寫出的 OUT/audit.json 與各憑證。頁面上每一個「通過」都來自稽核：
稽核確認那份結果是針對目前這份憑證、由目前這版程式做出來的，才算數。沒有稽核檔就不產生頁面。
輸出 GALLERY_DIR/proof.html 與 proof/ 下的圖。"""
import html
import json
import shutil
import sys
from pathlib import Path

OUT, GAL = Path(sys.argv[1]), Path(sys.argv[2])
esc = html.escape
if not (OUT / "audit.json").exists():
    sys.exit("no audit.json: run audit.py first; the page only shows what the audit confirmed")
AUD = json.loads((OUT / "audit.json").read_text())
(GAL / "proof").mkdir(parents=True, exist_ok=True)

ITEM = {"prover version": "由定版證明器產生", "same design in both tools": "模型與模擬器是同一個設計", "reset protocol": "reset 協定經明確決定",
        "certificate consistent": "憑證自身一致",
        "witnesses replayed": "軌跡在模擬器重播", "completeness, second engine": "第二引擎重證完整性", "state names": "狀態名稱證明",
        "guard labels": "條件標籤證明", "drawing matches certificate": "圖檔反查", "attack": "攻擊"}
WORD = {"pass": "通過", "FAIL": "未通過", "NOT RUN": "未跑", "n/a": "不適用"}
GREEN, AMBER, RED, GREY, BLUE = "#047857", "#b45309", "#b91c1c", "#6b7280", "#1d4ed8"
ORIGIN = {"simulation": "隨機模擬", "bmc": "從 reset 的有界模型檢查", "bmc continued from a trace": "沿既有軌跡延伸的模型檢查", "snapshot relay": "快照接力"}


def chip(t, c):
    return f'<span class="g" style="background:{c}">{esc(t)}</span>'


cards, table = [], []
REJ = {}
REJ_WORD = {"form": "格式不合", "witnesses:trace outside the assumptions": "軌跡不符假設", "witnesses:edge not reproduced": "宣稱的邊重播不出來",
            "witnesses:a replayed trace takes an unlisted edge": "重播的軌跡走了沒列出的邊", "completeness:base case fails": "第二引擎找到反例",
            "completeness:not inductive within maxsteps": "第二引擎證不出完整", "completeness:counterexample replayed in the simulator": "反例在模擬器重播成立"}
T = dict(n=0, proven=0, exact=0, wit=0, und=0, model=0, edges=0, pu=0, l1lab=0, l1exact=0, derived=0, derived_exact=0, names=0, names_ok=0,
         new=0, l1extra=0, l1miss=0, tam=0, tamk=0, mut=0, mutk=0, mutrep=0, same=0, cons=0, surv=0, err=0, sup=0, relay=0, all_ok=0,
         pdr=0, pdr_certs=0, inv=0, two=0)
for r in AUD["rows"]:
    d = Path(r["dir"]) if Path(r["dir"]).exists() else OUT / r["design"] / r["id"].replace("/", "_")
    cert = json.loads((d / "cert.json").read_text())
    it = r["items"]
    comp, e = cert["completeness"], cert["edges"]
    T["n"] += 1
    T["edges"] += r["edges"]
    T["wit"] += r["witnessed"]
    T["und"] += r["undetermined"]
    T["model"] += r["model_witness"]
    T["pu"] += r["needs_power_up"]
    proven = comp["status"] == "proven"
    T["proven"] += proven
    T["exact"] += proven and r["undetermined"] == 0 and r["model_witness"] == 0
    T["new"] += r.get("source") != "l1"
    bad = [k for k, v in it.items() if v["status"] == "FAIL"]
    notrun = [k for k, v in it.items() if v["status"] == "NOT RUN"]
    T["all_ok"] += not bad and not notrun
    c1 = chip("完整性已證明", GREEN) if proven else chip("被模擬推翻" if comp["status"] == "refuted" else f"只證到 {comp['depth']} 拍", RED if comp["status"] == "refuted" else AMBER)
    gap = r["undetermined"] + r["model_witness"]
    c2 = chip("每條邊都有實際軌跡", GREEN) if gap == 0 else chip(f"{gap} 條邊未定", AMBER)
    c3 = (chip(f"{len(bad)} 項驗證未通過", RED) if bad else chip(f"{len(notrun)} 項驗證未跑", GREY) if notrun else chip("驗證全部通過", GREEN))
    svg = ""
    if (d / "graph.svg").exists():
        name = f"{r['design']}__{r['id'].replace('/', '_').replace('@', '_at_')}.svg"
        shutil.copyfile(d / "graph.svg", GAL / "proof" / name)
        svg = f'<figure><img loading="lazy" src="proof/{esc(name)}" alt="{esc(r["id"])} 的已證明狀態圖"></figure>'
    A = cert["assumptions"]
    rst = "、".join(f"{x['port']} {'低' if x['active_low'] else '高'}態有效" for x in A["reset"]) or "無 reset，從 RTL 初值出發"
    org = {}
    for x in e:
        if x["status"] == "witnessed":
            o = ORIGIN.get(cert["traces"][x["trace"]].get("origin", ""), "其他")
            org[o] = org.get(o, 0) + 1
    facts = [f"觀測訊號：<code>{esc(' , '.join(o['signal'] for o in cert['observation']))}</code>，證明範圍是模組 <code>{esc(cert['scope']['module'])}</code>"
             + ("，帶入上層給的參數" if cert["scope"]["instance"] else "") + "。",
             f"假設：時脈 {esc(A['clock']['port'])}；reset {esc(rst)}，保持 {A['reset_cycles']} 拍後放開、之後不再拉起；輸入不設限；未知值可為任意值；"
             f"以合成組態解讀 RTL，檔案順序為{'清單順序' if A.get('source_order') == 'as listed' else '頂層檔案優先'}。",
             f"{len(cert['states'])} 個狀態、{r['edges']} 條轉移含自環：{r['witnessed']} 條有 iverilog 重播確認的軌跡"
             + (f"，{r['undetermined']} 條未定" if r["undetermined"] else "") + (f"，{r['model_witness']} 條模型有軌跡但模擬器未重現" if r["model_witness"] else "")
             + "。軌跡來源：" + "、".join(f"{k} {v} 條" for k, v in sorted(org.items(), key=lambda z: -z[1])) + "。"]
    if r["needs_power_up"]:
        facts.append(f"其中 {r['needs_power_up']} 條需要特定的上電值才會發生，例如未初始化的暫存器堆內容。上電值寫在軌跡裡，模擬器只在 RTL 沒給初值的位元上放入。")
    if str(it.get("witnesses replayed", {}).get("detail", "")).find("two-valued") >= 0:
        T["two"] += 1
        facts.append("重播是二值的：RTL 沒給初值的暫存器與記憶體，上電時一律給定值（軌跡指定的值，否則 0）；RTL 裡寫的 x 當成 0；每一拍檢查沒有任何暫存器出現 x。"
                     "所以每條軌跡都是硬體在某個合法上電狀態下的真實執行，不依賴模擬器自己的 x 運算規則。")
    rl = comp.get("relay")
    if rl and rl.get("found"):
        T["relay"] += rl.get("pairs", 0)
        facts.append(f"快照接力：把模擬器跑到的 {rl['snapshots']} 個真實狀態交給求解器往後找，補到 {rl['pairs']} 條轉移的軌跡，每條都只用輸入從 reset 重播確認"
                     + (f"；另有 {rl['rejected']} 個提議重播不出來，沒有採用" if rl.get("rejected") else "") + "。")
    sup = comp.get("support")
    if sup:
        T["sup"] += 1
        extra = " , ".join(o["signal"] for o in sup["observation"][len(cert["observation"]):])
        facts.append(f"證明時把 <code>{esc(extra)}</code> 一起觀測，先在 {sup['states']} 個組合狀態、{len(sup['pairs'])} 條轉移上證明完整，再投影回這張圖。"
                     "只看單一訊號排除不掉的轉移，要靠組合才能排除。獨立檢查器重證的是這組較細的轉移，投影由它自己重算。")
    if proven:
        facts.append("沒畫出來的轉移都已證明不可能發生，方法是" + ("從任意狀態求一步後繼的閉包" if comp["k"] == 0 else f"{comp['k']} 步歸納")
                     + (f"；另有 {comp['tightened']['removed']} 條靠 {comp['tightened']['k']} 步歸納證明到不了" if comp.get("tightened", {}).get("removed") else "") + "。")
    inv = comp.get("invariant")
    if inv:
        T["pdr"] += len(inv.get("removed_edges", []))
        T["pdr_certs"] += 1
        T["inv"] += len(inv.get("blocked", []))
        facts.append(f"<b>另有 {len(inv.get('removed_edges', []))} 條轉移</b>在一步之內看似可能，但從 reset 出發永遠不會發生："
                     + esc("、".join(f"{a}→{b}" for a, b in inv.get("removed_edges", [])[:16])) + "。"
                     f"證明由 PDR（ABC 的 IC3）找出歸納不變量，共 {len(inv.get('blocked', []))} 個子句，寫在憑證裡；"
                     "獨立檢查器不信任它，自己用 Yosys 的 SAT 引擎把不變量和整個邊集一起做歸納證明。")
    if cert.get("note"):
        facts.append("提議者說明：" + esc(cert["note"]))
    lc = cert.get("l1_compare")
    if lc:
        if lc["l1_only"]:
            T["l1extra"] += len(lc["l1_only"])
            facts.append(f"<b>現有工具的圖多畫了 {len(lc['l1_only'])} 條轉移</b>，已證明從 reset 出發永遠不會發生：" + esc("、".join(f"{a}→{b}" for a, b in lc["l1_only"][:10])) + "。")
        else:
            facts.append("現有工具畫的非自環轉移都在已證明的圖裡。")
        if lc["proof_only"]:
            T["l1miss"] += len(lc["proof_only"])
            facts.append(f"<b>現有工具的圖少了 {len(lc['proof_only'])} 條實際會發生的轉移</b>，每條都有重播確認的軌跡：" + esc("、".join(f"{a}→{b}" for a, b in lc["proof_only"][:10])) + "。")
    if it["guard labels"]["status"] == "pass" and r.get("l1_labels") is not None:
        ll, dl = r["l1_labels"], r.get("derived_labels", {})
        n, ex = sum(ll.values()), ll.get("exact", 0)
        T["l1lab"] += n
        T["l1exact"] += ex
        T["derived"] += sum(dl.values())
        T["derived_exact"] += dl.get("exact", 0)
        facts.append(f"條件標籤：現有圖上 {n} 個，逐一證明後 <b>{ex} 個精確</b>、{ll.get('sufficient', 0)} 個只是充分條件、{ll.get('unproven', 0)} 個有反例"
                     + (f"、{ll.get('not compiled', 0)} 個無法編譯" if ll.get("not compiled") else "") + f"。改由真值表導出後，{sum(dl.values())} 條邊中 {dl.get('exact', 0)} 條的條件證明精確。")
    if it["state names"]["status"] == "pass" and r.get("names_proposed"):
        T["names"] += r["names_proposed"]
        T["names_ok"] += r["names_verified"]
        facts.append(f"狀態名稱：提議 {r['names_proposed']} 個，{r['names_verified']} 個證明與 RTL 常數相等後才採用，其餘只顯示數值。")
    at = r.get("attack") if it["attack"]["status"] in ("pass", "FAIL") else None
    if at:
        for k, v in (r.get("attack_rejected_by") or {}).items():
            if k.startswith("tamper"):
                label = REJ_WORD.get(k.split(": ", 1)[1].split(":")[0] + (":" + k.split(": ")[2] if k.count(": ") >= 2 else ""), k.split(": ", 1)[1])
                REJ[label] = REJ.get(label, 0) + v
        tk, ts = at.get("tamper:killed", 0), at.get("tamper:SURVIVOR", 0)
        mk, ms = at.get("mutant:killed", 0), at.get("mutant:SURVIVOR", 0)
        mr = at.get("mutant:trace no longer reproduces, rejected", 0)
        T["tam"] += tk + ts
        T["tamk"] += tk
        T["mut"] += mk + ms
        T["mutk"] += mk
        T["mutrep"] += mr
        T["surv"] += ts + ms
        T["cons"] += at.get("mutant:rejected, not shown false", 0)
        T["same"] += at.get("mutant:same graph, accepted", 0)
        facts.append(f"攻擊，每類 {r.get('attack_cases_per_kind')} 例：竄改憑證 {tk + ts} 份擋下 {tk} 份；讓狀態圖失真的 RTL 突變 {mk + ms} 個擋下 {mk} 個；"
                     f"圖不變但軌跡不再成立的突變 {mr} 個，被軌跡重播擋下；不改變狀態圖的突變 {at.get('mutant:same graph, accepted', 0)} 個照常通過"
                     + (f"；{at.get('mutant:rejected, not shown false', 0)} 個被拒絕但無法判定是否失真，屬保守拒絕" if at.get("mutant:rejected, not shown false") else "")
                     + "。" + (f"<b>漏網 {ts + ms} 個。</b>" if ts + ms else ""))
    audit_li = "".join(f'<li><span class="st st-{v["status"].replace(" ", "")}">{WORD[v["status"]]}</span> {esc(ITEM.get(k, k))}'
                       f'{"：<small>" + esc(str(v.get("detail") or "")[:220]) + "</small>" if v.get("detail") else ""}</li>' for k, v in it.items())
    src = chip("現有工具已找到", GREY) if r.get("source") == "l1" else chip("新提議，現有工具沒抓到", BLUE)
    anchor = esc(r["design"] + "-" + r["id"])
    cards.append(f'<article class="card" id="{anchor}"><header><h3>{esc(r["id"])}</h3><span class="proj">{esc(r["design"])}</span>{src}{c1}{c2}{c3}</header>'
                 f'<section>{svg}<ul>{"".join("<li>" + f + "</li>" for f in facts)}</ul>'
                 f'<details><summary>驗證稽核，憑證雜湊 <code>{esc(r["cert_sha"])}</code></summary><ul class="audit">{audit_li}</ul></details></section></article>')
    table.append(f'<tr><td><a href="#{anchor}">{esc(r["id"])}</a><br><small>{esc(r["design"])}</small></td><td>{c1}</td>'
                 f'<td>{len(cert["states"])} 個狀態<br><small>{r["edges"]} 條轉移</small></td><td>{c2}</td><td>{c3}</td><td><small>證明 {r["seconds"]} 秒<br>重證 {r.get("check_seconds", "-")} 秒</small></td></tr>')
for m in AUD["without_certificate"]:
    table.append(f'<tr><td>{esc(m["id"])}<br><small>{esc(m["design"])}</small></td><td colspan="5">{chip("拒絕產生" if m["status"] == "refused" else "執行錯誤", GREY if m["status"] == "refused" else RED)}'
                 f' <small>{esc(str(m.get("reason") or ""))[:200]}</small></td></tr>')

tot = AUD["totals"]
audit_rows = "".join(f'<tr><td>{esc(ITEM.get(k, k))}</td><td>{v["pass"]}</td><td>{v["FAIL"]}</td><td>{v["NOT RUN"]}</td><td>{v["n/a"]}</td></tr>' for k, v in tot.items())
clean = AUD["clean"]
verdict = (f'<p class="verdict ok">稽核結論：{T["n"]} 張圖、{len(tot)} 項驗證，全部跑完而且全部通過。每一項結果都綁定目前的憑證雜湊與程式版本。</p>' if clean else
           f'<p class="verdict no">稽核結論：尚未全部完成。{T["n"] - T["all_ok"]} 張圖有驗證未通過或未跑，'
           f'{sum(v["FAIL"] for v in tot.values())} 項未通過、{sum(v["NOT RUN"] for v in tot.values())} 項未跑'
           + (f"、{len(AUD['without_certificate'])} 個候選沒有憑證" if AUD["without_certificate"] else "") + '。下方每張卡片列出是哪一項。</p>')

# ---- open-source extractors against the proven graphs (bench_fsm.py), only rows of audited certificates
BENCH = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 and Path(sys.argv[3]).exists() else None
bench_html = ""
if BENCH:
    shas = {r["id"]: r["cert_sha"] for r in AUD["rows"]}
    V = BENCH.get("versions", {})
    TN = {"yosys": f"Yosys {V.get('yosys') or ''} FSM 流程", "yosys_new": f"Yosys {V.get('yosys_new') or ''} FSM 流程",
          "verilator": f"Verilator {V.get('verilator') or ''} --coverage-fsm", "teroshdl": f"TerosHDL {V.get('teroshdl') or ''}",
          "pyverilog": f"Pyverilog {V.get('pyverilog') or ''}", "x4": "x4，本專案舊版抽取器"}
    rows_b = [r for r in BENCH["rows"] if not r.get("skip") and shas.get(r["id"]) == r.get("cert_sha")]
    stale = [r["id"] for r in BENCH["rows"] if not r.get("skip") and shas.get(r["id"]) != r.get("cert_sha")]
    tools = [t for t in BENCH["tools"] if any(t in r["tools"] and r["tools"][t].get("status") != "not installed" for r in rows_b)]
    tools += ["x4"] if any("x4" in r["tools"] for r in rows_b) else []
    agg = {t: dict(exact=0, extra=0, missed=0, nodet=0, err=0, found=0, unreach=0) for t in tools}
    body = []
    for r in rows_b:
        cells = []
        for t in tools:
            v = r["tools"].get(t)
            a = agg[t]
            if v is None:
                cells.append("<td>-</td>")
                continue
            st = v.get("status")
            if st == "found":
                a["found"] += 1
                a["extra"] += v.get("extra", 0)
                a["missed"] += v.get("missed", 0)
                a["unreach"] += len(v.get("unreachable_states", []) or [])
                ok = not v.get("extra") and not v.get("missed")
                a["exact"] += ok
                tip = esc("多畫：" + "、".join(f"{x}→{y}" for x, y in (v.get("extra_edges") or [])[:12]) + "；漏畫：" + "、".join(f"{x}→{y}" for x, y in (v.get("missed_edges") or [])[:12]))
                word = "完全正確" if ok else "多 %d / 漏 %d" % (v.get("extra", 0), v.get("missed", 0))
                cells.append(f'<td class="{"bk-ok" if ok else "bk-bad"}" title="{tip}">{word}</td>')
            elif st == "not detected":
                a["nodet"] += 1
                cells.append('<td class="bk-none">沒抓到</td>')
            else:
                a["err"] += 1
                cells.append(f'<td class="bk-err" title="{esc(str(v.get("why") or ""))}">工具出錯</td>')
        body.append(f'<tr><td><a href="#{esc(r["design"] + "-" + r["id"])}">{esc(r["id"])}</a><br><small>非自環轉移 {r["real_edges_no_self"]} 條</small></td>{"".join(cells)}'
                    '<td class="bk-ok">完全正確</td></tr>')
    n = len(rows_b)
    foot = "".join(f'<td><b>{agg[t]["exact"]} / {n}</b> 張完全正確<br><small>多畫 {agg[t]["extra"]} 條、漏畫 {agg[t]["missed"]} 條'
                   f'{"、到不了的狀態 " + str(agg[t]["unreach"]) + " 個" if agg[t]["unreach"] else ""}<br>沒抓到 {agg[t]["nodet"]} 張、出錯 {agg[t]["err"]} 張</small></td>' for t in tools)
    oss = [t for t in tools if t != "x4"]  # x4 is this project's own earlier extractor, not an open-source tool
    best = max(oss, key=lambda t: (agg[t]["exact"], -agg[t]["extra"] - agg[t]["missed"])) if oss else None
    bench_html = (f'<h2>和開源工具正面比較</h2><p>{n} 張單一狀態暫存器的圖，同一份 RTL 交給目前能從命令列執行的開源 FSM 抽取工具，各照自己的使用說明跑。'
                  "標準答案是這裡已證明的圖：沒畫的轉移都證明不可能發生，所以工具多畫的每一條都是錯的；有軌跡的轉移都真的會發生，所以工具少畫的每一條也是錯的。"
                  "比的是非自環轉移，因為各工具畫自環的習慣不同；工具因為 reset 可以再拉起而畫的「回到 reset 狀態」不算錯。滑鼠停在格子上可看到是哪幾條。</p>"
                  f'<table class="bench"><thead><tr><th>狀態機</th>{"".join(f"<th>{esc(TN.get(t, t))}</th>" for t in tools)}<th>x5，本頁</th></tr></thead>'
                  f'<tbody>{"".join(body)}</tbody><tfoot><tr><td><b>合計</b></td>{foot}<td><b>{n} / {n}</b> 張完全正確<br><small>每個元素都有證據</small></td></tr></tfoot></table>'
                  + (f"<p>表現最好的開源工具是 {esc(TN.get(best, best))}：{agg[best]['exact']} / {n} 張完全正確。</p>" if best else "")
                  + (f"<p><small>以下圖的對照結果不是針對目前的憑證，沒有列入：{esc('、'.join(stale))}</small></p>" if stale else ""))

CSS = """
:root{--bg:#f3f4f6;--card:#fff;--ink:#14171c;--mute:#5b6370;--line:#d9dde3}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.75 "Microsoft JhengHei","Noto Sans TC","PingFang TC",system-ui,sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:0 24px}
header.hero{background:#0b0d10;color:#fff;padding:52px 0 40px}.hero h1{font-size:42px;line-height:1.25;margin:0 0 12px}
.hero p{font-size:20px;color:#b6bcc6;margin:0 0 20px;max-width:58em}.hero a{color:#fff}
.chips{display:flex;flex-wrap:wrap;gap:10px}.chip{border:1px solid #3a4049;border-radius:999px;padding:6px 16px;font-size:16px;color:#e6e8eb}.chip b{font-size:20px;margin-right:6px;color:#fff}
.verdict{font-size:20px;font-weight:700;border-radius:12px;padding:14px 20px;margin:22px 0 0}.verdict.ok{background:#064e3b;color:#d1fae5}.verdict.no{background:#7c2d12;color:#ffedd5}
h2{font-size:30px;margin:36px 0 16px}
.three{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.two{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}
.box{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px 24px}.box h3{margin:0 0 10px;font-size:22px}
.box ul{margin:8px 0 0;padding-left:1.2em}.box li{margin:.35em 0}.box p{margin:.4em 0}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}
th,td{text-align:left;padding:10px 16px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:16px;color:var(--mute);background:#fafafb}
td small{color:var(--mute);font-size:16px}td a{color:var(--ink);font-weight:700}
.g{display:inline-block;color:#fff;border-radius:999px;padding:1px 12px;font-size:16px;white-space:nowrap}
article.card{background:var(--card);border:1px solid var(--line);border-radius:16px;margin:24px 0;overflow:hidden}
.card>header{display:flex;flex-wrap:wrap;gap:8px 10px;align-items:center;padding:16px 24px;border-bottom:1px solid var(--line);background:#fafafb}
.card h3{font-size:24px;margin:0 8px 0 0}.proj{color:var(--mute);font-size:16px;margin-right:auto}
.card section{padding:18px 24px}.card ul{margin:10px 0 0;padding-left:1.2em}.card li{margin:.3em 0}
details{margin-top:12px}summary{cursor:pointer;color:var(--mute);font-size:16px}ul.audit{list-style:none;padding-left:0}ul.audit small{color:var(--mute);font-size:15px}
.st{display:inline-block;min-width:4.2em;text-align:center;border-radius:6px;color:#fff;font-size:15px;padding:0 6px;margin-right:6px}
.st-pass{background:#047857}.st-FAIL{background:#b91c1c}.st-NOTRUN{background:#6b7280}.st-n\\/a{background:#9ca3af}
figure{margin:0 0 8px}figure img{display:block;max-width:100%;max-height:560px;margin:0 auto;background:#fff;border:1px solid var(--line);border-radius:8px;cursor:zoom-in}
code{font-size:15px;background:#eef0f3;border-radius:4px;padding:1px 5px}
table.bench td{font-size:16px;text-align:center}table.bench td:first-child{text-align:left}
.bk-ok{background:#ecfdf5;color:#065f46;font-weight:700}.bk-bad{background:#fef2f2;color:#991b1b;font-weight:700}.bk-none{background:#f3f4f6;color:#6b7280}.bk-err{background:#fff7ed;color:#9a3412}
.legend{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:16px;color:var(--mute);margin:10px 0 0}
footer{padding:30px 0 60px;color:var(--mute);font-size:16px}footer a{color:var(--ink)}
#lb{position:fixed;inset:0;background:rgba(10,12,15,.92);display:none;align-items:center;justify-content:center;z-index:20;cursor:zoom-out;padding:24px}
#lb.on{display:flex}#lb img{max-width:100%;max-height:100%;background:#fff;border-radius:6px}
@media (max-width:1000px){.three,.two{grid-template-columns:1fr}}
"""
JS = """
const lb=document.getElementById('lb'),lbi=lb.querySelector('img');
document.querySelectorAll('figure img').forEach(i=>i.addEventListener('click',()=>{lbi.src=i.src;lbi.alt=i.alt;lb.classList.add('on');}));
lb.addEventListener('click',()=>lb.classList.remove('on'));
document.addEventListener('keydown',e=>{if(e.key==='Escape')lb.classList.remove('on');});
"""
code = ", ".join(f"{k} {v}" for k, v in AUD["code"].items())
page = f'''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RTL-To-Graph 可證明的狀態圖</title><style>{CSS}</style></head><body>
<header class="hero"><div class="wrap"><h1>先求一定正確：每條邊都帶著證據的狀態圖</h1>
<p>圖不是抽出來再檢查，而是由證明引擎直接算出來。畫出的每條轉移都有一段可在模擬器重播的實際軌跡；沒畫的轉移都有不可能發生的證明；證不出來的明白標成未定。要觀測哪些訊號、狀態叫什麼、條件怎麼寫，可以交給啟發式或 LLM 提議，由檢查器裁決。回到 <a href="all.html">完整成果頁</a>。</p>
<div class="chips"><span class="chip"><b>{T["n"]}</b>張狀態圖</span><span class="chip"><b>{T["proven"]}</b>張完整性已證明</span><span class="chip"><b>{T["exact"]}</b>張每條邊都有軌跡</span>
<span class="chip"><b>{T["wit"]}</b>條轉移有重播確認的軌跡，{T["und"]} 條未定，{T["model"]} 條兩工具不一致</span><span class="chip"><b>{T["all_ok"]}</b>張全部驗證通過</span></div>
{verdict}</div></header>
<main class="wrap">
<h2>一張圖宣稱什麼，憑什麼</h2>
<div class="three">
<div class="box"><h3>畫出來的邊：會發生</h3><p>證據是一段從 reset 開始的輸入序列。Icarus Verilog 照著跑，必須在指定的那一拍看到這個轉移。Yosys 建的模型和 iverilog 是兩套獨立的前端；兩邊讀同樣的檔案順序與巨集，而且模型裡每個暫存器都必須在模擬器裡找得到，才算同一個設計。</p></div>
<div class="box"><h3>沒畫的邊：不可能發生</h3><p>證據是不可滿足的證明。從任意狀態出發求一步後繼並取閉包，真實狀態必然是其中之一，所以不論跑多久都不會漏。z3 和 Yosys 內建的 MiniSat 用兩種編碼各證一次，檢查器不匯入 z3。</p></div>
<div class="box"><h3>看似可能：交給 PDR，證不出來才標未定</h3><p>一步之內可能、但找不到軌跡的轉移，交給 PDR（ABC 的 IC3）證明從 reset 出發到不了。PDR 找到的歸納不變量寫進憑證，檢查器再用 Yosys 的 SAT 引擎獨立驗證，不信任 ABC。連 PDR 都證不了的才用虛線畫成未定，不當成事實。超出模型能精確處理的設計直接拒絕產生，例如鎖存器、多個時脈、超過狀態上限。</p></div>
</div>
<div class="legend"><span>實線黑色：有軌跡的轉移</span><span>灰色虛線帶問號：未定</span><span>橘色虛線：模型與模擬器不一致</span><span>黑點箭頭：reset 放開後的起始狀態</span><span>自環未畫出，數量寫在各圖說明</span></div>
<h2>驗證稽核</h2>
<p>每張圖做 {len(tot)} 項驗證。稽核程式只讀結果檔，確認它是針對目前這份憑證、由目前這版程式做出來的才計入；舊結果、對不上雜湊的結果一律算未跑。</p>
<table><thead><tr><th>驗證項目</th><th>通過</th><th>未通過</th><th>未跑</th><th>不適用</th></tr></thead><tbody>{audit_rows}</tbody></table>
<h2>這一輪發現的事</h2>
<div class="two">
<div class="box"><h3>對現有圖的檢驗</h3><ul>
<li>現有圖上的條件標籤共 {T["l1lab"]} 個，逐一證明後 <b>{T["l1exact"]} 個精確成立</b>。常見的錯是漏了優先權：後面的 <code>if</code> 會蓋掉前面的。</li>
<li>改用真值表導出後，{T["derived"]} 條邊中 <b>{T["derived_exact"]} 條的條件證明精確</b>。</li>
<li>現有圖多畫了 <b>{T["l1extra"]} 條</b>從 reset 出發永遠不會發生的轉移，也少畫了 <b>{T["l1miss"]} 條</b>實際會發生的轉移。</li>
<li>一步之內看似可能、靠 PDR 證明永遠不會發生的轉移 <b>{T["pdr"]} 條</b>，分布在 {T["pdr_certs"]} 張圖；不變量合計 {T["inv"]} 個子句，全部由檢查器獨立重證。</li>
<li>狀態名稱 {T["names"]} 個提議中 {T["names_ok"]} 個通過「與 RTL 常數相等」的證明。</li></ul></div>
<div class="box"><h3>對方法本身的攻擊</h3><ul>
<li>竄改憑證 {T["tam"]} 份：刪掉真的邊、刪邊並拿掉經過它的所有軌跡、加上假的邊、改指向、把未定升格、軌跡裡再拉一次 reset、軌跡少一個輸入、把不變量改成假的。獨立檢查器擋下 <b>{T["tamk"]} 份</b>，每一份都有明確判定：{esc("、".join(f"{k} {v}" for k, v in sorted(REJ.items(), key=lambda z: -z[1])))}。</li>
<li>在 RTL 注入單點錯誤後，先證明突變體自己的圖，再拿原憑證去檢查。讓狀態圖失真的 {T["mut"]} 個擋下 <b>{T["mutk"]} 個</b>；圖不變但原軌跡不再成立的 {T["mutrep"]} 個也被軌跡重播擋下。不改變狀態圖的 {T["same"]} 個照常通過，這是對的。保守拒絕 {T["cons"]} 個。</li>
<li>漏網數：<b>{T["surv"]}</b>。</li>
<li>新提議而現有工具沒抓到的狀態機 {T["new"]} 張，同樣走完整套證明。</li></ul></div>
</div>
{bench_html}
<h2>總表</h2>
<table><thead><tr><th>狀態機</th><th>完整性</th><th>規模</th><th>軌跡</th><th>驗證</th><th>耗時</th></tr></thead><tbody>{"".join(table)}</tbody></table>
<h2>逐一檢視</h2>
{"".join(cards)}
</main>
<footer><div class="wrap">信任基礎：完整性依賴 Yosys 對 RTL 的解讀，加上兩套 SAT 求解器結論一致；軌跡依賴 Icarus Verilog。L1 使用的 slang 完全沒參與，所以這也是對 L1 的獨立檢驗。<br>
未知值：模擬一律是二值的。RTL 沒給初值的暫存器與記憶體在上電時給定值，RTL 寫的 x 當成 0，每一拍檢查沒有暫存器是 x，所以軌跡不依賴模擬器自己的 x 規則。剩下的信任前提是模擬器本身正確，以及 Yosys 刪掉的暫存器不影響觀測；後者由「模型裡每個暫存器都在模擬器找得到」和檢查器自己列出的暫存器清單把關。<br>
被拒絕的假憑證：歸納證不出來時，檢查器另外用 ABC 找反例，反例的輸入與上電值交給模擬器重播，重播出沒列出的轉移才算「反例在模擬器重播成立」。<br>
每張圖的假設寫在卡片上。以模組為範圍的證明，在任何以相同參數例化它的設計裡都成立，但軌跡是該模組單獨執行的軌跡。<br>
尚未涵蓋：多時脈、鎖存器、Yosys 讀不了的 SystemVerilog 語法、註解形式的合成指示，以及 reset 極性是否符合設計者本意。時序圖與架構圖還沒有搬到這套做法上。<br>
程式版本：<code>{esc(code)}</code>。工具：Yosys 0.33、z3 5.4.1、Icarus Verilog 12.0、Graphviz。產生於 2026 年 11 月 17 日。</div></footer>
<div id="lb" role="dialog" aria-label="放大檢視"><img alt=""></div><script>{JS}</script></body></html>'''
(GAL / "proof.html").write_text(page, encoding="utf-8")
print("wrote proof.html", len(page), "clean" if clean else "NOT CLEAN", T)
