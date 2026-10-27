MODULE: RefModule
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | CLOCK | L3
E2 | in | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L4
E3 | reset | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | RESET | L5
E4 | out_bytes | port_out | 24b | logic[23:0] | driven_by=assign | fanin=2 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L6
E5 | done | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=1 addr_fanout=0 | - | L7
E6 | state | reg | 2b | reg[1:0] | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=1 addr_fanout=0 | STATE FSM? | L11
E7 | next | comb | 2b | reg[1:0] | driven_by=always_comb | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L12
E8 | in3 | wire | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=1 addr_fanout=0 | - | L14
E9 | out_bytes_r | reg | 24b | reg[23:0] | driven_by=always_ff | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L32

RTL (line-numbered):
   2| module RefModule (
   3|   input clk,
   4|   input [7:0] in,
   5|   input reset,
   6|   output [23:0] out_bytes,
   7|   output done
   8| );
   9| 
  10|   parameter BYTE1=0, BYTE2=1, BYTE3=2, DONE=3;
  11|   reg [1:0] state;
  12|   reg [1:0] next;
  13| 
  14|   wire in3 = in[3];
  15| 
  16|   always_comb begin
  17|     case (state)
  18|       BYTE1: next = in3 ? BYTE2 : BYTE1;
  19|       BYTE2: next = BYTE3;
  20|       BYTE3: next = DONE;
  21|       DONE: next = in3 ? BYTE2 : BYTE1;
  22|     endcase
  23|   end
  24| 
  25|   always @(posedge clk) begin
  26|     if (reset) state <= BYTE1;
  27|       else state <= next;
  28|   end
  29| 
  30|   assign done = (state==DONE);
  31| 
  32|   reg [23:0] out_bytes_r;
  33|   always @(posedge clk)
  34|     out_bytes_r <= {out_bytes_r[15:0], in};
  35| 
  36|   // Implementations may vary: Allow user to do anything while the output
  37|   // doesn't have to be valid.
  38| 
  39|   assign out_bytes = done ? out_bytes_r : 'x;
  40| 
  41| endmodule

DESIGN SPEC (teacher-only reference; use it to understand intent, but anchors must be grounded in the RTL and entity table, and the RTL wins if they disagree):
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clk
 - input  reset
 - input  in (8 bits)
 - output out_bytes (24 bits)
 - output done

The module should implement a finite state machine that will search for
message boundaries when given an input byte stream. The algorithm we'll
use is to discard bytes until we see one with in[3]=1. We then assume
that this is byte 1 of a message, and signal the receipt of a message
once all 3 bytes have been received (done). The FSM should signal done in
the cycle immediately after the third byte of each message was
successfully received.

Implement the datapath module that will output the 24-bit (3 byte)
message whenever a packet is received (out_bytes[23:16] is the first
byte, out_bytes[15:8] is the second byte, etc.). The reset signal is
active high synchronous. out_bytes needs to be valid whenever the done
signal is asserted. You may output anything at other times (i.e.,
don't-care). Assume all sequential logic is triggered on the positive
edge of the clock.

Here is an example waveform:

  time   clk rst in  done out_bytes
  0ns    0   1    0  x         x
  5ns    1   1    0  0         x
  10ns   0   1    0  0         x
  15ns   1   0   2c  0         x
  20ns   0   0   2c  0         x
  25ns   1   0   81  0         x
  30ns   0   0   81  0         x
  35ns   1   0    9  0         x
  40ns   0   0    9  0         x
  45ns   1   0   6b  1    2c8109
  50ns   0   0   6b  1    2c8109
  55ns   1   0    d  0         x
  60ns   0   0    d  0         x
  65ns   1   0   8d  0         x
  70ns   0   0   8d  0         x
  75ns   1   0   6d  1    6b0d8d
  80ns   0   0   6d  1    6b0d8d
  85ns   1   0   12  0         x
  90ns   0   0   12  0         x
  95ns   1   0    1  0         x
  100ns  0   0    1  0         x
  105ns  1   0    d  1    6d1201
  110ns  0   0    d  1    6d1201
  115ns  1   0   76  0         x
  120ns  0   0   76  0         x
  125ns  1   0   3d  0         x
  130ns  0   0   3d  0         x
  135ns  1   0   ed  1     d763d
  140ns  0   0   ed  1     d763d
  145ns  1   0   8c  0         x
  150ns  0   0   8c  0         x
  155ns  1   0   f9  0         x
  160ns  0   0   f9  0         x
  165ns  1   0   ce  1    ed8cf9
  170ns  0   0   ce  1    ed8cf9
  175ns  1   0   c5  0         x
  180ns  0   0   c5  0         x
  185ns  1   0   aa  0         x
  190ns  0   0   aa  0         x