"""x5 in one command.

    python x5.py doctor
        Check that every tool the method rests on is there, in the version it was validated with.

    python x5.py selftest [WORK]
        Small designs with known answers. Every expectation must hold before results count.

    python x5.py design --files a.v b.v --top TOP --observe state [options] --out OUT
        Prove the state graph of one register (or several signals together) of your own design, check
        it, attack the checker, audit everything, and write the page OUT/page/proof.html.
        options: --aux SIG ...        more signals observed while proving, dropped from the result
                 --reset PORT --active-low | --active-high
                 --include DIR ...  --define NAME ...  --scope INST ...  --budget SECONDS
                 --attack N         cases per attack kind (default 6; 0 skips the attack)

    python x5.py batch REPO MANIFEST.json X4_DESIGNS OUT --proposals P.json [--gallery DIR] [--jobs N]
        The whole corpus: prove, post-process, audit, page.

Each step runs only if the one before it succeeded, and the page is written only from a clean
audit: a result that was not verified to the end is never shown as one that was.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
VALIDATED = {"yosys": "0.33", "iverilog": "12.0", "z3": "5.4.1", "graphviz": "2.43"}


def say(msg):
    print(msg, flush=True)


def step(name, cmd, cwd=None, ok_codes=(0,)):
    say(f"\n== {name}\n   {' '.join(str(c) for c in cmd)}")
    t0 = time.time()
    rc = subprocess.call([str(c) for c in cmd], cwd=cwd)
    say(f"   -> exit {rc}, {time.time() - t0:.0f} s")
    if rc not in ok_codes:
        say(f"\nSTOPPED at '{name}'. Nothing after it ran; no result of this run counts.")
        sys.exit(rc or 1)


def doctor():
    rows, bad = [], False

    def ver(cmd, pat):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            m = re.search(pat, out.stdout + out.stderr)
            return m.group(1) if m else "?"
        except (OSError, subprocess.TimeoutExpired):
            return None

    checks = [("yosys", ["yosys", "-V"], r"Yosys (\d+\.\d+)"), ("yosys-abc", ["yosys-abc", "-c", "quit"], r"(UC Berkeley|ABC)"),
              ("iverilog", ["iverilog", "-V"], r"version (\d+\.\d+)"), ("vvp", ["vvp", "-V"], r"version (\d+\.\d+)"),
              ("graphviz", ["dot", "-V"], r"version (\d+\.\d+)")]
    for name, cmd, pat in checks:
        v = ver(cmd, pat)
        rows.append((name, v or "MISSING", VALIDATED.get(name, "")))
        bad |= v is None
    try:
        import z3  # noqa: PLC0415
        rows.append(("z3 (python)", z3.get_version_string(), VALIDATED["z3"]))
    except ImportError:
        rows.append(("z3 (python)", "MISSING", VALIDATED["z3"]))
        bad = True
    say(f"{'tool':14s} {'found':12s} validated with")
    for n, v, w in rows:
        say(f"{n:14s} {v:12s} {w}")
    if bad:
        say("\nSomething is missing. Run install.sh, or see README.md, Tools.")
        return 1
    if any(w and v not in ("MISSING", "?") and not v.startswith(w.split(".")[0]) for n, v, w in rows):
        say("\nA major version differs from the one the method was validated with; run `x5.py selftest` before trusting results.")
    say("\nAll tools found.")
    return 0


def arg_list(argv, key):
    if key not in argv:
        return []
    i, out = argv.index(key) + 1, []
    while i < len(argv) and not argv[i].startswith("--"):
        out.append(argv[i])
        i += 1
    return out


def arg_one(argv, key, default=None):
    v = arg_list(argv, key)
    return v[0] if v else default


def design(argv):
    files = [str(Path(f).resolve()) for f in arg_list(argv, "--files")]
    top, observe, out = arg_one(argv, "--top"), arg_list(argv, "--observe"), arg_one(argv, "--out")
    if not files or not top or not observe or not out:
        say(__doc__)
        return 2
    for f in files:
        if not Path(f).exists():
            say(f"no such file: {f}")
            return 2
    out = Path(out).resolve()
    if out.exists() and any(out.iterdir()):
        say(f"{out} is not empty. Results always go to a fresh folder, so old ones cannot mix in; pick another name.")
        return 2
    inp = out / "_input"
    inp.mkdir(parents=True)
    root = Path(os.path.commonpath([str(Path(f).parent) for f in files]))
    name = top
    manifest = [{"name": name, "files": [os.path.relpath(f, root) for f in files], "top": top,
                 "include_dirs": [os.path.relpath(str(Path(d).resolve()), root) for d in arg_list(argv, "--include")],
                 "defines": arg_list(argv, "--define"), "tb": None}]
    prop = {"id": top + "." + "+".join(observe), "observe": observe, "scope": arg_list(argv, "--scope"), "source": "given"}
    if arg_list(argv, "--aux"):
        prop["options"] = {"aux": arg_list(argv, "--aux")}
    if arg_one(argv, "--reset"):
        prop["reset"] = {"port": arg_one(argv, "--reset"), "active_low": "--active-low" in argv, "how": "given on the command line"}
    (inp / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (inp / "proposals.json").write_text(json.dumps({name: [prop]}, indent=1))
    (inp / "x4").mkdir()
    attack = arg_one(argv, "--attack", "6")
    step("prove", [PY, HERE / "run.py", root, inp / "manifest.json", inp / "x4", out / "certs", "--proposals", inp / "proposals.json",
                   "--jobs", "1", "--budget", arg_one(argv, "--budget", "420")])
    rows = json.loads((out / "certs" / "summary.json").read_text())
    if not rows or rows[0].get("status") in (None, "refused", "error"):
        say("\nNo certificate: " + json.dumps(rows[0] if rows else {}, ensure_ascii=False)[:600])
        return 1
    post = [PY, HERE / "post.py", out / "certs", "--jobs", "1"]
    post += ["--attack", attack, "--attack-heavy", "2", "--heavy-seconds", "90"] if attack != "0" else []
    step("check, names, labels, drawing, attack", post)
    step("audit", [PY, HERE / "audit.py", out / "certs"])
    (out / "page").mkdir()
    step("page", [PY, HERE / "make_proof.py", out / "certs", out / "page"])
    say(f"\nDone. Open {out / 'page' / 'proof.html'}")
    return 0


def batch(argv):
    if len(argv) < 4:
        say(__doc__)
        return 2
    repo, man, x4, out = argv[:4]
    jobs = arg_one(argv, "--jobs", "6")
    cmd = [PY, HERE / "run.py", repo, man, x4, out, "--jobs", jobs, "--budget", arg_one(argv, "--budget", "420")]
    if arg_one(argv, "--proposals"):
        cmd += ["--proposals", arg_one(argv, "--proposals")]
    step("selftest", [PY, HERE / "selftest.py", Path(out).resolve().parent / (Path(out).name + "_selftest")])
    step("prove", cmd)
    step("check, names, labels, drawing, attack", [PY, HERE / "post.py", out, "--jobs", "3", "--attack", "6", "--attack-heavy", "2", "--heavy-seconds", "90"])
    step("audit", [PY, HERE / "audit.py", out])
    if arg_one(argv, "--gallery"):
        step("page", [PY, HERE / "make_proof.py", out, arg_one(argv, "--gallery")])
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        say(__doc__)
        return 0
    cmd = argv[1]
    if cmd == "doctor":
        return doctor()
    if cmd == "selftest":
        work = Path(argv[2] if len(argv) > 2 else "x5_selftest").resolve()
        if work.exists():
            shutil.rmtree(work)
        return subprocess.call([PY, str(HERE / "selftest.py"), str(work)])
    if cmd == "design":
        return design(argv[2:])
    if cmd == "batch":
        return batch(argv[2:])
    say(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
