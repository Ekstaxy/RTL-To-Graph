MODULE: verified_multi_booth_8bit
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=5 ctrl_fanout=0 addr_fanout=0 | CLOCK | L4
E2 | reset | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=5 ctrl_fanout=0 addr_fanout=0 | RESET | L4
E3 | a | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L5
E4 | b | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L5
E5 | p | port_out | 16b | reg[15:0] | driven_by=always_ff | fanin=5 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L9
E6 | multiplier | reg | 16b | reg[15:0] | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=1 addr_fanout=0 | STATE | L10
E7 | multiplicand | reg | 16b | reg[15:0] | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L11
E8 | rdy | port_out | 1b | reg | driven_by=always_ff | fanin=3 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L12
E9 | ctr | reg | 5b | reg[4:0] | driven_by=always_ff | fanin=2 fanout=3 ctrl_fanout=3 addr_fanout=0 | STATE | L13

RTL (line-numbered):
   3| module verified_multi_booth_8bit (p, rdy, clk, reset, a, b);
   4|    input clk, reset;
   5|    input [7:0] a, b;
   6|    output [15:0] p;
   7|    output rdy;
   8|    
   9|    reg [15:0] p;
  10|    reg [15:0] multiplier;
  11|    reg [15:0] multiplicand;
  12|    reg rdy;
  13|    reg [4:0] ctr;
  14| 
  15| always @(posedge clk or posedge reset) begin
  16|     if (reset) 
  17|     begin
  18|     rdy     <= 0;
  19|     p   <= 0;
  20|     ctr     <= 0;
  21|     multiplier <= {{8{a[7]}}, a};
  22|     multiplicand <= {{8{b[7]}}, b};
  23|     end 
  24|     else 
  25|     begin 
  26|       if(ctr < 16) 
  27|           begin
  28|           multiplicand <= multiplicand << 1;
  29|             if (multiplier[ctr] == 1)
  30|             begin
  31|                 p <= p + multiplicand;
  32|             end
  33|             ctr <= ctr + 1;
  34|           end
  35|        else 
  36|            begin
  37|            rdy <= 1;
  38|            end
  39|     end
  40|   end //End of always block
  41|     
  42| endmodule

DESIGN SPEC (teacher-only reference; use it to understand intent, but anchors must be grounded in the RTL and entity table, and the RTL wins if they disagree):
Please act as a professional verilog designer.

Implement an 8-bit Radix-4 booth multiplier that performs the multiplication of two 8-bit inputs (a and b) using the Booth algorithm. It utilizes a clock signal (clk), and a reset signal (reset), and provides the product output (p) and a ready signal (rdy). The ready signal (rdy) is set to 1 to indicate the completion of the multiplication process.

Module name:  
   multi_booth_8bit  

Input ports:
   clk: Clock signal used for synchronous operation.
   reset: Reset signal used to initialize the multiplier module.
   a: 8-bit input representing the multiplicand.
   b: 8-bit input representing the multiplier.

Output ports:
   p: 16-bit output representing the product of the multiplication.
   rdy: Ready signal indicating the completion of the multiplication operation.

Implementation:
On the positive edge of the clock signal (clk) or the positive edge of the reset signal (reset), the module performs the multiplication process.
If the reset signal (reset) is high, two 16-bit registers multiplier <= {{8{a[7]}}, a} and multiplicand <= {{8{b[7]}}, b}. 
If the reset signal (reset) is low, indicating normal operation, the module checks if the counter (5bit ctr) is less than 16.
If the counter (ctr) is less than 16, the multiplicand register (multiplicand) is left-shifted by 1 to simulate the Booth algorithm's shifting operation.
If the current bit of the multiplier register (multiplier[ctr]) is 1, indicating a positive Booth encoding, the product register (p) accumulates the value of the multiplicand register (multiplicand).
The counter (ctr) is incremented by 1. Once the counter (ctr) reaches 16, indicating the completion of the multiplication process, the ready signal (rdy) is set to 1.

Give me the complete code.