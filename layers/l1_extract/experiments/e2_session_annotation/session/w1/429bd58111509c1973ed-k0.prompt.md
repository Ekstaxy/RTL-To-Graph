MODULE: sync_fifo
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | CLOCK | L6
E2 | rst_n | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=3 ctrl_fanout=0 addr_fanout=0 | RESET | L7
E3 | flush_i | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=3 ctrl_fanout=3 addr_fanout=0 | - | L8
E4 | in_valid | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L10
E5 | in_ready | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L11
E6 | in_data | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L12
E7 | out_valid | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L14
E8 | out_ready | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L15
E9 | out_data | port_out | 8b | logic[7:0] | driven_by=assign | fanin=2 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L16
E10 | count_o | port_out | 3b | logic[2:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L17
E11 | mem_q | mem | 8b x4 | logic[7:0]$[0:3] | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L21
E12 | wptr_q | reg | 2b | logic[1:0] | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=1 | STATE | L22
E13 | rptr_q | reg | 2b | logic[1:0] | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=1 | STATE | L22
E14 | count_q | reg | 3b | logic[2:0] | driven_by=always_ff | fanin=5 fanout=3 ctrl_fanout=0 addr_fanout=0 | STATE | L23
E15 | do_push | wire | 1b | logic | driven_by=assign | fanin=2 fanout=3 ctrl_fanout=3 addr_fanout=0 | - | L24
E16 | do_pop | wire | 1b | logic | driven_by=assign | fanin=2 fanout=2 ctrl_fanout=2 addr_fanout=0 | - | L24

RTL (line-numbered):
   2| module sync_fifo #(
   3|   parameter int WIDTH = 32,
   4|   parameter int DEPTH = 8
   5| ) (
   6|   input  logic             clk,
   7|   input  logic             rst_n,
   8|   input  logic             flush_i,
   9|   // write side
  10|   input  logic             in_valid,
  11|   output logic             in_ready,
  12|   input  logic [WIDTH-1:0] in_data,
  13|   // read side
  14|   output logic             out_valid,
  15|   input  logic             out_ready,
  16|   output logic [WIDTH-1:0] out_data,
  17|   output logic [$clog2(DEPTH):0] count_o
  18| );
  19|   localparam int AW = $clog2(DEPTH);
  20| 
  21|   logic [WIDTH-1:0] mem_q [DEPTH];
  22|   logic [AW-1:0]    wptr_q, rptr_q;
  23|   logic [AW:0]      count_q;
  24|   logic             do_push, do_pop;
  25| 
  26|   assign in_ready  = (count_q != DEPTH);
  27|   assign out_valid = (count_q != 0);
  28|   assign do_push   = in_valid && in_ready;
  29|   assign do_pop    = out_valid && out_ready;
  30|   assign out_data  = mem_q[rptr_q];
  31|   assign count_o   = count_q;
  32| 
  33|   always_ff @(posedge clk) begin
  34|     if (do_push) mem_q[wptr_q] <= in_data;
  35|   end
  36| 
  37|   always_ff @(posedge clk or negedge rst_n) begin
  38|     if (!rst_n) begin
  39|       wptr_q  <= '0;
  40|       rptr_q  <= '0;
  41|       count_q <= '0;
  42|     end else if (flush_i) begin
  43|       wptr_q  <= '0;
  44|       rptr_q  <= '0;
  45|       count_q <= '0;
  46|     end else begin
  47|       if (do_push) wptr_q <= wptr_q + 1'b1;
  48|       if (do_pop)  rptr_q <= rptr_q + 1'b1;
  49|       case ({do_push, do_pop})
  50|         2'b10:   count_q <= count_q + 1'b1;
  51|         2'b01:   count_q <= count_q - 1'b1;
  52|         default: count_q <= count_q;
  53|       endcase
  54|     end
  55|   end
  56| endmodule