MODULE: um_core
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | ck | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | CLOCK | L2
E2 | nr | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | RESET | L2
E3 | ld | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=4 addr_fanout=0 | - | L2
E4 | go | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=4 addr_fanout=0 | - | L2
E5 | ia | port_in | 16b | logic[15:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L3
E6 | ib | port_in | 16b | logic[15:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L3
E7 | last | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L5
E8 | sum | port_out | 32b | reg[31:0] | driven_by=always_ff | fanin=5 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L6
E9 | mcand | reg | 32b | reg[31:0] | driven_by=always_ff | fanin=5 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L6
E10 | mplier | reg | 16b | reg[15:0] | driven_by=always_ff | fanin=5 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L7
E11 | lap | reg | 5b | reg[4:0] | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L8
E12 | addend | wire | 32b | logic[31:0] | driven_by=assign | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L9

RTL (line-numbered):
   1| module um_core(ck, nr, ld, go, ia, ib, sum, last);
   2| input ck, nr, ld, go;
   3| input [15:0] ia, ib;
   4| output [31:0] sum;
   5| output last;
   6| reg [31:0] sum, mcand;
   7| reg [15:0] mplier;
   8| reg [4:0] lap;
   9| wire [31:0] addend;
  10| assign addend = mcand & {32{mplier[0]}};
  11| assign last = lap[4] & ~|lap[3:0];
  12| always @(posedge ck or negedge nr)
  13|   if (!nr) begin
  14|     sum <= 32'd0;
  15|     mcand <= 32'd0;
  16|   end else if (ld) begin
  17|     sum <= 32'd0;
  18|     mcand <= {16'd0, ia};
  19|   end else if (go) begin
  20|     sum <= sum + addend;
  21|     mcand <= {mcand[30:0], 1'b0};
  22|   end
  23| always @(posedge ck or negedge nr)
  24|   if (!nr) begin
  25|     mplier <= 16'd0;
  26|     lap <= 5'd0;
  27|   end else begin
  28|     if (ld) mplier <= ib;
  29|     else if (go) mplier <= {1'b0, mplier[15:1]};
  30|     if (ld) lap <= 5'd0;
  31|     else if (go) lap <= lap - 5'b11111;
  32|   end
  33| endmodule