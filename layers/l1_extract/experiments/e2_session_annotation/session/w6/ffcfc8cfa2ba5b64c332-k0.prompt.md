MODULE: RefModule
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | CLOCK | L3
E2 | areset | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | RESET | L4
E3 | bump_left | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=1 addr_fanout=0 | - | L5
E4 | bump_right | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=1 addr_fanout=0 | - | L6
E5 | ground | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=1 addr_fanout=0 | - | L7
E6 | walk_left | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L8
E7 | walk_right | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L9
E8 | aaah | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L10
E9 | state | reg | 2b | reg[1:0] | driven_by=always_ff | fanin=3 fanout=4 ctrl_fanout=1 addr_fanout=0 | STATE FSM? | L14
E10 | next | comb | 2b | reg[1:0] | driven_by=always_comb | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L15

RTL (line-numbered):
   2| module RefModule (
   3|   input clk,
   4|   input areset,
   5|   input bump_left,
   6|   input bump_right,
   7|   input ground,
   8|   output walk_left,
   9|   output walk_right,
  10|   output aaah
  11| );
  12| 
  13|   parameter WL=0, WR=1, FALLL=2, FALLR=3;
  14|   reg [1:0] state;
  15|   reg [1:0] next;
  16| 
  17|   always_comb begin
  18|     case (state)
  19|       WL: next = ground ? (bump_left ? WR : WL) : FALLL;
  20|       WR: next = ground ? (bump_right ? WL: WR) : FALLR;
  21|       FALLL: next = ground ? WL : FALLL;
  22|       FALLR: next = ground ? WR : FALLR;
  23|     endcase
  24|   end
  25| 
  26|   always @(posedge clk, posedge areset) begin
  27|     if (areset) state <= WL;
  28|       else state <= next;
  29|   end
  30| 
  31|   assign walk_left = (state==WL);
  32|   assign walk_right = (state==WR);
  33|   assign aaah = (state == FALLL) || (state == FALLR);
  34| 
  35| endmodule