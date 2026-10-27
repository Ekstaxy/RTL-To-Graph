"""x3: run external RTL -> diagram tools on the same RTL as ours and collect their drawings.

Each tool runs the way its own source or README runs it (tools.json "recipe"). Browser-only
renderers (d3-hwschematic, DigitalJS, Digital-IDE) run in headless Chromium via Playwright.
Nothing in any layer is imported; "ours" is copied from runs/x2_l1_to_paper/svg/ (top set) or
runs/x3_tool_compare/ours_modules/svg/ (module set, drawn by ours_modules.py).

    pipeline/experiments/x3_tool_compare/install.sh          # once
    uv run --no-project --with playwright==1.49.1 python \\
        pipeline/experiments/x3_tool_compare/run.py --set top|module|recompare \\
        [--only netlistsvg,teroshdl] [--designs picosoc]
    uv run --no-project python pipeline/experiments/x3_tool_compare/gallery.py --set ...
Output: runs/x3_tool_compare/{rtl/,out*/<design>/<tool>.svg,logs*/,results*.json}
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CORPUS = ROOT / "layers" / "l1_extract" / "data" / "corpus"
X2 = ROOT / "runs" / "x2_l1_to_paper"
OUT = ROOT / "runs" / "x3_tool_compare"
T = ROOT / "runs" / ".tools" / "x3"
SRC = T / "src"
YOSYS = T / "oss-cad-suite" / "bin" / "yosys"
NODE = T / "node" / "bin" / "node"
PY = T / "pyenv" / "bin" / "python"
DIDE_VIEW = T / "vsix" / "dide046" / "extension" / "resources" / "dide-netlist" / "view"
ENV = dict(os.environ, PATH=os.pathsep.join([
    str(T / "oss-cad-suite" / "bin"), str(T / "node" / "bin"),
    str(T / "bin"), str(T / "pyenv" / "bin"),
    os.environ["PATH"]]))
TIMEOUT = 900
# Every tool runs in its own cgroup with a hard memory cap and no swap. WSL2 gets half the host's
# RAM; when a render outgrows it (TerosHDL on picosoc peaks near 2 GB) the whole VM can go down
# instead of the kernel killing one process. With the cap only that tool is killed.
MEM_GB = 3.0
CAP = ["systemd-run", "--scope", "-q", "-p", "MemorySwapMax=0"] if shutil.which(
    "systemd-run") else []


class ToolError(RuntimeError):
    pass


def sh(cmd: list, log: Path, cwd: Path | None = None, mem_gb: float = MEM_GB) -> str:
    """Run cmd under the memory cap, append its output to log, raise ToolError with the tail
    on failure."""
    full = [*CAP, "-p", f"MemoryMax={int(mem_gb * 1024)}M", *cmd] if CAP else cmd
    with log.open("a") as fh:
        fh.write("$ " + " ".join(map(str, full)) + "\n")
    p = subprocess.run([str(c) for c in full], cwd=cwd, env=ENV, capture_output=True,
                       text=True, timeout=TIMEOUT)
    with log.open("a") as fh:
        fh.write(p.stdout + p.stderr + f"[exit {p.returncode}]\n")
    if p.returncode == -9 or p.returncode == 137:
        raise ToolError(f"killed: used more than the {mem_gb:g} GB memory cap")
    if p.returncode != 0:
        tail = (p.stdout + p.stderr).strip().splitlines()[-12:]
        raise ToolError("\n".join(tail) or f"exit {p.returncode}")
    return p.stdout


# --------------------------------------------------------------------------- RTL


def prepare(d: dict) -> dict:
    """Copy the design's files under runs/x3_tool_compare/rtl/<name>/ (first path component
    dropped, so relative includes such as darksocv's "../rtl/config.vh" still resolve)."""
    base = OUT / "rtl" / d["name"]
    files = []
    for rel in d["files"]:
        dst = base / Path(*Path(rel).parts[1:])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CORPUS / rel, dst)
        files.append(dst)
    incs = []
    for rel in d["include_dirs"]:
        src = CORPUS / rel
        dst = base / Path(*Path(rel).parts[1:])
        for h in list(src.glob("*.vh")) + list(src.glob("*.svh")):
            shutil.copy2(h, dst / h.name)
        incs.append(dst)
    for rel in d.get("data_files", []):
        dst = base / Path(*Path(rel).parts[1:])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CORPUS / rel, dst)
    top_file = next(f for f in files if f.name == d.get("top_file", d["top"] + ".v"))
    concat = top_file.parent / "_all.v"  # beside the top file so its includes resolve
    concat.write_text("".join(f.read_text(errors="replace") + "\n" for f in files))
    return dict(d, paths=files, incs=incs, top_file=top_file, concat=concat)


def rel(d: dict, paths: list[Path]) -> list[str]:
    """Paths relative to the run directory (the top file's), as a user would type them; Yosys
    copies them into cell names (src attributes), which some tools print as labels."""
    return [os.path.relpath(p, d["top_file"].parent) for p in paths]


def read_cmds(d: dict, flags: str = "-sv", each: bool = False) -> str:
    inc = " ".join(f"-I{i}" for i in rel(d, d["incs"]))
    if each:
        return "; ".join(f"read_verilog {flags} {inc} {f}" for f in rel(d, d["paths"]))
    return f"read_verilog {flags} {inc} " + " ".join(rel(d, d["paths"]))


def yosys(script: str, log: Path, d: dict) -> None:
    sh([YOSYS, "-q", "-p", script], log, d["top_file"].parent)


# --------------------------------------------------------------------------- tools


def t_netlistsvg(d, o, log):
    j = o.with_suffix(".json")
    yosys(f"{read_cmds(d)}; prep -top {d['top']}; write_json {j}", log, d)
    sh([NODE, SRC / "netlistsvg" / "bin" / "netlistsvg.js", j, "-o", o.with_suffix(".svg")], log)


def t_yosys_show(d, o, log):
    yosys(f"{read_cmds(d)}; prep -top {d['top']}; "
          f"show -format dot -prefix {o.with_suffix('')} {d['top']}", log, d)
    sh(["dot", "-Tsvg", o.with_suffix(".dot"), "-o", o.with_suffix(".svg")], log)


def t_yosys_viz(d, o, log):
    yosys(f"{read_cmds(d)}; prep -top {d['top']}; "
          f"viz -format dot -prefix {o.with_suffix('')} {d['top']}", log, d)
    sh(["dot", "-Tsvg", o.with_suffix(".dot"), "-o", o.with_suffix(".svg")], log)


def t_d3_hwschematic(d, o, log, browser):
    j = o.with_suffix(".json")
    # -compat-int: without it today's Yosys writes parameters as bit strings and the importer
    # throws "Incorrect width00...01" (see tools.json "deviation")
    yosys(f"{read_cmds(d)}; hierarchy -top {d['top']}; "
          f"synth -run coarse -noabc -noalumacc -nordff; splice; "
          f"write_json -compat-int {j}", log, d)
    browser.render(f"/pipeline/experiments/x3_tool_compare/render/d3hw.html?json={url(j)}",
                   o, log, fit="d3hw")


def t_digitaljs(d, o, log, browser):
    j = o.with_suffix(".json")
    sh([NODE, HERE / "render" / "y2d.js", SRC / "yosys2digitaljs", YOSYS, d["top"], j,
        *rel(d, d["paths"])], log, cwd=d["top_file"].parent)
    browser.render(f"/pipeline/experiments/x3_tool_compare/render/digitaljs.html?json={url(j)}",
                   o, log, fit="digitaljs")


def _sphinx(d, o, log, kind):
    """One Sphinx project per (design, type): conf.py + index.rst beside the concatenated
    sources (the directive takes one file, relative to the doc source dir)."""
    src = d["concat"].parent
    (src / "conf.py").write_text("extensions = ['sphinxcontrib_hdl_diagrams']\n"
                                 "hdl_diagram_yosys = 'yowasp'\n")
    (src / "index.rst").write_text(
        f"{d['name']}\n{'=' * len(d['name'])}\n\n.. hdl-diagram:: {d['concat'].name}\n"
        f"   :type: {kind}\n   :module: {d['top']}\n")
    build = o.parent / f"_sphinx_{kind}"
    shutil.rmtree(build, ignore_errors=True)
    try:
        sh([PY, "-m", "sphinx", "-b", "html", "-q", "-d", build / "doctrees", src, build], log,
           cwd=src)
    finally:
        for f in ("conf.py", "index.rst"):
            (src / f).unlink(missing_ok=True)
    svgs = list((build / "_images").glob("*.svg"))
    if not svgs:
        raise ToolError("Sphinx finished but produced no diagram")
    shutil.copy2(svgs[0], o.with_suffix(".svg"))


def t_sphinx_blackbox(d, o, log):
    _sphinx(d, o, log, "yosys-blackbox")


def t_sphinx_netlistsvg(d, o, log):
    _sphinx(d, o, log, "netlistsvg")


def t_symbolator(d, o, log):
    sh([T / "pyenv" / "bin" / "symbolator", "-i", d["top_file"], "-o", o.with_suffix(".svg"),
        "--output-as-filename", "-f", "svg", "--component", d["top"], "--title"], log)


def t_teroshdl(d, o, log):
    j = o.with_suffix(".json")
    yosys(f"{read_cmds(d, each=True)}; hierarchy -top {d['top']}; proc; write_json {j}", log, d)
    skin = SRC / "vscode-terosHDL" / "resources" / "webviews" / "netlist_viewer" / "default.svg"
    # --stack-size: netlistsvg's recursive gather() overflows Node's default ~1 MB stack on
    # picosoc ("Maximum call stack size exceeded"); 8000 KB still fits Linux's 8 MB main stack
    sh([NODE, "--stack-size=8000", HERE / "render" / "teroshdl.js", SRC / "teros-netlistsvg",
        skin, j, o.with_suffix(".svg")], log, mem_gb=3.5)


def t_digital_ide(d, o, log, browser):
    j = o.with_suffix(".json")
    yosys(f"{read_cmds(d, '-sv -formal -overwrite', each=True)}; design -reset-vlog; proc; "
          f"write_json {j}", log, d)
    # the extension rewrites test.json / test.module / dide.skin in index.html and loads it
    view = "/" + DIDE_VIEW.relative_to(ROOT).as_posix()
    html = (DIDE_VIEW / "index.html").read_text()
    html = (html.replace("'test.json'", f"'{url(j)}'").replace("test.module", d["top"])
            .replace("'dide.skin'", f"'{view}/dide.skin'"))
    page = o.parent / "_dide.html"
    page.write_text(html.replace("<head>", f'<head><base href="{view}/">{VSCODE_LIGHT}', 1))
    browser.render(url(page), o, log, fit="dide")


# VS Code injects its theme as --vscode-* variables into every webview; the viewer reads
# --background (= --vscode-editor-background) at start-up and throws without it. Values are
# VS Code's default "Light+" theme.
VSCODE_LIGHT = "<style>:root{" + ";".join(f"--vscode-{k}:{v}" for k, v in {
    "editor-background": "#ffffff", "editor-foreground": "#000000", "foreground": "#616161",
    "sideBar-background": "#f3f3f3", "sideBar-border": "#e5e5e5",
    "sideBarSectionHeader-background": "#f3f3f3", "sideBarSectionHeader-foreground": "#616161",
    "sideBarSectionHeader-border": "#e5e5e5", "activityBar-background": "#2c2c2c",
    "activityBar-inactiveForeground": "#ffffff66", "button-background": "#007acc",
    "button-foreground": "#ffffff", "button-hoverBackground": "#0062a3",
    "input-background": "#ffffff", "input-foreground": "#616161", "input-border": "#cecece",
    "input-placeholderForeground": "#767676", "dropdown-border": "#cecece",
    "list-hoverBackground": "#e8e8e8", "list-inactiveSelectionBackground": "#e4e6f1",
    "list-inactiveSelectionForeground": "#616161", "focusBorder": "#0090f1",
    "textLink-foreground": "#006ab1", "textLink-activeForeground": "#006ab1",
    "icon-foreground": "#424242", "breadcrumb-background": "#ffffff",
    "breadcrumbPicker-background": "#f3f3f3", "quickInput-background": "#f3f3f3",
    "quickInput-foreground": "#616161", "pickerGroup-border": "#cccedb",
    "scrollbarSlider-background": "rgba(100, 100, 100, 0.4)",
    "scrollbarSlider-hoverBackground": "rgba(100, 100, 100, 0.7)",
    "scrollbarSlider-activeBackground": "rgba(0, 0, 0, 0.6)",
    "editorIndentGuide-background": "#d3d3d3", "editorIndentGuide-activeBackground": "#939393",
    "editorCursor-foreground": "#000000", "editor-font-family": "monospace",
    "editor-font-size": "14px", "editor-font-weight": "normal",
    "inputValidation-errorBackground": "#f2dede", "inputValidation-errorBorder": "#be1100",
    "inputValidation-errorForeground": "#000000",
}.items()) + "}</style>"


def t_vl_hier_graph(d, o, log):
    dot = o.with_suffix(".dot")
    inc = [f"+incdir+{i}" for i in d["incs"]]
    sh(["python3", SRC / "verilator" / "examples" / "json_py" / "vl_hier_graph", "-o", dot,
        "--top-module", d["top"], "-Wno-fatal", *inc, *d["paths"]], log, cwd=o.parent)
    # the script sets dpi=300 (meant for PDF/PNG); in SVG that shrinks the drawing into a corner
    sh(["dot", "-Tsvg", "-Gdpi=72", dot, "-o", o.with_suffix(".svg")], log)


TOOLS = {
    "netlistsvg": t_netlistsvg, "yosys_show": t_yosys_show, "yosys_viz": t_yosys_viz,
    "d3_hwschematic": t_d3_hwschematic, "digitaljs": t_digitaljs,
    "sphinx_blackbox": t_sphinx_blackbox, "sphinx_netlistsvg": t_sphinx_netlistsvg,
    "symbolator": t_symbolator, "teroshdl": t_teroshdl, "digital_ide": t_digital_ide,
    "vl_hier_graph": t_vl_hier_graph,
}
BROWSER_TOOLS = {"d3_hwschematic", "digitaljs", "digital_ide"}

# --------------------------------------------------------------------------- minimal options
# Each tool's own most-simplifying option, found in its source or docs by the x3 research
# workflow, tested on both designs and confirmed by an independent reviewer (tools.json
# "minimal" holds the evidence). A tool missing here has no such option and keeps its drawing.


def m_yosys_viz(d, o, log):
    """viz at effort -6, clock/reset excluded (-x), the wires running between instances given
    as one user-defined group (-G ... .), and the instances plus their wires selected."""
    t = d["top"]
    xs = " ".join(f"-x w:{w}" for w in d["clock_reset"])
    inst = f"{t}/t:* {t}/t:$* %d {t}/t:$paramod* %u"
    yosys(f"{read_cmds(d)}; prep -top {t}; select -set inst {inst}; "
          f"viz -format dot -prefix {o.with_suffix('')} -6 {xs} "
          f"-G @inst %co1 @inst %ci1 %i {t}/w:* %i . @inst @inst %x1 %u", log, d)
    sh(["dot", "-Tsvg", o.with_suffix(".dot"), "-o", o.with_suffix(".svg")], log)


def m_yosys_show(d, o, log):
    """show with a selection (show [options] [selection]; yosys -h select): the cells whose
    type is a module (%C), in the top only (%i), plus the wires touching them (%x1)."""
    yosys(f"{read_cmds(d)}; show -format dot -prefix {o.with_suffix('')} -notitle "
          f"-wireshape plaintext * %C {d['top']} %i %x1", log, d)
    sh(["dot", "-Tsvg", o.with_suffix(".dot"), "-o", o.with_suffix(".svg")], log)


def m_d3_hwschematic(d, o, log, browser):
    """The top node starts collapsed (README, LNode: children/edges -> _children/_edges);
    submodules are already collapsed by the importer."""
    j = o.with_suffix(".json")
    yosys(f"{read_cmds(d)}; hierarchy -top {d['top']}; "
          f"synth -run coarse -noabc -noalumacc -nordff; splice; "
          f"write_json -compat-int {j}", log, d)
    browser.render(f"/pipeline/experiments/x3_tool_compare/render/d3hw.html?json={url(j)}"
                   f"&collapse=top", o, log, fit="d3hw")


def m_teroshdl(d, o, log):
    """The fork's hierarchy.enable "off" (its own default; the extension hard-codes "all"),
    plus `opt` typed into the extension's "Arguments passed to Yosys" setting."""
    j = o.with_suffix(".json")
    yosys(f"{read_cmds(d, each=True)}; hierarchy -top {d['top']}; proc; opt; write_json {j}",
          log, d)
    skin = SRC / "vscode-terosHDL" / "resources" / "webviews" / "netlist_viewer" / "default.svg"
    sh([NODE, "--stack-size=8000", HERE / "render" / "teroshdl.js", SRC / "teros-netlistsvg",
        skin, j, o.with_suffix(".svg"), "off"], log, mem_gb=3.5)


def m_digitaljs(d, o, log, browser):
    """DigitalJS's own graph simplification (digitaljs.transform.transformCircuit, the
    "Simplify diagram" box of its web front end) applied before drawing."""
    j = o.with_suffix(".json")
    sh([NODE, HERE / "render" / "y2d.js", SRC / "yosys2digitaljs", YOSYS, d["top"], j,
        *rel(d, d["paths"])], log, cwd=d["top_file"].parent)
    browser.render(f"/pipeline/experiments/x3_tool_compare/render/digitaljs.html?json={url(j)}"
                   f"&transform=1", o, log, fit="digitaljs")


def m_yosys_viz_leaf(d, o, log):
    """Leaf module: viz's most merged effort level (-9 down to -0) that still draws more than
    one group, with clock/reset excluded (-x). At -9 spimemio_xfer is a single blob."""
    t = d["top"]
    xs = " ".join(f"-x w:{w}" for w in d["clock_reset"])
    for effort in range(9, -1, -1):
        yosys(f"{read_cmds(d)}; prep -top {t}; "
              f"viz -format dot -prefix {o.with_suffix('')} -{effort} {xs} {t}", log, d)
        dot = o.with_suffix(".dot").read_text()
        if len(re.findall(r"^\s*n\d+ \[", dot, re.M)) > 1:
            break
    with log.open("a") as fh:
        fh.write(f"chosen effort: -{effort}\n")
    sh(["dot", "-Tsvg", o.with_suffix(".dot"), "-o", o.with_suffix(".svg")], log)


TOOLS_MIN: dict = {"yosys_viz": m_yosys_viz, "yosys_show": m_yosys_show,
                   "d3_hwschematic": m_d3_hwschematic, "teroshdl": m_teroshdl,
                   "digitaljs": m_digitaljs}
# Module set (leaf modules, no submodules): the top-level selections (show: submodule cells;
# viz: instances) and d3's collapsed top (a single box) do not apply; these options do.
MODULE_MIN: dict = {"yosys_viz": m_yosys_viz_leaf, "digitaljs": m_digitaljs,
                    "teroshdl": m_teroshdl}


# --------------------------------------------------------------------------- browser


def url(p: Path) -> str:
    return "/" + p.resolve().relative_to(ROOT).as_posix()


# Make the drawn content the whole <svg>: wrap every child in one <g>, fit the viewBox to its
# bbox (child transforms such as a pan/zoom are kept), inline the page's CSS so the saved file
# draws standalone as it did in the page, and return the markup.
FIT_JS = """(sel) => {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.querySelector(sel);
  if (!svg) throw new Error('no svg ' + sel);
  const w = document.createElementNS(ns, 'g');
  while (svg.firstChild) w.appendChild(svg.firstChild);
  svg.appendChild(w);
  const b = w.getBBox(), m = 20;
  if (!b.width || !b.height) throw new Error('empty drawing');
  svg.setAttribute('viewBox', `${b.x - m} ${b.y - m} ${b.width + 2 * m} ${b.height + 2 * m}`);
  svg.setAttribute('width', b.width + 2 * m); svg.setAttribute('height', b.height + 2 * m);
  svg.removeAttribute('style');  // keep class: some skins scope their CSS under it
  svg.setAttribute('xmlns', ns);
  let css = '';
  // keep only rules that style something in the drawing (plus :root variables and fonts)
  const used = (r) => {
    if (!r.selectorText) return /^@(font-face|keyframes)/.test(r.cssText);
    if (/:root/.test(r.selectorText)) return true;
    try { return !!svg.querySelector(r.selectorText.replace(/::?[a-z-]+(\\([^)]*\\))?/g, '')); }
    catch (e) { return false; }
  };
  for (const s of document.styleSheets) {
    try { for (const r of s.cssRules) if (used(r)) css += r.cssText + '\\n'; } catch (e) {}
  }
  const st = document.createElementNS(ns, 'style');
  st.textContent = css; svg.insertBefore(st, svg.firstChild);
  return new XMLSerializer().serializeToString(svg);  // XML, not HTML (foreignObject content)
}"""
SELECTORS = {"d3hw": "#scheme-placeholder", "digitaljs": "#paper svg", "dide": "svg"}


class Browser:
    def __init__(self):
        from playwright.sync_api import sync_playwright

        handler = functools.partial(_QuietHandler, directory=str(ROOT))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.pw = sync_playwright().start()
        self.chromium = self.pw.chromium.launch()

    def render(self, path: str, o: Path, log: Path, fit: str) -> None:
        page = self.chromium.new_page(viewport={"width": 1600, "height": 1000})
        msgs = []
        page.on("console", lambda m: msgs.append(f"[console.{m.type}] {m.text}"))
        page.on("pageerror", lambda e: msgs.append(f"[pageerror] {e}"))
        try:
            page.goto(self.base + path)
            if fit == "dide":
                # Digital-IDE has no completion flag: wait for its netlist SVG to appear and stop
                # growing. When its renderer throws it stays on the "加载中" (loading) screen
                # forever, so an error with no drawing after 30 s is the result.
                t0 = time.time()
                while not page.query_selector("svg g g"):
                    errs = [m for m in msgs if m.startswith(("[pageerror]", "[console.error]"))
                            and "Failed to load resource" not in m]
                    if errs and time.time() - t0 > 30:
                        raise ToolError("viewer stuck on its loading screen after: "
                                        + errs[-1][:1500])
                    if time.time() - t0 > TIMEOUT:
                        raise ToolError(f"no drawing after {TIMEOUT} s")
                    time.sleep(1)
                last, stable = -1, 0
                while stable < 10:
                    time.sleep(0.5)
                    n = page.evaluate("document.querySelectorAll('svg *').length")
                    stable, last = (stable + 1, last) if n == last else (0, n)
                sel = page.evaluate("""() => { let best = null, n = -1;
                    for (const s of document.querySelectorAll('svg')) {
                      const k = s.querySelectorAll('*').length; if (k > n) { n = k; best = s; } }
                    best.id = best.id || 'x3-netlist'; return '#' + best.id; }""")
            else:
                page.wait_for_function("window.__done || window.__error", timeout=TIMEOUT * 1000)
                err = page.evaluate("window.__error")
                if err:
                    raise ToolError(err)
                sel = SELECTORS[fit]
            svg = page.evaluate(FIT_JS, sel)
            o.with_suffix(".svg").write_text(svg)
        finally:
            with log.open("a") as fh:
                fh.write("\n".join(msgs[-200:]) + "\n")
            page.close()

    def close(self):
        self.chromium.close()
        self.pw.stop()
        self.httpd.shutdown()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


# --------------------------------------------------------------------------- main


# Design sets. "top" is the first comparison; "module" draws one leaf module per SoC
# (designs_module.json, ours from ours_modules.py); "recompare" reruns "top" with each tool's own
# most-minimal option (TOOLS_MIN) and keeps the "top" drawing for a tool that has none.
SETS = {
    "top": dict(designs="designs.json", out="out", logs="logs", results="results.json",
                ours=X2),
    "module": dict(designs="designs_module.json", out="out_module", logs="logs_module",
                   results="results_module.json", ours=OUT / "ours_modules"),
    "recompare": dict(designs="designs.json", out="out_recompare", logs="logs_recompare",
                      results="results_recompare.json", ours=X2),
}


def ours(d: dict, meta: dict, cfg: dict) -> list[dict]:
    rows = []
    src_dir = cfg["ours"]
    res = {(r["input"], r["engine"]): r
           for r in json.loads((src_dir / "results.json").read_text())}
    for o in meta["ours"]:
        src = src_dir / "svg" / d["x2"] / f"{o['engine']}.svg"
        dst = OUT / cfg["out"] / d["name"] / f"{o['id']}.svg"
        r = res.get((d["x2"], o["engine"]), {})
        row = dict(design=d["name"], tool=o["id"], seconds=r.get("seconds"), x2=r)
        if src.exists() and r.get("status") == "ok":
            shutil.copy2(src, dst)
            row.update(status="ok", svg=url(dst))
        else:
            row.update(status="failed", error=r.get("error", "no drawing"))
        rows.append(row)
    return rows


def run_tool(tool: str, d: dict, o: Path, log: Path, browser, table: dict) -> None:
    if tool in BROWSER_TOOLS:
        table[tool](d, o, log, browser)
    else:
        table[tool](d, o, log)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="top", choices=list(SETS))
    ap.add_argument("--only", help="comma-separated tool ids")
    ap.add_argument("--designs", help="comma-separated design names")
    ap.add_argument("--skip-done", action="store_true",
                    help="keep (design, tool) rows already drawn in this set's results; "
                         "use it to continue an interrupted run")
    args = ap.parse_args()
    cfg = SETS[args.set]
    meta = json.loads((HERE / "tools.json").read_text())
    designs = json.loads((HERE / cfg["designs"]).read_text())["designs"]
    if args.designs:
        designs = [d for d in designs if d["name"] in args.designs.split(",")]
    tools = args.only.split(",") if args.only else list(TOOLS)
    res_path = OUT / cfg["results"]
    old = json.loads(res_path.read_text()) if res_path.exists() else []
    done = {(r["design"], r["tool"]) for r in old if r.get("status") == "ok"
            and (ROOT / r.get("svg", "/missing").lstrip("/")).exists()} if args.skip_done else set()
    recompare = args.set == "recompare"
    if recompare:  # tools without an option of their own keep their "top" drawing
        top_rows = {(r["design"], r["tool"]): r
                    for r in json.loads((OUT / SETS["top"]["results"]).read_text())}
    live = [t for t in tools if not recompare or t in TOOLS_MIN]
    browser = Browser() if BROWSER_TOOLS & set(live) else None
    rows = []
    try:
        for d in map(prepare, designs):
            od = OUT / cfg["out"] / d["name"]
            (OUT / cfg["logs"]).mkdir(parents=True, exist_ok=True)
            od.mkdir(parents=True, exist_ok=True)
            rows += ours(d, meta, cfg)
            for tool in tools:
                if (d["name"], tool) in done:
                    print(f"{d['name']:13} {tool:18} kept (--skip-done)", flush=True)
                    continue
                o = od / tool
                log = OUT / cfg["logs"] / f"{d['name']}.{tool}.log"
                log.write_text("")
                for f in od.glob(f"{tool}.*"):
                    f.unlink()
                t0 = time.time()
                row = dict(design=d["name"], tool=tool)
                if recompare and tool not in TOOLS_MIN:
                    prev = top_rows.get((d["name"], tool), {})
                    row.update({k: v for k, v in prev.items() if k not in ("svg", "log")},
                               unchanged=True)
                    if prev.get("svg"):
                        shutil.copy2(ROOT / prev["svg"].lstrip("/"), o.with_suffix(".svg"))
                        row["svg"] = url(o.with_suffix(".svg"))
                    log.write_text("no simplification option of its own; drawing kept from "
                                   "the top-level comparison\n")
                    row["log"] = url(log)
                    rows.append(row)
                    save(res_path, old, rows)
                    continue
                table = TOOLS_MIN if recompare else TOOLS
                if args.set == "module" and tool in MODULE_MIN:
                    table = MODULE_MIN
                row["mode"] = "default" if table is TOOLS else "minimal"
                try:
                    run_tool(tool, d, o, log, browser, table)
                    row.update(status="ok", svg=url(o.with_suffix(".svg")))
                except Exception as e:  # noqa: BLE001 - every failure is a result to report
                    msg = str(e) if isinstance(e, ToolError) else traceback.format_exc()
                    row.update(status="failed", error=msg[-2000:])
                row.update(seconds=round(time.time() - t0, 1), log=url(log))
                print(f"{d['name']:13} {tool:18} {row['status']:6} {row['seconds']}s",
                      flush=True)
                rows.append(row)
                save(res_path, old, rows)
    finally:
        if browser:
            browser.close()
        save(res_path, old, rows)


def save(res_path: Path, old: list[dict], rows: list[dict]) -> None:
    """Rows from this run replace the same (design, tool) rows of earlier runs."""
    new = {(r["design"], r["tool"]) for r in rows}
    keep = [r for r in old if (r["design"], r["tool"]) not in new]
    res_path.write_text(json.dumps(keep + rows, indent=1))


if __name__ == "__main__":
    main()
