"""The web demo: python server.py, then open http://localhost:8765

Each browser tab is a session with its own conversation. The agent runs in a background thread;
the page polls /api/events and shows every step: the agent's reasoning summary, each tool call and
its result, every drawing, the answer. A transcript of each session is kept in runs/<session>/.
"""
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import agent as A

HERE = Path(__file__).resolve().parent
WEB, RUNS = HERE / "web", HERE / "runs"
SESS = {}
LOCK = threading.Lock()
TYPES = {".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".js": "text/javascript", ".css": "text/css",
         ".png": "image/png", ".json": "application/json"}


def session(sid):
    with LOCK:
        return SESS.setdefault(sid, {"history": [], "events": [], "busy": False})


def worker(sid, prompt):
    s = session(sid)
    log = RUNS / sid / "transcript.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)

    def emit(e):
        e = dict(e, t=round(time.time(), 2))
        with LOCK:
            s["events"].append(e)
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")

    emit({"type": "user", "text": prompt})
    try:
        A.run(prompt, s["history"], sid, emit)
    except Exception as ex:  # noqa: BLE001
        emit({"type": "error", "text": f"agent 發生錯誤：{ex!r}"[:400]})
    finally:
        s["busy"] = False
        emit({"type": "idle"})


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self._send(200, (WEB / "index.html").read_bytes(), TYPES[".html"])
        if u.path == "/api/status":
            return self._send(200, {"key": A.load_key(), "model": A.CFG.get("model"), "effort": A.CFG.get("effort")})
        if u.path == "/api/events":
            q = parse_qs(u.query)
            s = session(q.get("session", [""])[0])
            n = int(q.get("since", ["0"])[0])
            with LOCK:
                ev = s["events"][n:]
            return self._send(200, {"events": ev, "next": n + len(ev), "busy": s["busy"]})
        if u.path.startswith("/runs/"):
            p = (HERE / unquote(u.path.lstrip("/"))).resolve()
            if RUNS.resolve() in p.parents and p.is_file():
                return self._send(200, p.read_bytes(), TYPES.get(p.suffix, "application/octet-stream"))
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/chat":
            if not A.load_key():
                return self._send(400, {"error": "API key 尚未設定：請在 agent_demo/.env 填入 ANTHROPIC_API_KEY，然後重新啟動。"})
            sid = body.get("session") or uuid.uuid4().hex[:10]
            s = session(sid)
            if s["busy"]:
                return self._send(409, {"error": "上一個請求還在跑"})
            s["busy"] = True
            threading.Thread(target=worker, args=(sid, str(body.get("prompt", ""))[:4000]), daemon=True).start()
            return self._send(200, {"session": sid})
        if u.path == "/api/reset":
            with LOCK:
                SESS.pop(body.get("session", ""), None)
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(A.CFG.get("port", 8765))
    print(f"RTL-To-Graph agent demo: http://localhost:{port}   (API key {'found' if A.load_key() else 'NOT SET: fill agent_demo/.env'})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
