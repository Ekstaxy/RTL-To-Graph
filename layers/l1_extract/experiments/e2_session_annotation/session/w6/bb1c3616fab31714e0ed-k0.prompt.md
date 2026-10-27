MODULE: serial2parallel
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | CLOCK | L36
E2 | rst_n | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | RESET | L37
E3 | din_serial | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L38
E4 | din_valid | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L39
E5 | dout_parallel | port_out | 8b | reg[7:0] | driven_by=always_ff | fanin=4 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L40
E6 | dout_valid | port_out | 1b | reg | driven_by=always_ff | fanin=3 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L41
E7 | beat | wire | 4b | logic[3:0] | driven_by=inst_out | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L43
E8 | full_k | wire | 1b | logic | driven_by=inst_out | fanin=1 fanout=2 ctrl_fanout=1 addr_fanout=0 | - | L44
E9 | acc_bus | wire | 8b | logic[7:0] | driven_by=inst_out | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L45
E10 | low_half | wire | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L46
I1 | ctr0 | inst of s2p_tick | fanin=3 fanout=2 | L50
I2 | sr0 | inst of s2p_shreg | fanin=5 fanout=1 | L58

CHILD SUMMARIES:
I1 ctr0: s2p_tick -- s2p_tick (heuristic)
    interface clock_reset: CLOCK_RESET IN
    interface misc: SIMPLE OUT
I2 sr0: s2p_shreg -- s2p_shreg (heuristic)
    interface clock_reset: CLOCK_RESET IN
    interface shift: SIMPLE IN
    interface bit: SIMPLE IN
    interface misc: SIMPLE OUT

RTL (line-numbered):
  35| module serial2parallel(
  36| 	input clk,
  37| 	input rst_n,
  38| 	input din_serial,
  39| 	input din_valid,
  40| 	output reg [7:0]dout_parallel,
  41| 	output reg dout_valid
  42| );
  43|     wire [3:0] beat;
  44|     wire       full_k;
  45|     wire [7:0] acc_bus;
  46|     wire       low_half;
  47| 
  48|     assign low_half = ~beat[3];
  49| 
  50|     s2p_tick ctr0 (
  51|         .c   (clk),
  52|         .rb  (rst_n),
  53|         .en  (din_valid),
  54|         .pos (beat),
  55|         .wrap(full_k)
  56|     );
  57| 
  58|     s2p_shreg sr0 (
  59|         .c       (clk),
  60|         .rb      (rst_n),
  61|         .shift_en(din_valid & low_half),
  62|         .bit_in  (din_serial),
  63|         .word    (acc_bus)
  64|     );
  65| 
  66|     always @(posedge clk or negedge rst_n) begin
  67|         if (!rst_n)
  68|             dout_valid <= 1'b0;
  69|         else
  70|             dout_valid <= full_k;
  71|     end
  72| 
  73|     always @(posedge clk or negedge rst_n) begin
  74|         if (!rst_n)
  75|             dout_parallel <= 8'b0;
  76|         else if (full_k)
  77|             dout_parallel <= acc_bus;
  78|     end
  79| endmodule