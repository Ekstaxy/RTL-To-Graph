"""The path a new design takes: python test_own.py DIR TOP STATE_SIGNAL. Runs every tool on it."""
import json
import sys
import time
import traceback

import agent as A

d = f"dir:{sys.argv[1]}#{sys.argv[2]}"
for name, args in (("analyze_design", {"design": d}), ("draw_block", {"design": d, "view": "paper"}),
                   ("draw_fsm", {"design": d, "signal": sys.argv[3]}), ("draw_timing", {"design": d})):
    t0 = time.time()
    try:
        out, arts = A.call_tool(name, args, "own")
        print("ok  ", name, f"{time.time() - t0:.1f}s |", A._brief(name, out)[:300], "|", [a["file"] for a in arts], flush=True)
        if name == "draw_fsm":
            print("     ", json.dumps(out.get("how")), json.dumps(out["summary"].get("checker")), flush=True)
    except A.B.ToolError as ex:
        print("TOOL", name, f"{time.time() - t0:.1f}s |", str(ex)[:400], flush=True)
    except Exception:  # noqa: BLE001
        print("FAIL", name, flush=True)
        traceback.print_exc()
