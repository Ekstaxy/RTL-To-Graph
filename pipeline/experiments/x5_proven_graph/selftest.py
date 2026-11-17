"""x5 self-test on designs small enough to know the answer by reading them.

    python selftest.py WORK

Each case states what the certificate must say and what the independent checker must do with it.
Exit status 0 only if every expectation holds.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check as C  # noqa: E402
import prove as P  # noqa: E402

T1 = """
module t1(input clk, input rst, input go, output reg [1:0] st, output reg [2:0] cnt);
  // st 0 idle, 1 counting 6..1, 2 done. st never becomes 3, so cnt never wraps from 0 to 7.
  // Seen through cnt alone, a state with st = 3 walks 4,3,2,1,0 like a real one and then leaves
  // the graph, which is more steps than the induction looks back.
  always @(posedge clk)
    if (rst) begin st <= 0; cnt <= 0; end
    else case (st)
      0: if (go) begin st <= 1; cnt <= 6; end
      1: begin cnt <= cnt - 1; if (cnt == 1) st <= 2; end
      2: st <= 0;
      3: cnt <= cnt - 1;
    endcase
endmodule
"""
T2 = """
module t2(input clk, input a, input b, output reg s);
  reg armed = 1'b0;  // an RTL initial value, no reset, only ever cleared: s can never become 1
  initial s = 1'b0;
  always @(posedge clk) begin
    armed <= armed & b;
    s <= a && armed;
  end
endmodule
"""
T3 = """
module t3(input clk, input rst, input go, output reg [1:0] s);
  always @(posedge clk)
    if (rst) s <= 0;
    else
`ifdef __ICARUS__
      s <= s;             // the simulator's own macro: this branch is not the synthesized design
`else
      s <= go ? s + 2'd1 : s;
`endif
endmodule
"""
T5 = """
module t5(input clk, input rst, input [1:0] ra, output reg hit);
  reg [3:0] mem [0:3];  // never written: what it holds is whatever it powered up with
  always @(posedge clk)
    if (rst) hit <= 1'b0; else hit <= (mem[ra] == 4'd9);
endmodule
"""

T6_SUB = """
`ifndef MODE_B
  this file is only valid after the top file has defined MODE_B ;
`endif
module t6_sub(input clk, input rst, input go, output reg [1:0] s);
  always @(posedge clk)
    if (rst) s <= 0;
    else if (go) s <= s + 2'd1;
endmodule
"""
T6_TOP = """
`define MODE_B
module t6(input clk, input rst, input go, output [1:0] s);
  t6_sub u (.clk(clk), .rst(rst), .go(go), .s(s));
endmodule
"""

T8 = """
module t8(input clk, input rst, input go, output reg [1:0] st);
  // u keeps its power-up value forever. u ^ u is 0 in every circuit, but a simulator that computes
  // with x sees x ^ x = x, takes the else branch, and shows 0 -> 1, which no hardware can do.
  reg u;
  always @(posedge clk) u <= u;
  always @(posedge clk)
    if (rst) st <= 0;
    else if (st == 0 && go) begin if ((u ^ u) == 1'b0) st <= 2; else st <= 1; end
    else st <= 0;
endmodule
"""
T9 = """
module t9(input clk, input rst, input go, output reg [1:0] st);
  // d is a don't-care every cycle. The model lets it be anything, so 0 -> 1 and 0 -> 2 are both
  // possible; the simulator takes it as 0 and can only show 0 -> 2.
  reg d;
  always @(posedge clk) d <= 1'bx;
  always @(posedge clk)
    if (rst) st <= 0;
    else if (st == 0 && go) st <= d ? 2'd1 : 2'd2;
    else st <= 0;
endmodule
"""
T10 = """
module t10_sub(input clk, output reg q, output reg r);
  always @(posedge clk) begin q <= q; r <= r; end  // keep their power-up values; the parent sees them only as wires
endmodule
module t10(input clk, input rst, input go, output reg [1:0] st);
  wire u;
  wire w;  // r drives nothing the observation needs: the model drops it, the simulator still has it
  t10_sub s(.clk(clk), .q(u), .r(w));
  always @(posedge clk)
    if (rst) st <= 0;
    else if (st == 0 && go) begin if ((u ^ u) == 1'b0) st <= 2; else st <= 1; end
    else st <= 0;
endmodule
"""
T7 = """
module t7(input clk, input rst, input soft_rst, input go, output reg s);
  // two inputs look like a reset; only rst is the reset, soft_rst is a functional input
  always @(posedge clk)
    if (rst) s <= 0;
    else if (soft_rst) s <= 0;
    else if (go) s <= 1;
endmodule
"""

results = []


def expect(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("ok    " if cond else "FAIL  ") + name + (("   " + str(detail)) if detail and not cond else ""), flush=True)


def build(work, name, text):
    d = Path(work) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / (name + ".v")).write_text(text)
    return {"design": name, "top": name, "files": [str(d / (name + ".v"))], "include_dirs": [], "defines": []}


def tally(cert):
    t = {}
    for e in cert["edges"]:
        t[e["status"]] = t.get(e["status"], 0) + 1
    return t


def main(work):
    work = Path(work).resolve()
    kw = dict(budget=90, sim_runs=8, sim_cycles=400, windows=(16,))

    # 1. A counter observed alone leaves edges open; observed with its state machine it is exact.
    s1 = build(work, "t1", T1)
    a = P.prove(s1, ["cnt"], work / "t1" / "alone", pdr=False, **kw)
    a2 = P.prove(s1, ["cnt"], work / "t1" / "alone_pdr", **kw)
    b = P.prove(s1, ["cnt"], work / "t1" / "aux", aux=["st"], **kw)
    pairs = lambda c: sorted((e["src"], e["dst"]) for e in c["edges"])  # noqa: E731
    real = [(0, 0), (0, 6), (1, 0), (2, 1), (3, 2), (4, 3), (5, 4), (6, 5)]
    und = sorted((e["src"], e["dst"]) for e in a["edges"] if e["status"] == "undetermined")
    expect("t1 alone, without PDR: complete, the eight real transitions witnessed, the wrap 0->7 left undetermined",
           a["completeness"]["status"] == "proven" and (0, 7) in und and set(und) <= {(0, 7), (7, 6), (7, 7)} and tally(a).get("witnessed") == 8,
           (pairs(a), tally(a)))
    inv = a2["completeness"].get("invariant") or {}
    expect("t1 alone, with PDR: exactly the eight real transitions, the rest proven impossible, invariant carried",
           pairs(a2) == real and tally(a2) == {"witnessed": 8} and len(inv.get("blocked", [])) > 0 and (0, 7) in {tuple(x) for x in inv.get("removed_edges", [])},
           (pairs(a2), tally(a2), a2["completeness"].get("pdr")))
    c2 = C.check(s1, a2, work / "t1" / "chk_pdr")
    expect("t1 alone, with PDR: independent checker accepts, induction with the invariant", c2["ok"] and "invariant" in c2["completeness"].get("engine", ""), c2)
    if inv.get("blocked"):
        m = copy.deepcopy(a2)
        m["completeness"]["invariant"]["blocked"] = []
        # with the invariant one induction step is enough; without it, two are not
        expect("t1 alone, with PDR: at induction length 2 the invariant is what makes the proof go through",
               C.check(s1, a2, work / "t1" / "chk_pdr_a1", maxsteps=2)["ok"] and not C.check(s1, m, work / "t1" / "chk_pdr_a", maxsteps=2)["ok"])
        m = copy.deepcopy(a2)
        m["edges"] = [e for e in m["edges"] if (e["src"], e["dst"]) != (3, 2)]
        expect("t1 alone, with PDR: a real edge removed, invariant kept: rejected", not C.check(s1, m, work / "t1" / "chk_pdr_b")["ok"])
        m = copy.deepcopy(a2)
        m["completeness"]["invariant"]["blocked"].append([])  # the empty cube matches every state: a false invariant
        r = C.check(s1, m, work / "t1" / "chk_pdr_c")
        expect("t1 alone, with PDR: a false invariant makes the proof fail, it never passes", not r["ok"] and r["completeness"]["result"] == "failed", r["completeness"])
    expect("t1 with st: exactly the eight real transitions, all witnessed", pairs(b) == real and tally(b) == {"witnessed": 8}, (pairs(b), tally(b)))
    expect("t1 with st: no trace needs a power-up state", not any(e.get("needs_power_up") for e in b["edges"]))
    cb = C.check(s1, b, work / "t1" / "chk")
    expect("t1 with st: independent checker accepts", cb["ok"], cb)
    m = copy.deepcopy(b)
    m["completeness"]["support"]["pairs"] = [p for p in m["completeness"]["support"]["pairs"] if p[0] != p[1]][:-1]
    expect("t1: supporting set with a pair removed is rejected", not C.check(s1, m, work / "t1" / "chk_a")["ok"])
    m = copy.deepcopy(b)
    m["edges"] = [e for e in m["edges"] if (e["src"], e["dst"]) != (3, 2)]
    expect("t1: projected edge removed is rejected", not C.check(s1, m, work / "t1" / "chk_b")["ok"])
    # a real edge removed while its trace stays: the replayed trace takes an unlisted edge
    m = copy.deepcopy(a)
    m["edges"] = [e for e in m["edges"] if (e["src"], e["dst"]) != (2, 1)]
    r = C.check(s1, m, work / "t1" / "chk_f", skip_proof_when_witnesses_fail=True)
    expect("t1: edge removed, its trace kept: rejected by the replayed trace alone", not r["ok"] and r["witnesses"].get("replayed_pairs_not_listed"), r["witnesses"])
    # the same edge removed together with every trace through it: only the induction can catch it
    m = copy.deepcopy(a)
    R = m["assumptions"]["reset_cycles"]
    through = {i for i, tr in enumerate(m["traces"]) if any((tr["obs"][t], tr["obs"][t + 1]) == (2, 1) for t in range(R, len(tr["obs"]) - 1))}
    keep = [i for i in range(len(m["traces"])) if i not in through]
    m["traces"] = [a["traces"][i] for i in keep]
    rm = {o: k for k, o in enumerate(keep)}
    m["edges"] = [({"src": e["src"], "dst": e["dst"], "status": "undetermined"} if e.get("trace") in through else dict(e, trace=rm[e["trace"]]) if "trace" in e else e)
                  for e in a["edges"] if (e["src"], e["dst"]) != (2, 1)]
    r = C.check(s1, m, work / "t1" / "chk_g")
    expect("t1: edge removed with every trace through it: witnesses pass, the induction rejects",
           not r["ok"] and r["witnesses"]["result"] == "ok" and r["completeness"]["result"] == "failed", (r["witnesses"]["result"], r["completeness"]))
    expect("t1: that lie is refuted by a concrete counterexample the simulator replays, taking 2->1",
           (r["completeness"].get("refutation") or {}).get("result") == "refuted" and r["completeness"]["refutation"].get("pair") == [2, 1],
           r["completeness"].get("refutation"))
    ca = C.check(s1, a, work / "t1" / "chk_alone")
    expect("t1 alone: independent checker accepts the looser certificate too", ca["ok"], ca)
    m = copy.deepcopy(b)
    m["traces"][m["edges"][1]["trace"]]["inputs"]["rst"][-1] = 1
    expect("t1: trace that pulls reset again is rejected", not C.check(s1, m, work / "t1" / "chk_c")["ok"])
    m = copy.deepcopy(b)
    del m["traces"][m["edges"][1]["trace"]]["inputs"]["go"]
    expect("t1: trace with an input left out is rejected", not C.check(s1, m, work / "t1" / "chk_d")["ok"])

    # 2. A register with an RTL initial value is not free at power-up.
    s2 = build(work, "t2", T2)
    c = P.prove(s2, ["s"], work / "t2" / "p", **kw)
    st = {(e["src"], e["dst"]): e["status"] for e in c["edges"]}
    expect("t2: 0->0 witnessed, 0->1 not witnessed", st.get((0, 0)) == "witnessed" and st.get((0, 1), "absent") in ("undetermined", "absent"), st)
    expect("t2: independent checker accepts the honest certificate", C.check(s2, c, work / "t2" / "chk")["ok"])
    m = copy.deepcopy(c)
    m["traces"].append({"obs": [0, 1], "inputs": {"a": [1, 1], "b": [1, 1]}, "init_regs": {"armed": 1}, "init_mems": {}})
    m["widths"]["regs"]["armed"] = 1
    m["edges"] = [e for e in m["edges"] if (e["src"], e["dst"]) != (0, 1)]
    m["edges"].append({"src": 0, "dst": 1, "status": "witnessed", "trace": len(m["traces"]) - 1, "step": 0, "replay": True, "needs_power_up": True})
    if 1 not in {x["value"] for x in m["states"]}:
        m["states"].append({"value": 1, "status": "witnessed", "entry": False})
    r = C.check(s2, m, work / "t2" / "chk_forged")
    expect("t2: forged trace that overrides the RTL initial value is rejected", not r["ok"] and [0, 1] in r["witnesses"]["unconfirmed"], r["witnesses"])

    # 3. The simulator must run the synthesized configuration.
    s3 = build(work, "t3", T3)
    c = P.prove(s3, ["s"], work / "t3" / "p", **kw)
    expect("t3: eight transitions, all witnessed, none model-only", tally(c) == {"witnessed": 8}, tally(c))
    expect("t3: independent checker accepts", C.check(s3, c, work / "t3" / "chk")["ok"])

    # 5. A transition that depends on what a memory powered up with.
    s5 = build(work, "t5", T5)
    c = P.prove(s5, ["hit"], work / "t5" / "p", **kw)
    e01 = next((e for e in c["edges"] if (e["src"], e["dst"]) == (0, 1)), {})
    expect("t5: 0->1 witnessed and marked as needing a power-up state", e01.get("status") == "witnessed" and e01.get("needs_power_up") is True, e01)
    expect("t5: the trace carries the memory contents", bool(e01) and bool(c["traces"][e01["trace"]].get("init_mems")), c["widths"].get("mems"))
    expect("t5: independent checker accepts", C.check(s5, c, work / "t5" / "chk")["ok"])

    # 6. The order of the source files is part of the design; the simulator must use the model's order.
    d6 = work / "t6"
    d6.mkdir(parents=True, exist_ok=True)
    (d6 / "t6_sub.v").write_text(T6_SUB)
    (d6 / "t6.v").write_text(T6_TOP)
    s6 = {"design": "t6", "top": "t6", "files": [str(d6 / "t6_sub.v"), str(d6 / "t6.v")], "include_dirs": [], "defines": []}
    c = P.prove(s6, ["u.s"], d6 / "p", **kw)
    expect("t6: model built with the top file first, and the certificate says so", c["assumptions"].get("source_order") == "top module's file first",
           c["assumptions"].get("source_order"))
    expect("t6: eight transitions, all witnessed by the simulator", tally(c) == {"witnessed": 8}, tally(c))
    expect("t6: independent checker accepts", C.check(s6, c, d6 / "chk")["ok"])
    sd = c["replay"].get("same_design", {})
    expect("t6: every register of the model exists in the simulator", sd.get("unknown_to_simulator") == [] and sd.get("registers", 0) >= 1, sd)

    # 7. A reset chosen among several reset-like inputs: the others are listed as left free.
    s7 = dict(build(work, "t7", T7), reset={"port": "rst", "active_low": False, "how": "l1: name hint"})
    c = P.prove(s7, ["s"], work / "t7" / "p", **kw)
    expect("t7: the other reset-like input is listed as left free", c["assumptions"].get("reset_like_inputs_left_free") == ["soft_rst"],
           c["assumptions"].get("reset_like_inputs_left_free"))
    s7b = dict(build(work, "t7b", T7.replace("module t7", "module t7b")), top="t7b")
    c = P.prove(s7b, ["s"], work / "t7b" / "p", **kw)
    expect("t7: with no reset given, every reset-like input is held as a reset and none is left free",
           c["assumptions"].get("reset_like_inputs_left_free") == [] and len(c["assumptions"]["reset"]) == 2, c["assumptions"]["reset"])

    # 8. Unknown values: the simulator must not show a transition only its x rules produce.
    s8 = build(work, "t8", T8)
    c = P.prove(s8, ["st"], work / "t8" / "p", **kw)
    expect("t8: complete and not refuted: two-valued simulation agrees with the model", c["completeness"]["status"] == "proven"
           and not c["completeness"].get("conflicts"), c["completeness"])
    expect("t8: 0->2 witnessed, 0->1 absent", tally(c).get("witnessed", 0) >= 2 and (0, 1) not in pairs(c) and (0, 2) in pairs(c), pairs(c))
    r = C.check(s8, c, work / "t8" / "chk")
    expect("t8: independent checker accepts, replay is two-valued", r["ok"] and str(r["witnesses"].get("mode", "")).startswith("two-valued"), r["witnesses"])
    m = copy.deepcopy(c)
    e02 = next(e for e in m["edges"] if (e["src"], e["dst"]) == (0, 2))
    m["edges"].append(dict(e02, dst=1))
    m["states"] = m["states"] + [{"value": 1, "status": "witnessed", "entry": False}] if all(x["value"] != 1 for x in m["states"]) else m["states"]
    r = C.check(s8, m, work / "t8" / "chk_x", skip_proof_when_witnesses_fail=True)
    expect("t8: forged 0->1, which only x rules would show, is rejected", not r["ok"] and [0, 1] in r["witnesses"]["unconfirmed"], r["witnesses"])
    m = copy.deepcopy(c)
    m["widths"]["regs"] = {}
    r = C.check(s8, m, work / "t8" / "chk_w")
    expect("t8: a certificate that lists no registers still gets every register defined by the checker", r["ok"] and r["witnesses"]["state"]["registers"] >= 2, r["witnesses"])

    s9 = build(work, "t9", T9)
    c = P.prove(s9, ["st"], work / "t9" / "p", **kw)
    st9 = {(e["src"], e["dst"]): e["status"] for e in c["edges"]}
    expect("t9: an x written by the RTL: 0->2 witnessed, 0->1 only in the model, not proven absent, not drawn as fact",
           st9.get((0, 2)) == "witnessed" and st9.get((0, 1)) in ("undetermined", "model-witness") and c["completeness"]["status"] == "proven", st9)
    expect("t9: independent checker accepts", C.check(s9, c, work / "t9" / "chk")["ok"])

    # 10. The same through a submodule: the register is s.q, the parent only has the wire u. Filling
    # u is impossible (a wire); the register itself must be found and made defined.
    s10 = build(work, "t10", T10)
    c = P.prove(s10, ["st"], work / "t10" / "p", **kw)
    expect("t10: register behind a submodule port: complete, not refuted, 0->2 witnessed, 0->1 absent",
           c["completeness"]["status"] == "proven" and (0, 2) in pairs(c) and (0, 1) not in pairs(c) and tally(c).get("witnessed", 0) == len(c["edges"]),
           (c["completeness"].get("status"), pairs(c), tally(c)))
    r = C.check(s10, c, work / "t10" / "chk")
    expect("t10: independent checker accepts", r["ok"], r["witnesses"])
    m10 = P.Model(s10, work / "t10" / "model")
    expect("t10: the simulator's fill list has every register by its own hierarchical name, also one the model drops",
           {"s.q", "s.r", "st"} <= set(m10.fill_regs or {}) and "s.r" not in m10.regs, (sorted(m10.regs), sorted(m10.fill_regs or {})))

    # 9. The attack program end to end on a small certificate: it must finish, and every false
    # certificate must be turned down with a verdict.
    import attack as A
    d8 = work / "t1" / "cert_aux"
    d8.mkdir(parents=True, exist_ok=True)
    (d8 / "cert.json").write_text(json.dumps(b))
    (d8 / "spec.json").write_text(json.dumps(s1))
    try:
        A.main(["attack", str(d8 / "spec.json"), str(d8 / "cert.json"), str(d8 / "attack"), "4"])
        rows = json.loads((d8 / "attack" / "attack.json").read_text())
        kinds = {}
        for r in rows:
            k = r["kind"] + ":" + (r.get("verdict") or ("accepted" if r.get("accepted") else "REJECTED"))
            kinds[k] = kinds.get(k, 0) + 1
        bad_rows = [r for r in rows if r.get("verdict") in ("SURVIVOR", "ERROR", "ABORTED")]
        expect("attack on t1: runs to the end, original accepted, no survivor, no case without a verdict",
               kinds.get("original:accepted") == 1 and kinds.get("tamper:killed", 0) >= 8 and not bad_rows, kinds)
    except Exception as ex:  # noqa: BLE001
        expect("attack on t1: runs to the end", False, repr(ex))

    bad = [n for n, ok in results if not ok]
    (work / "selftest.json").write_text(json.dumps([{"case": n, "ok": ok} for n, ok in results], indent=1))
    print(f"{len(results) - len(bad)} of {len(results)} expectations hold")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "selftest_work"))
