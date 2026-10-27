MODULE: lm_core
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | ck | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | CLOCK | L27
E2 | rst_a | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | RESET | L28
E3 | sense | port_in | 3b | logic[2:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L29
E4 | act | port_out | 3b | logic[2:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L30
E5 | ph | reg | 2b | reg[1:0] | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L33
E6 | ph_n | wire | 2b | logic[1:0] | driven_by=inst_out | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L34
I1 | u_step | inst of lm_step_unit | fanin=2 fanout=1 | L45

CHILD SUMMARIES:
I1 u_step: lm_step_unit -- lm_step_unit (heuristic)
    interface misc: SIMPLE IN
    interface hit: SIMPLE IN

RTL (line-numbered):
  26| module lm_core (
  27|   input  ck,
  28|   input  rst_a,
  29|   input  [2:0] sense,
  30|   output [2:0] act
  31| );
  32|   localparam [1:0] PH_A = 2'b11;
  33|   reg  [1:0] ph;
  34|   wire [1:0] ph_n;
  35| 
  36|   function [2:0] dec_ph;
  37|     input [1:0] v;
  38|     begin
  39|       dec_ph[2] = v[1] & v[0];
  40|       dec_ph[1] = v[1] & ~v[0];
  41|       dec_ph[0] = ~v[1];
  42|     end
  43|   endfunction
  44| 
  45|   lm_step_unit u_step (
  46|     .cur(ph),
  47|     .g(sense[0]),
  48|     .hit_a(sense[2]),
  49|     .hit_b(sense[1]),
  50|     .nxt(ph_n)
  51|   );
  52| 
  53|   always_ff @(posedge ck or posedge rst_a) begin
  54|     if (rst_a) ph <= PH_A;
  55|     else ph <= ph_n;
  56|   end
  57| 
  58|   assign act = dec_ph(ph);
  59| endmodule