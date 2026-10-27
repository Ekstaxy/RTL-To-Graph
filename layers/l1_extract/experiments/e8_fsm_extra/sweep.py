"""e8 sweep: counter-candidate admissions over corpus manifests, literal plan rule vs R5.

    uv run --package rtl2d-l1 python layers/l1_extract/experiments/e8_fsm_extra/sweep.py \
        layers/l1_extract/examples/corpus.json layers/l1_extract/data/corpus/rtllm.json \
        layers/l1_extract/data/corpus/verilog_eval.json \
        layers/l1_extract/data/corpus/picorv32.json \
        layers/l1_extract/data/corpus/opensource.json \
        [--out runs/e8_fsm_extra/sweep] [--skip NAME ...] [--timeout 180]

The manifest RTL paths are relative to the manifest's directory, except `data/corpus/*.json`
whose paths are remapped `data/corpus -> data/rtl` (plan §1). Per design: elaborate, graph,
entity tables; the skip set is the syntactic FSM candidates (fsm_candidate rows, as e4's sweep);
then `candidates.evaluate` over every `x <= x + k` register. Today's L1 rule admits none of
them (candidate_registers drops arith self-sources), so every admission is a *new* FSM; the
script lists them for labelling and prints the counts for both rules. Writes
`<out>/sweep.json` (one row per candidate register) and prints a summary.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import signal
import sys
import time
from pathlib import Path

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def _sib(name: str):
    key = f"e8_fsm_extra_{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


candidates = _sib("candidates")


class _Timeout(Exception):
    pass


def _alarm(_sig, _frm):
    raise _Timeout


def base_dir(manifest: Path) -> Path:
    """Directory the manifest's RTL paths are relative to (data/corpus -> data/rtl)."""
    if manifest.parent.name == "corpus" and manifest.parent.parent.name == "data":
        return manifest.parent.parent / "rtl"
    return manifest.parent


def syntactic_keys(T) -> set[str]:
    return {
        k
        for t in T
        for r in t.rows
        if r.fsm_candidate
        for k in ([*r.members] if r.members else [f"{t.canonical_instance}.{r.name}"])
    }


def one(item: dict, base: Path, timeout: int) -> tuple[list[dict], str | None]:
    """Decision rows for one corpus entry (or an error text)."""
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout)
    try:
        d = elaborate([str(base / f) for f in item["files"]], top=item.get("top"),
                      include_dirs=[str(base / i) for i in item.get("include_dirs", [])],
                      defines=item.get("defines", []))
        G = build_graph(d)
        rows = candidates.evaluate(d, G, syntactic_keys(build_entity_tables(G)))
        return [{k: v for k, v in r.items() if k != "r"} for r in rows], None
    except _Timeout:
        return [], f"timeout {timeout}s"
    except Exception as ex:  # a frontend failure is reported, not fatal for the sweep
        return [], f"{type(ex).__name__}: {str(ex)[:120]}"
    finally:
        signal.alarm(0)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("manifests", nargs="+")
    ap.add_argument("--out", default=str(ROOT / "runs" / "e8_fsm_extra" / "sweep"))
    ap.add_argument("--skip", nargs="*", default=[], help="corpus entry names to skip")
    ap.add_argument("--timeout", type=int, default=180, help="seconds per design")
    a = ap.parse_args(argv)
    out, rows, errors, n = Path(a.out), [], [], 0
    t0 = time.time()
    for m in map(Path, a.manifests):
        base = base_dir(m)
        for it in json.loads(m.read_text(encoding="utf-8")):
            if it["name"] in a.skip:
                errors.append({"design": it["name"], "error": "skipped (--skip)"})
                continue
            n += 1
            t1 = time.time()
            got, err = one(it, base, a.timeout)
            if err:
                errors.append({"design": it["name"], "error": err})
            for r in got:
                rows.append({"design": it["name"], **r})
                tag = "R5" if r["admitted"] else "  "
                tag += " LIT" if r.get("literal") else "    "
                if r["admitted"] or r.get("literal"):
                    print(f"  {tag} {it['name']}: {r['key']} w={r['width']} "
                          f"n={r.get('n_states')} {r['reason']}", flush=True)
            print(f"  . {it['name']} {len(got)} candidate(s) {time.time() - t1:.1f}s"
                  + (f" ERROR {err}" if err else ""), flush=True)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sweep.json").write_text(json.dumps({"rows": rows, "errors": errors}, indent=1,
                                               default=str), encoding="utf-8")
    r5 = [r for r in rows if r["admitted"]]
    lit = [r for r in rows if r.get("literal")]
    print(f"designs {n}, errors {len(errors)}, candidate registers {len(rows)}, "
          f"admitted: R5 {len(r5)}, literal rule {len(lit)}, today's L1 rule 0 "
          f"({time.time() - t0:.0f}s) -> {out / 'sweep.json'}")
    for e in errors:
        print(f"  error {e['design']}: {e['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
