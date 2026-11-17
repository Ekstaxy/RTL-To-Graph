"""Bundle the results the demo reads for the 30 corpus designs into demo_cache.zip, so it runs on a
machine without the pipelines: python make_cache.py CONFIG.json OUT.zip (paths as in config.json).

  x4/<design>/      result.json, signals.json, fsm/*.json, timing/*.svg and *.json   (L1 + x4)
  block/<design>/   block.json, e3.*.svg, x1.system.svg                               (x1 + x2 + e3)
  x5/               audit.json and per graph cert.json, check.json, names.json, graph.svg
  all30.json        the corpus manifest; the RTL itself is in the repository
Local paths inside text files are replaced; nothing else is changed.
"""
import json
import os
import re
import sys
import zipfile
from pathlib import Path

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
X = lambda p: Path(os.path.expanduser(p))  # noqa: E731
x4, blk, x5 = X(cfg["cache"]["x4"]), X(cfg["cache"]["block"]), X(cfg["cache"]["x5"])
man = X(cfg["corpus_manifest"])
SUBS = [(re.compile(rb"/home/[^/]+/"), b"~/"), (re.compile(rb"/mnt/c/Users/[^/]+/Downloads/RTL_/"), b"RTL_/"),
        (re.compile(rb"C:\\\\Users\\\\[^\\\\]+\\\\"), b"~\\\\"), (re.compile(rb"C:\\Users\\[^\\]+\\"), b"~\\")]
TEXT = {".json", ".svg", ".txt"}
n = 0


def put(z, src, arc):
    global n
    data = Path(src).read_bytes()
    if Path(src).suffix in TEXT:
        for rx, to in SUBS:
            data = rx.sub(lambda _m, to=to: to, data)
    z.writestr(arc, data)
    n += 1


with zipfile.ZipFile(sys.argv[2], "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    put(z, man, "all30.json")
    for e in json.loads(man.read_text()):
        d = e["name"]
        p = x4 / d
        for f in ("result.json", "signals.json"):
            if (p / f).exists():
                put(z, p / f, f"x4/{d}/{f}")
        for f in sorted((p / "fsm").glob("*.json")):
            put(z, f, f"x4/{d}/fsm/{f.name}")
        for f in sorted((p / "timing").glob("*")):
            if f.suffix in (".svg", ".json") and not f.name.endswith(".wavedrom.json"):
                put(z, f, f"x4/{d}/timing/{f.name}")
        b = blk / d
        for f in [b / "block.json", b / "x1.system.svg"] + sorted(b.glob("e3.*.svg")):
            if f.exists():
                put(z, f, f"block/{d}/{f.name}")
    put(z, x5 / "audit.json", "x5/audit.json")
    for c in sorted(x5.glob("*/*/cert.json")):
        for f in ("cert.json", "check.json", "names.json", "graph.svg"):
            if (c.parent / f).exists():
                put(z, c.parent / f, f"x5/{c.parent.parent.name}/{c.parent.name}/{f}")
    z.writestr("README.txt", "Results for the 30 corpus designs, bundled for the agent demo.\n"
               "x5: certificates of the audited run out17 (code src26, audit clean, 23 graphs x 10 verifications).\n"
               "Local paths in text files were replaced by ~/ or RTL_/.\n")
print(n, "files", round(Path(sys.argv[2]).stat().st_size / 2**20, 1), "MB")
