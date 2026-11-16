"""Semantic FSM extraction must not depend on coding style."""

import networkx as nx

from rtl2d_l1.frontend import build_entity_tables, build_graph, elaborate
from rtl2d_l1.frontend.fsm_hybrid import extract_fsms_hybrid
from rtl2d_l1.frontend.fsm_semantic import _parse_const, detect, state_graph

BINARY = """
module det(input clk, input rst_n, input x, output y);
  localparam A = 2'd0, B = 2'd1, C = 2'd2;
  reg [1:0] s, n;
  always @(*) begin
    n = s;
    case (s)
      A: if (x) n = B;
      B: n = x ? C : A;
      C: if (!x) n = A;
      default: n = A;
    endcase
  end
  always @(posedge clk or negedge rst_n) if (!rst_n) s <= A; else s <= n;
  assign y = (s == C);
endmodule
"""

# same machine: one-hot, per-bit next-state equations, reset folded into a ternary,
# logic in a submodule
ONEHOT = """
module nxt(input [2:0] q, input x, output [2:0] d);
  assign d[0] = (q[0] & ~x) | (q[1] & ~x) | (q[2] & ~x);
  assign d[1] = q[0] & x;
  assign d[2] = (q[1] & x) | (q[2] & x);
endmodule
module det(input clk, input rst_n, input x, output y);
  reg [2:0] h;
  wire [2:0] d;
  nxt u(.q(h), .x(x), .d(d));
  always @(posedge clk) h <= (!rst_n) ? 3'b001 : d;
  assign y = h[2];
endmodule
"""


# same machine as BINARY: literals with white space after the base, and comments in front of
# them (both legal Verilog; seen in wb2axip axisgfsm and picosoc spimemio)
SPACED = """
module det(input clk, input rst_n, input x, output y);
  reg [1:0] s, n;
  always @(*) begin
    n = s;
    case (s)
      2'd 0: if (x) n = // leave A
                        2'd 1;
      2'd 1: n = x ? /* stay on the path */ 2'd 2 : 2'b 00;
      2'd 2: if (!x) n = 2'b 0_0;
      default: n = 2'd 0;
    endcase
  end
  always @(posedge clk or negedge rst_n) if (!rst_n) s <= 2'd 0; else s <= n;
  assign y = (s == 2'd 2);
endmodule
"""


def _graph(tmp_path, name, text):
    f = tmp_path / f"{name}.v"
    f.write_text(text, encoding="utf-8")
    d = elaborate([f], top="det")
    G = build_graph(d)
    return d, G, build_entity_tables(G)


def test_coding_style_independent(tmp_path):
    d1, G1, T1 = _graph(tmp_path, "bin", BINARY)
    d2, G2, T2 = _graph(tmp_path, "oh", ONEHOT)
    syn1 = {f"{t.canonical_instance}.{r.name}" for t in T1 for r in t.rows if r.fsm_candidate}
    s1 = [r for r in detect(d1, G1, syn1) if not r.error]
    s2 = [r for r in detect(d2, G2, set()) if not r.error]
    assert len(s1) == 1 and len(s2) == 1
    g1, g2 = state_graph(s1[0]), state_graph(s2[0])
    assert len(g1) == len(g2) == 3
    assert nx.is_isomorphic(g1, g2, node_match=lambda a, b: a["reset"] == b["reset"])
    # the one-hot register is found only by the semantic engine
    assert not any(r.fsm_candidate for t in T2 for r in t.rows)


def test_hybrid_marks_syntactic_consistent_and_adds_semantic_only(tmp_path):
    d1, G1, T1 = _graph(tmp_path, "bin", BINARY)
    f1 = extract_fsms_hybrid(d1, G1, T1)
    assert [getattr(f, "semantic_check", None) for f in f1] == ["consistent"]
    d2, G2, T2 = _graph(tmp_path, "oh", ONEHOT)
    f2 = extract_fsms_hybrid(d2, G2, T2)
    assert len(f2) == 1 and f2[0].semantic_check == "semantic-only"
    edges = {(t.src, t.dst, t.cond) for t in f2[0].transitions if t.src != t.dst}
    assert (
        "S_1",
        "S_2",
        "x",
    ) in edges  # A -> B on x (state names from values: 001 -> S_1, 010 -> S_2)


def _candidates(tables):
    return {
        f"{t.canonical_instance}.{r.name}" for t in tables for r in t.rows if r.fsm_candidate
    }


def test_parse_const_accepts_comments_and_space_after_base():
    # text as `str(expr.syntax)` returns it: the comments and newlines in front come with it
    assert _parse_const(" // Clear any errors\n\t\t1'b1") == (1, 1, 1)
    assert _parse_const("/* note */ 2'b1_0") == (2, 2, 3)
    # white space between the base and the digits is legal; `?` bits are don't-care
    assert _parse_const(" 1'b 0") == (0, 1, 1)
    assert _parse_const("\n\t3'b 01?") == (2, 3, 0b110)
    assert _parse_const("4 'd 9") == (9, 4, 15)


def test_spaced_and_commented_literals_do_not_make_the_check_unsupported(tmp_path):
    d1, G1, T1 = _graph(tmp_path, "bin", BINARY)
    d2, G2, T2 = _graph(tmp_path, "sp", SPACED)
    f2 = extract_fsms_hybrid(d2, G2, T2)
    assert [getattr(f, "semantic_check", None) for f in f2] == ["consistent"]
    g1 = state_graph([r for r in detect(d1, G1, _candidates(T1)) if not r.error][0])
    g2 = state_graph([r for r in detect(d2, G2, _candidates(T2)) if not r.error][0])
    assert nx.is_isomorphic(g1, g2, node_match=lambda a, b: a["reset"] == b["reset"])


# BINARY with a soft reset next to the hard one, as in picosoc spimemio: `if (!resetn || softreset)`
SOFT_RESET = """
module det(input clk, input rst_n, input go, input x, output y);
  localparam A = 2'd0, B = 2'd1, C = 2'd2;
  reg [1:0] s;
  reg sr;
  always @(posedge clk) if (!rst_n) sr <= 1'b1; else sr <= go;
  always @(posedge clk) begin
    if (!rst_n || sr) s <= A;
    else case (s)
      A: if (x) s <= B;
      B: s <= x ? C : A;
      C: if (!x) s <= A;
      default: s <= A;
    endcase
  end
  assign y = (s == C);
endmodule
"""


def test_soft_reset_next_to_the_reset_still_gives_the_reset_state(tmp_path):
    d, G, T = _graph(tmp_path, "soft", SOFT_RESET)
    f = extract_fsms_hybrid(d, G, T)
    assert len(f) == 1
    # asserting rst_n alone takes the branch, so A is the reset state...
    assert f[0].reset_state == "A"
    # ...and `sr` makes the same assignment an ordinary transition from every state
    assert ("*", "A", "sr") in {(t.src, t.dst, t.cond) for t in f[0].transitions}
    assert f[0].semantic_check == "consistent"


# Six states that each wait for a handshake from a submodule. `rdy` needs fourteen independent
# registers at once (well under 0.1% of uniform samples), so plain sampling stays in S0.
_Q = [f"q{i}" for i in range(14)]
HANDSHAKE = f"""
module hs(input clk, input [13:0] a, output rdy);
  reg {", ".join(_Q)};
  always @(posedge clk) {{{", ".join(_Q)}}} <= a;
  assign rdy = {" & ".join(_Q)};
endmodule
module det(input clk, input rst_n, input [13:0] a, output y);
  localparam S0 = 3'd0, S1 = 3'd1, S2 = 3'd2, S3 = 3'd3, S4 = 3'd4, S5 = 3'd5;
  reg [2:0] s;
  wire rdy;
  hs u(.clk(clk), .a(a), .rdy(rdy));
  always @(posedge clk or negedge rst_n)
    if (!rst_n) s <= S0;
    else case (s)
      S0: if (rdy) s <= S1;
      S1: if (rdy) s <= S2;
      S2: if (rdy) s <= S3;
      S3: if (rdy) s <= S4;
      S4: if (rdy) s <= S5;
      S5: if (rdy) s <= S0;
      default: s <= S0;
    endcase
  assign y = (s == S5);
endmodule
"""


def test_rare_guard_from_a_submodule_is_found_and_reused_in_every_state(tmp_path):
    d, G, T = _graph(tmp_path, "hs", HANDSHAKE)
    r = [x for x in detect(d, G, _candidates(T)) if not x.error]
    assert len(r) == 1
    assert r[0].states == [0, 1, 2, 3, 4, 5]
    f = extract_fsms_hybrid(d, G, T)
    assert [getattr(x, "semantic_check", None) for x in f] == ["consistent"]
