"""Exercise every tool without the API: python test_tools.py. Prints one line per call."""
import json
import sys
import time
import traceback

import agent as A

CASES = [
    ("list_designs", {}),
    ("analyze_design", {"design": "picorv32_spimemio"}),
    ("read_source", {"design": "picorv32_spimemio", "file": "spimemio.v", "grep": "state"}),
    ("read_source", {"design": "picorv32_spimemio", "file": "spimemio.v", "start": 205, "end": 240}),
    ("draw_block", {"design": "picorv32_picosoc", "view": "paper"}),
    ("draw_block", {"design": "picorv32_picosoc", "view": "system"}),
    ("draw_fsm", {"design": "picorv32_spimemio", "signal": "state"}),
    ("draw_fsm", {"design": "picorv32_picosoc", "signal": "cpu_state", "scope": ["cpu"]}),
    ("draw_timing", {"design": "verilog-uart_uart_rx"}),
    ("draw_timing", {"design": "picorv32_spimemio", "interface": "valid"}),
    ("analyze_design", {"design": "nonexistent"}),
]
only = sys.argv[1:] or None
bad = 0
for name, args in CASES:
    if only and name not in only:
        continue
    t0 = time.time()
    try:
        out, arts = A.call_tool(name, args, "test")
        print("ok  ", name, json.dumps(args, ensure_ascii=False), f"{time.time() - t0:.1f}s |", A._brief(name, out)[:220], "|", [a["file"] for a in arts])
    except A.B.ToolError as ex:
        print("TOOL", name, json.dumps(args, ensure_ascii=False), "|", str(ex)[:220])
    except Exception:  # noqa: BLE001
        bad += 1
        print("FAIL", name, json.dumps(args, ensure_ascii=False))
        traceback.print_exc()
sys.exit(1 if bad else 0)
