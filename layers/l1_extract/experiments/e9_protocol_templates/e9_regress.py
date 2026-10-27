"""e9 regression cases: tiny inline RTL designs with the expected interface set.

    uv run --package rtl2d-l1 python \
        layers/l1_extract/experiments/e9_protocol_templates/e9_regress.py [--out DIR]

Writes each design to DIR/rtl/<case>.v (default DIR = runs/e9_protocol_templates/_regress),
runs annotate_design + select() and checks `{iface id: (protocol, confirmed, sorted roles)}`
plus a few extra predicates. Prints one PASS/FAIL line per case; exit code 1 on any FAIL.
Cases come from the e9 review (chain: output data loaded under the input handshake; timer:
registered status pulse next to a counter must not be SERIAL; loop index not a lane).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]

CASES: dict[str, str] = {
    "chain": """
module chain (input wire clk, input wire rst, input wire in_valid, output wire in_ready,
  input wire [7:0] in_data, output wire out_valid, input wire out_ready,
  output wire [7:0] out_data);
  reg v_q; reg [7:0] d_q; wire a1, a2;
  assign a1 = v_q; assign a2 = a1; assign out_valid = a2; assign out_data = d_q;
  assign in_ready = !v_q || out_ready;
  always @(posedge clk) begin
    if (rst) v_q <= 1'b0; else if (in_ready) v_q <= in_valid;
    if (in_valid && in_ready) d_q <= in_data;
  end
endmodule
""",
    "timer": """
module timer (input wire clk, input wire rst, input wire start, input wire mode,
  output reg expired, output wire [7:0] count);
  reg run_q; reg [7:0] cnt;
  assign count = cnt;
  always @(posedge clk) begin
    if (rst) begin run_q <= 1'b0; cnt <= 8'd0; expired <= 1'b0; end
    else begin
      if (start) run_q <= 1'b1; else if (cnt == 8'hff) run_q <= 1'b0;
      if (run_q) cnt <= cnt + (mode ? 8'd2 : 8'd1);
      expired <= run_q && (cnt == 8'hff);
    end
  end
endmodule
""",
    "ser_shift": """
module ser_shift (input wire clk, input wire rst_n, input wire load, input wire [7:0] din,
  output wire sout);
  reg [7:0] sh; reg [2:0] n;
  assign sout = sh[0];
  always @(posedge clk or negedge rst_n)
    if (!rst_n) begin sh <= 0; n <= 0; end
    else if (load) begin sh <= din; n <= 0; end
    else if (n != 3'd7) begin sh <= {1'b0, sh[7:1]}; n <= n + 3'd1; end
endmodule
""",
    "ser_index": """
module ser_index (input wire clk, input wire rst, input wire [7:0] din, input wire load,
  output reg tx);
  reg [7:0] d; reg [2:0] idx;
  always @(posedge clk)
    if (rst) begin d <= 0; idx <= 0; tx <= 1'b1; end
    else begin
      if (load) begin d <= din; idx <= 0; end else idx <= idx + 3'd1;
      tx <= d[idx];
    end
endmodule
""",
    "loopidx": """
module loopidx (input wire clk, input wire in_valid, output wire in_ready,
  input wire [7:0] in_data, output reg [7:0] q);
  integer i;
  reg [7:0] r;
  assign in_ready = 1'b1;
  always @(posedge clk)
    if (in_valid && in_ready) for (i = 0; i < 8; i = i + 1) r[i] <= in_data[7 - i];
  always @(posedge clk) q <= r;
endmodule
""",
}

# expected {iface id: (protocol, confirmed, sorted roles)}; extra predicates below
EXPECT: dict[str, dict[str, tuple[str, bool, tuple[str, ...]]]] = {
    "chain": {"if.in": ("VALID_READY", True, ("data", "ready", "valid")),
              "if.out": ("VALID_READY", True, ("data", "ready", "valid"))},
    "timer": {},
    "ser_shift": {"if.sout": ("SERIAL", True, ("serial",))},
    "ser_index": {"if.tx": ("SERIAL", True, ("serial",))},
    "loopidx": {"if.in": ("VALID_READY", True, ("data", "ready", "valid"))},
}


def _extra(case: str, sig: dict) -> list[str]:
    errs = []
    if case == "loopidx" and any(x["signal"] == "i" for x in sig["internal"]):
        errs.append("loop index i listed as an internal lane")
    if case == "timer" and not any(d["signal"] == "expired" for d in sig["dropped"]):
        errs.append("expired not in dropped")
    return errs


def _load_select():
    spec = importlib.util.spec_from_file_location("e9_select", HERE / "e9_select.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["e9_select"] = mod
    spec.loader.exec_module(mod)
    return mod


def check(case: str, out: Path, e9) -> list[str]:
    from rtl2d_l1.pipeline import RunConfig, annotate_design

    f = out / "rtl" / f"{case}.v"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(CASES[case].lstrip(), encoding="utf-8")
    cfg = RunConfig(mode="heuristic", targets=frozenset({"block", "fsm", "timing"}))
    run = annotate_design([str(f)], top=case, cfg=cfg, name=case)
    sig = e9.select(run, design=case)
    got = {i["id"]: (i["protocol"], i["confirmed"], tuple(sorted(m["role"] for m in i["members"])))
           for i in sig["interfaces"]}
    errs = [] if got == EXPECT[case] else [f"interfaces {got} != expected {EXPECT[case]}"]
    return errs + _extra(case, sig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "runs" / "e9_protocol_templates" / "_regress"))
    a = ap.parse_args(argv)
    e9 = _load_select()
    bad = 0
    for case in CASES:
        errs = check(case, Path(a.out), e9)
        bad += bool(errs)
        print(f"{'PASS' if not errs else 'FAIL'} {case}" + "".join(f"\n    {e}" for e in errs))
    print(f"{len(CASES) - bad}/{len(CASES)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
