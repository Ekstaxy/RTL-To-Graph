"""The RTL-To-Graph agent: Claude reads the request, looks at the design, and calls the project's
own diagram pipelines (backbone.py). It decides what to draw and which signals matter; the
pipelines draw, and their checks decide what is true.

    python agent.py "畫出 picosoc 的架構圖，論文用的版本"        # one request in the terminal
    python server.py                                          # the web demo

The API key is read from .env next to this file (ANTHROPIC_API_KEY=...), or from the environment.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

import anthropic

import backbone as B

HERE = Path(__file__).resolve().parent
CFG = B.CFG
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1"}


def load_key():
    env = HERE / ".env"
    if env.exists():
        for ln in env.read_text(encoding="utf-8").splitlines():
            k, _, v = ln.partition("=")
            if k.strip() == "ANTHROPIC_API_KEY" and v.strip() and not v.strip().startswith("<"):
                os.environ["ANTHROPIC_API_KEY"] = v.strip().strip('"')
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


SYSTEM = """你是 RTL-To-Graph 的硬體圖表助理。使用者用一句話描述想看什麼，你負責讀懂設計、挑出該看的訊號，再呼叫專案自己的畫圖工具產生三種圖：
架構圖（方塊圖）、狀態機圖、時序圖。圖由工具畫，工具的檢查決定什麼是真的；你決定畫什麼、看哪些訊號，並用一般人聽得懂的話解釋。

做事的順序：
1. 先確定是哪個設計。不確定就呼叫 list_designs。使用者自己的資料夾寫成 design = "dir:/絕對路徑#頂層模組"。
2. 呼叫 analyze_design 看 L1 的語意標註：時脈、reset 與極性、握手介面與每個訊號的角色、狀態暫存器候選。
   這些是啟發式判斷。要用到某個訊號的意義（哪個是狀態暫存器、reset 是高態還是低態有效、哪組 valid/ready 是使用者問的那條通道），
   先用 read_source（可用 grep 找訊號出現的行）確認，再下結論。
3. 依需求畫圖：
   - 架構圖 draw_block：要放論文、簡報、海報，或使用者沒特別說，用 view="paper"（交叉最少的版面）；要看整體系統階層用 "system"；要比較各種版面用 "all"。
   - 狀態機 draw_fsm：signal 填狀態暫存器名稱。狀態機在子模組裡時，scope 填從頂層到該實例的路徑，例如 ["cpu"]。
     確定 reset 埠與極性時才填 reset / active_low。計數器類的訊號可以用 aux 帶上驅動它的狀態暫存器，讓證明排除到不了的值。
   - 時序圖 draw_timing：interface 填使用者關心的通道名稱或訊號名；不確定就先不填，看回傳的 available 清單再挑。
4. 一個請求可以畫多張圖；使用者要三種圖就三種都畫。

回答的規矩：
- 用繁體中文，對一般大眾說明：這張圖在畫什麼、重要的訊號各代表什麼、從圖上能看出設計怎麼運作。
- 只講工具結果支持的事。狀態圖的每條實線都有模擬器重播過的實際軌跡，沒畫的轉移都證明不可能發生，未定的要明說；時序圖說明檢查有沒有通過。
- 說明狀態怎麼轉移時，以 draw_fsm 回傳的 transitions 為準，不要只憑原始碼字面推論。原始碼看起來任何狀態都能走、但不在 transitions 裡的轉移
  （例如 proven_impossible_by_pdr 列出的），就是證明過永遠不會發生的；要說清楚是在哪些狀態才會發生，必要時讀原始碼解釋為什麼其他狀態不會。
- 你看不到圖片本身。描述時序圖時，只能用 draw_timing 回傳的 drawn：畫了哪幾拍（cycles）、每條訊號依序出現的值、因果箭頭的路徑。
  圖只涵蓋短短幾拍、看不到使用者想看的完整過程時（例如整個位元組），要直接說出來，不要說圖上看得到它沒畫的東西。
- 工具出錯或做不到，就照實說原因，不要編造圖或數字。
- 圖會直接顯示在畫面右側，你不用重貼路徑；用標題提到它即可。最後用三到六句話總結。"""

TOOLS = [
    {"name": "list_designs", "description": "列出可用的設計（語料庫裡的 30 個開源設計），以及如何指定使用者自己的 RTL 資料夾。",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "analyze_design",
     "description": "L1 對設計的語意解讀：檔案、時脈、reset 與極性、握手介面（每個訊號的角色 valid/ready/data/addr…）、狀態暫存器候選與狀態名稱。啟發式結果，重要結論要用 read_source 確認。",
     "input_schema": {"type": "object", "properties": {"design": {"type": "string", "description": "設計名稱，或 dir:/path#top"}},
                      "required": ["design"], "additionalProperties": False}},
    {"name": "read_source", "description": "讀設計的原始碼。給 grep 時回傳提到這個訊號的所有行；否則回傳 start 到 end 行（最多 200 行）。",
     "input_schema": {"type": "object", "properties": {"design": {"type": "string"}, "file": {"type": "string", "description": "檔名，例如 spimemio.v"},
                                                       "start": {"type": "integer"}, "end": {"type": "integer"},
                                                       "grep": {"type": "string", "description": "訊號名稱"}},
                      "required": ["design", "file"], "additionalProperties": False}},
    {"name": "draw_block", "description": "畫架構圖（方塊圖）。view: paper＝交叉最少的論文版、system＝整體系統版、all＝全部版面。",
     "input_schema": {"type": "object", "properties": {"design": {"type": "string"}, "view": {"type": "string", "enum": ["paper", "system", "all"]}},
                      "required": ["design", "view"], "additionalProperties": False}},
    {"name": "draw_fsm",
     "description": "畫已證明的狀態機圖：x5 證明器算出圖、獨立檢查器重證。每條轉移都有可重播的軌跡或不可能發生的證明。語料庫設計會直接取用已稽核的結果；新設計要幾分鐘。",
     "input_schema": {"type": "object", "properties": {
         "design": {"type": "string"}, "signal": {"type": "string", "description": "狀態暫存器名稱"},
         "scope": {"type": "array", "items": {"type": "string"}, "description": "子模組實例路徑，例如 [\"cpu\"]；狀態機在頂層時省略"},
         "reset": {"type": "string", "description": "reset 埠名，確定時才填"}, "active_low": {"type": "boolean"},
         "aux": {"type": "array", "items": {"type": "string"}, "description": "一起觀測、證明後丟掉的輔助訊號"}},
         "required": ["design", "signal"], "additionalProperties": False}},
    {"name": "draw_timing", "description": "畫時序圖：x4 用模擬器產生波形、重播比對、畫出交握與因果箭頭。interface 填通道或訊號名稱；回傳也會列出所有可畫的通道。",
     "input_schema": {"type": "object", "properties": {"design": {"type": "string"}, "interface": {"type": "string"},
                                                       "max_diagrams": {"type": "integer", "description": "最多幾張，預設 4"}},
                      "required": ["design"], "additionalProperties": False}},
]


def call_tool(name, args, session):
    """-> (result for the model, artifacts for the screen)"""
    if name == "list_designs":
        r = B.designs()
    elif name == "analyze_design":
        r = B.analyze(args["design"])
    elif name == "read_source":
        r = B.read_source(args["design"], args["file"], args.get("start", 1), args.get("end"), args.get("grep"))
    elif name == "draw_block":
        r = B.block(args["design"], args.get("view", "paper"), session=session)
    elif name == "draw_fsm":
        r = B.fsm(args["design"], args["signal"], scope=args.get("scope"), reset=args.get("reset"), active_low=args.get("active_low"),
                  aux=args.get("aux"), session=session)
    elif name == "draw_timing":
        r = B.timing(args["design"], args.get("interface"), int(args.get("max_diagrams") or 4), session=session)
    else:
        raise B.ToolError(f"no tool {name}")
    arts = r.get("artifacts", []) if isinstance(r, dict) else []
    for_model = dict(r)
    if arts:  # the model gets what each drawing shows, not the file
        for_model["artifacts"] = [{"title": a["title"], "caption": a["caption"], "facts": a.get("facts")} for a in arts]
    return for_model, arts


def run(prompt, history, session, emit):
    """One user request through the agent loop. history: earlier messages of this session (kept,
    appended in place). emit(event_dict) is called for every step the screen shows."""
    client = anthropic.Anthropic()
    history.append({"role": "user", "content": prompt})
    for rnd in range(int(CFG.get("max_tool_rounds", 14))):
        t0 = time.time()
        try:
            # Adaptive thinking; a summary of it is shown as the agent's reasoning. On models that have it,
            # server-side fallback reruns a request a safety classifier declined on a fallback model.
            model = CFG.get("model", "claude-opus-5-5")
            extra = {}
            if model in FALLBACK_MODELS:  # Haiku has no server-side fallback
                extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
            resp = client.beta.messages.create(
                model=model, max_tokens=16000, system=SYSTEM, tools=TOOLS, messages=history,
                thinking={"type": "adaptive", "display": "summarized"}, output_config={"effort": CFG.get("effort", "medium")}, **extra)
        except anthropic.AuthenticationError:
            emit({"type": "error", "text": "API key 無效。請檢查 agent_demo/.env 的 ANTHROPIC_API_KEY。"})
            return
        except anthropic.RateLimitError:
            emit({"type": "error", "text": "API 速率限制，請稍後再試。"})
            return
        except anthropic.APIStatusError as e:
            emit({"type": "error", "text": f"API 錯誤 {e.status_code}：{e.message}"})
            return
        except anthropic.APIConnectionError:
            emit({"type": "error", "text": "連不上 API，請檢查網路。"})
            return
        history.append({"role": "assistant", "content": resp.content})  # thinking blocks go back unchanged
        for b in resp.content:
            if b.type == "thinking" and getattr(b, "thinking", ""):
                emit({"type": "thinking", "text": b.thinking})
            elif b.type == "text" and b.text.strip():
                emit({"type": "text", "text": b.text})
        emit({"type": "usage", "round": rnd + 1, "seconds": round(time.time() - t0, 1), "model": resp.model,
              "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens})
        if resp.stop_reason == "refusal":
            emit({"type": "error", "text": "模型拒絕了這個請求。"})
            return
        if resp.stop_reason == "max_tokens":
            emit({"type": "error", "text": "回答超過長度上限，被截斷。"})
            return
        if resp.stop_reason == "pause_turn":
            continue
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            emit({"type": "done"})
            return
        results = []
        for u in uses:
            emit({"type": "tool", "name": u.name, "input": u.input, "id": u.id})
            t1 = time.time()
            try:
                out, arts = call_tool(u.name, dict(u.input or {}), session)
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps(out, ensure_ascii=False, default=str)[:60000]})
                emit({"type": "tool_done", "id": u.id, "name": u.name, "seconds": round(time.time() - t1, 1), "ok": True,
                      "brief": _brief(u.name, out)})
                for a in arts:
                    emit({"type": "artifact", **a})
            except B.ToolError as ex:
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"錯誤：{ex}", "is_error": True})
                emit({"type": "tool_done", "id": u.id, "name": u.name, "seconds": round(time.time() - t1, 1), "ok": False, "brief": str(ex)[:300]})
            except Exception as ex:  # noqa: BLE001
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"工具內部錯誤：{ex!r}"[:2000], "is_error": True})
                emit({"type": "tool_done", "id": u.id, "name": u.name, "seconds": round(time.time() - t1, 1), "ok": False,
                      "brief": f"內部錯誤 {type(ex).__name__}: {ex}"[:300], "trace": traceback.format_exc()[-1500:]})
        history.append({"role": "user", "content": results})
    emit({"type": "error", "text": "工具呼叫輪數到了上限，先停在這裡。"})


def _brief(name, out):
    if name == "list_designs":
        return f"{len(out['designs'])} 個設計"
    if name == "analyze_design":
        return (f"頂層 {out['top']}；時脈 {', '.join(c.get('port', '?') for c in out['clocks'])}；"
                f"reset {', '.join(r.get('port', '?') + ('（低態有效）' if r.get('active_low') else '') for r in out['resets'])}；"
                f"{len(out['interfaces'])} 個介面；狀態暫存器候選 {', '.join(str(f['state_signal']) for f in out['state_register_candidates']) or '無'}")
    if name == "read_source":
        return (f"{out['file']} 中提到 {out['signal']} 的 {out['total_hits']} 行" if "signal" in out else f"{out['file']} 第 {out['from']}–{out['to']} 行")
    if name in ("draw_block", "draw_fsm", "draw_timing"):
        return "、".join(a["title"] for a in out.get("artifacts", [])) or out.get("note", "沒有圖")
    return ""


if __name__ == "__main__":
    if not load_key():
        sys.exit("ANTHROPIC_API_KEY 尚未設定：在 agent_demo/.env 寫入 ANTHROPIC_API_KEY=你的key")
    hist = []
    run(" ".join(sys.argv[1:]) or "畫出 spimemio 的狀態機並說明", hist, "cli",
        lambda e: print(json.dumps(e, ensure_ascii=False)[:600], flush=True))
