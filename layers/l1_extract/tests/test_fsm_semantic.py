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
