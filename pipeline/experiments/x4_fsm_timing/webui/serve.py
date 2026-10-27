"""x4 web UI: drop RTL files or a folder, pick the top, get the Block / FSM / Timing gallery.

    uv run --package rtl2d-l1 python pipeline/experiments/x4_fsm_timing/webui/serve.py \\
        [--port 8765] [--runner pipeline/experiments/x4_fsm_timing/x4_run.py] [--timeout 600]

Dev tool only: binds 127.0.0.1, no auth, writes nothing outside runs/x4_fsm_timing/web/.

Routes
  GET  /                    index.html (drop zone, top-module field, Block/FSM/Timing boxes)
  POST /run                 JSON {top, parts: [..], files: [{path, b64}]} or multipart/form-data
                            (fields top, parts, and file parts whose filename is the relative
                            path, or a `path` field before each file) -> {sha, state}
  GET  /status/<sha>        {state: queued|running|done|error, log_tail, log_url, message,
                            position}; log_tail has Python tracebacks folded to one line,
                            the full text stays in run.log (log_url)
  GET  /result/<sha>/       the gallery.html the orchestrator wrote into the run folder
  GET  /result/<sha>/<path> any file under that run folder (side files the gallery links)

A run folder is runs/x4_fsm_timing/web/<sha>/ where <sha> is the sha256 of the uploaded file
paths and contents plus the top and the parts, so dropping the same RTL again reuses the
finished run. Files are kept under <sha>/rtl/ with their relative paths (only *.v *.sv *.vh
*.svh). Runs execute one at a time (a queue protects the 7 GB VM): the orchestrator
[python, x4_run.py, --rtl, <sha>/rtl, --top, T, --part, P, --out, <sha>] runs under a wall
clock timeout and, when systemd-run works, a cgroup memory cap; its output goes to <sha>/run.log
and its state to <sha>/status.json. Pages never show a Python traceback: the server prints
its own to stderr and folds the orchestrator's in log_tail. Rejected FSMs of web runs are
appended to runs/x4_fsm_timing/web/suggested_manifest_entries.json for a human to review; the
files they list live in the git-ignored run folder and must be copied to a tracked place first.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
X4 = HERE.parent
ROOT = X4.parents[2]
WEB = ROOT / "runs" / "x4_fsm_timing" / "web"
RTL_EXT = {".v", ".sv", ".vh", ".svh"}
PARTS = ("block", "fsm", "timing")
MAX_BODY = 64 * 1024 * 1024
MAX_FILES = 4000
SHA = re.compile(r"^[0-9a-f]{64}$")
TOP = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
MIME = {".html": "text/html; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
        ".json": "application/json", ".css": "text/css", ".js": "text/javascript"}


def _load_tools():
    if "x4_tools" in sys.modules:
        return sys.modules["x4_tools"]
    spec = importlib.util.spec_from_file_location("x4_tools", X4 / "x4_tools.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["x4_tools"] = mod
    spec.loader.exec_module(mod)
    return mod


class UserError(Exception):
    """A problem with the request, shown to the user as is."""


# ------------------------------------------------------------------ uploads
def clean_path(p: str) -> str | None:
    """Relative POSIX path inside the upload, or None if it is unsafe or not RTL."""
    p = p.replace("\\", "/").lstrip("/")
    parts = [x for x in PurePosixPath(p).parts if x not in ("", ".")]
    if not parts or any(x == ".." or ":" in x for x in parts):
        return None
    if PurePosixPath(parts[-1]).suffix.lower() not in RTL_EXT:
        return None
    return "/".join(parts)


def parse_json(body: bytes) -> tuple[str, list[str], dict[str, bytes]]:
    try:
        req = json.loads(body)
    except ValueError as e:
        raise UserError("the request is not valid JSON") from e
    if not isinstance(req, dict):
        raise UserError("the JSON body must be an object {top, parts, files}")
    flist = req.get("files") or []
    if not isinstance(flist, list):
        raise UserError("files must be a list of {path, b64} objects")
    files = {}
    for i, f in enumerate(flist):
        if not (isinstance(f, dict) and isinstance(f.get("path"), str)
                and isinstance(f.get("b64"), str)):
            raise UserError(f"files[{i}] is not a {{path, b64}} object with string values")
        try:
            files[f["path"]] = base64.b64decode(f["b64"], validate=True)
        except ValueError as e:
            raise UserError(f"files[{i}] ({f['path'][:80]!r}): b64 is not valid base64") from e
    parts = req.get("parts") or list(PARTS)
    if isinstance(parts, str):
        parts = parts.split(",")
    if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
        raise UserError("parts must be a list of strings or a comma-separated string")
    top = req.get("top") or ""
    if not isinstance(top, str):
        raise UserError("top must be a string")
    return top.strip(), parts, files


def parse_multipart(ctype: str, body: bytes) -> tuple[str, list[str], dict[str, bytes]]:
    msg = BytesParser(policy=HTTP).parsebytes(
        f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body)
    if not msg.is_multipart():
        raise UserError("multipart body could not be parsed")
    top, parts, files, pending = "", [], {}, None
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        fname = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if fname is not None:
            files[pending or fname] = data
            pending = None
        elif name == "top":
            top = data.decode(errors="replace").strip()
        elif name == "parts":
            parts += [p for p in data.decode(errors="replace").split(",") if p]
        elif name == "path":
            pending = data.decode(errors="replace")
    return top, parts or list(PARTS), files


def validate(top: str, parts: list[str], files: dict[str, bytes]) -> tuple[dict, list[str]]:
    """Kept files {relative path: bytes} and the parts; raises UserError with a reason."""
    if not TOP.match(top):
        raise UserError("enter the top module name (letters, digits, _ and $ only)")
    parts = [p.strip().lower() for p in parts if p.strip()]
    bad = [p for p in parts if p not in PARTS]
    if bad or not parts:
        raise UserError(f"parts must be a non-empty subset of {', '.join(PARTS)}")
    kept = {}
    for p, data in files.items():
        c = clean_path(p)
        if c:
            kept[c] = data
    if not kept:
        raise UserError("no Verilog/SystemVerilog file (*.v *.sv *.vh *.svh) in the upload")
    if len(kept) > MAX_FILES:
        raise UserError(f"too many files ({len(kept)} > {MAX_FILES})")
    if not any(re.search(rb"\bmodule\s+" + re.escape(top.encode()) + rb"\b", d)
               for d in kept.values()):
        raise UserError(f"no file declares module {top!r}")
    return kept, [p for p in PARTS if p in parts]


RUN_VERSION = "x4-r3 prove60"


def run_key(top: str, parts: list[str], files: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(p.encode() + b"\0" + hashlib.sha256(files[p]).digest())
    # RUN_VERSION: bump when the orchestrator command or its outputs change, so an old cached
    # result is not served for a request the current runner would answer differently
    h.update(f"\0top={top}\0parts={','.join(parts)}\0v={RUN_VERSION}".encode())
    return h.hexdigest()


# ------------------------------------------------------------------ runs
class Runner:
    """One orchestrator subprocess at a time; the rest wait in a FIFO queue."""

    def __init__(self, web: Path, runner: Path, timeout: float, mem: str) -> None:
        self.web, self.runner, self.timeout, self.mem = web, runner, timeout, mem
        self.q: queue.Queue[str] = queue.Queue()
        self.order: list[str] = []
        self.lock = threading.Lock()  # status.json, order, suggestions
        self.submit_lock = threading.Lock()  # check-and-enqueue is atomic per server
        self.capped = self._probe_systemd()
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _probe_systemd() -> bool:
        try:
            r = subprocess.run(["systemd-run", "--scope", "--quiet", "-p", "MemoryMax=64M",
                                "true"], capture_output=True, timeout=20)
            return r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    # status files
    def dir(self, sha: str) -> Path:
        return self.web / sha

    def status(self, sha: str) -> dict | None:
        f = self.dir(sha) / "status.json"
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def write_status(self, sha: str, **kw) -> dict:
        with self.lock:
            st = self.status(sha) or {}
            st.update(kw)
            f = self.dir(sha) / "status.json"
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
            tmp.replace(f)
            return st

    def recover(self) -> None:
        """Runs left queued or running by a previous server process cannot finish."""
        if not self.web.is_dir():
            return
        for d in self.web.iterdir():
            st = self.status(d.name) if SHA.match(d.name) else None
            if st and st.get("state") in ("queued", "running"):
                self.write_status(d.name, state="error",
                                  message="the server was restarted before this run finished; "
                                          "drop the files again to rerun")

    # submit / execute
    def submit(self, top: str, parts: list[str], files: dict[str, bytes]) -> dict:
        sha = run_key(top, parts, files)
        with self.submit_lock:  # identical concurrent POSTs: only the first one enqueues
            st = self.status(sha)
            if st and st.get("state") in ("queued", "running", "done"):
                return {"sha": sha, "state": st["state"], "cached": st["state"] == "done"}
            self._store(sha, files)
            self.write_status(sha, state="queued", top=top, parts=parts, files=sorted(files),
                              created=time.time(), message=None, returncode=None)
            with self.lock:
                self.order.append(sha)
            self.q.put(sha)
        return {"sha": sha, "state": "queued", "cached": False}

    def _store(self, sha: str, files: dict[str, bytes]) -> None:
        d = self.dir(sha)
        rtl = d / "rtl"
        for p, data in files.items():
            f = (rtl / p).resolve()
            if not f.is_relative_to(rtl.resolve()):
                continue  # clean_path already refused this; belt and braces
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)

    def position(self, sha: str) -> int | None:
        with self.lock:
            return self.order.index(sha) if sha in self.order else None

    def command(self, sha: str, st: dict) -> list[str]:
        d = self.dir(sha)
        cmd = [sys.executable, str(self.runner), "--rtl", str(d / "rtl"), "--top", st["top"],
               "--part", ",".join(st["parts"]), "--out", str(d)]
        if "fsm" in st["parts"]:  # G6 completeness proof, kept short for an interactive page
            cmd += ["--prove", "--prove-timeout", "60"]
        if self.capped:
            cmd = ["systemd-run", "--scope", "--quiet", "-p", f"MemoryMax={self.mem}",
                   "-p", "MemorySwapMax=0", *cmd]
        return cmd

    def _loop(self) -> None:
        while True:
            sha = self.q.get()
            try:
                self.execute(sha)
            except Exception as e:  # noqa: BLE001 - one bad run must not stop the queue
                traceback.print_exc()
                self.write_status(sha, state="error", message=f"internal error: {e}")
            finally:
                with self.lock:
                    if sha in self.order:
                        self.order.remove(sha)

    def execute(self, sha: str) -> None:
        st = self.status(sha) or {}
        d = self.dir(sha)
        cmd = self.command(sha, st)
        t0 = time.time()
        self.write_status(sha, state="running", started=t0, cmd=cmd)
        env = _load_tools().tool_env()
        env["PYTHONUNBUFFERED"] = "1"
        with open(d / "run.log", "w", encoding="utf-8") as log:
            p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
            try:
                rc = p.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
                self.write_status(sha, state="error", returncode=124, finished=time.time(),
                                  message=f"the run took longer than {self.timeout:g} s and "
                                          f"was stopped; try a smaller design or fewer parts")
                return
        secs = round(time.time() - t0, 1)
        gallery = d / "gallery.html"
        if gallery.exists() and gallery.stat().st_mtime >= t0:
            msg = None if rc == 0 else f"the orchestrator exited {rc}; the page may be partial"
            self.write_status(sha, state="done", returncode=rc, finished=time.time(),
                              seconds=secs, message=msg)
            self.suggest(sha, st)
        else:
            self.write_status(sha, state="error", returncode=rc, finished=time.time(),
                              seconds=secs, message=f"the orchestrator exited {rc} without "
                              f"writing a gallery; the log has the details")

    def suggest(self, sha: str, st: dict) -> None:
        """Rejected FSMs of this run -> suggested_manifest_entries.json (human review)."""
        try:
            rej = json.loads((self.dir(sha) / "rejected.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not rej:
            return
        f = self.web / "suggested_manifest_entries.json"
        with self.lock:
            try:
                rows = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                rows = []
            if any(r.get("sha") == sha for r in rows):
                return
            rtl = self.dir(sha) / "rtl"
            rows.append({"sha": sha, "name": f"web_{st['top']}_{sha[:8]}", "top": st["top"],
                         "files": [str((rtl / p).relative_to(ROOT)) for p in st["files"]],
                         "note": "files are in the git-ignored web run folder; copy them to a "
                                 "tracked location and fix these paths before adding this row "
                                 "to a manifest",
                         "rejected": rej, "added": time.strftime("%Y-%m-%d %H:%M")})
            f.write_text(json.dumps(rows, indent=1), encoding="utf-8")


TB_HEAD = "Traceback (most recent call last):"
TB_CHAIN = ("During handling of the above exception", "The above exception was the direct cause")
TB_FRAME = re.compile(r'^\s+File "[^"]*", line \d+')


def _tb_start(line: str) -> bool:
    """A traceback header, a chained-exception header, or a frame (tail cut mid-traceback)."""
    return line.strip() == TB_HEAD or line.startswith(TB_CHAIN) or bool(TB_FRAME.match(line))


def fold_tracebacks(lines: list[str]) -> list[str]:
    """Replace each Python traceback block by one line naming its final exception line.

    A block starts at TB_HEAD and runs over indented frame lines (and chained-exception
    headers) up to the first non-indented line, which is the exception itself.
    """
    out, i = [], 0
    while i < len(lines):
        if not _tb_start(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        j = i + 1
        while j < len(lines) and (lines[j][:1] in (" ", "\t", "") or lines[j].startswith(TB_CHAIN)
                                  or lines[j].strip() == TB_HEAD):
            j += 1
        exc = lines[j].strip() if j < len(lines) else "(cut off)"
        out.append(f"[Python traceback hidden; see the full log] {exc[:300]}")
        i = j + 1
    return out


def log_tail(path: Path, n: int = 40) -> str:
    """Last n lines of a run log, tracebacks folded (the page must not show them)."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            lines = fh.read().decode(errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(fold_tracebacks(lines)[-n:])


# ------------------------------------------------------------------ HTTP
def friendly_page(title: str, text: str, status: int = 404) -> tuple[int, bytes]:
    from html import escape

    body = (f"<!doctype html><meta charset=utf-8><meta name=viewport "
            f"content='width=device-width,initial-scale=1'><title>{escape(title)}</title>"
            f"<style>body{{font:15px/1.5 system-ui,sans-serif;margin:40px 16px;color:#1b2328;"
            f"background:#f3f5f6}}main{{max-width:640px;margin:auto}}a{{color:#1f6f5c}}"
            f"@media (prefers-color-scheme:dark){{body{{background:#12171a;color:#e3e8eb}}"
            f"a{{color:#5fc3a6}}}}</style><main><h1>{escape(title)}</h1><p>{escape(text)}</p>"
            f"<p><a href='/'>Back to the drop page</a></p></main>")
    return status, body.encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "x4web/0.1"
    runner: Runner  # set by make_server

    def log_message(self, fmt: str, *args) -> None:  # one short line per request on stderr
        sys.stderr.write(f"[x4web] {self.address_string()} {fmt % args}\n")

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj: dict, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _page(self, title: str, text: str, status: int = 404) -> None:
        code, body = friendly_page(title, text, status)
        self._send(code, body, "text/html; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        try:
            self._get()
        except Exception:  # noqa: BLE001 - never a traceback on the page
            traceback.print_exc()
            self._page("Something went wrong", "The server hit an internal error; its console "
                       "has the details.", 500)

    do_HEAD = do_GET

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        try:
            if urlsplit(self.path).path != "/run":
                return self._json({"error": "unknown endpoint"}, 404)
            self._json(self._post_run())
        except UserError as e:
            self._json({"error": str(e)}, 400)
        except Exception:  # noqa: BLE001 - never a traceback on the page
            traceback.print_exc()
            self._json({"error": "internal server error; see the server console"}, 500)

    def _post_run(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise UserError("empty request")
        if n > MAX_BODY:
            raise UserError(f"upload too large ({n / 2**20:.1f} MiB > {MAX_BODY // 2**20} MiB)")
        body = self.rfile.read(n)
        ctype = self.headers.get("Content-Type") or ""
        if ctype.startswith("multipart/form-data"):
            top, parts, files = parse_multipart(ctype, body)
        else:
            top, parts, files = parse_json(body)
        kept, parts = validate(top, parts, files)
        return self.runner.submit(top, parts, kept)

    def _get(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path in ("/", "/index.html"):
            body = (HERE / "index.html").read_bytes()
            return self._send(200, body, "text/html; charset=utf-8")
        m = re.match(r"^/status/([0-9a-f]{64})$", path)
        if m:
            return self._status(m.group(1))
        m = re.match(r"^/result/([0-9a-f]{64})(/.*)?$", path)
        if m:
            return self._result(m.group(1), m.group(2))
        self._page("Not found", f"There is nothing at {path}.")

    def _status(self, sha: str) -> None:
        st = self.runner.status(sha)
        if st is None:
            return self._json({"state": "error", "message": "unknown run"}, 404)
        out = {k: st.get(k) for k in ("state", "message", "top", "parts", "seconds",
                                      "returncode")}
        out["position"] = self.runner.position(sha) if st.get("state") == "queued" else None
        out["log_tail"] = log_tail(self.runner.dir(sha) / "run.log")
        has_log = (self.runner.dir(sha) / "run.log").is_file()
        out["log_url"] = f"/result/{sha}/run.log" if has_log else None
        out["result"] = f"/result/{sha}/" if st.get("state") == "done" else None
        self._json(out)

    def _result(self, sha: str, rest: str | None) -> None:
        if rest is None:  # relative links in the gallery need the trailing slash
            return self._send(301, b"", "text/plain", {"Location": f"/result/{sha}/"})
        d = self.runner.dir(sha).resolve()
        st = self.runner.status(sha)
        if st is None:
            return self._page("Unknown run", "No run with this id exists on this server.")
        if rest == "/":
            if st.get("state") != "done":
                msg = st.get("message") or f"The run is {st.get('state')}; try again shortly."
                return self._page("No result yet", msg, 404)
            rest = "/gallery.html"
        f = (d / rest.lstrip("/")).resolve()
        if not f.is_relative_to(d) or not f.is_file():
            return self._page("Not found", "That file is not part of this run.")
        ctype = MIME.get(f.suffix.lower(), "text/plain; charset=utf-8")
        self._send(200, f.read_bytes(), ctype)


def make_server(host: str, port: int, runner: Runner) -> ThreadingHTTPServer:
    handler = type("X4Handler", (Handler,), {"runner": runner})
    return ThreadingHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1", help="keep it on loopback (no auth)")
    ap.add_argument("--runner", default=str(X4 / "x4_run.py"),
                    help="orchestrator script (a stub for testing)")
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--mem", default="50%", help="cgroup MemoryMax when systemd-run works")
    ap.add_argument("--web-root", default=str(WEB), help="must lie under <repo>/runs/")
    a = ap.parse_args(argv)
    web = Path(a.web_root)
    web = (web if web.is_absolute() else ROOT / web).resolve()
    if not web.is_relative_to((ROOT / "runs").resolve()):
        print(f"--web-root must lie under {ROOT / 'runs'}", file=sys.stderr)
        return 2
    runner_py = Path(a.runner)
    runner_py = (runner_py if runner_py.is_absolute() else ROOT / runner_py).resolve()
    if not runner_py.is_file():
        print(f"runner not found: {runner_py}", file=sys.stderr)
        return 2
    web.mkdir(parents=True, exist_ok=True)
    runner = Runner(web, runner_py, a.timeout, a.mem)
    runner.recover()
    srv = make_server(a.host, a.port, runner)
    print(f"[x4web] http://{a.host}:{srv.server_address[1]}/  runs -> {web}  runner {runner_py}"
          f"  memory cap {'on' if runner.capped else 'off'}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
