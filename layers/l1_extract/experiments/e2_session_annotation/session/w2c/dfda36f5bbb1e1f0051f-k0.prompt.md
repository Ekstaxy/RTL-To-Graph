MODULE: add8
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | a | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L30
E2 | b | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L31
E3 | Cin | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L32
E4 | y | port_out | 8b | logic[7:0] | driven_by=inst_out | fanin=2 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L33
E5 | Co | port_out | 1b | logic | driven_by=inst_out | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L34
E6 | Co_temp | wire | 1b | logic | driven_by=inst_out | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L37
I1 | add4_inst1 | inst of add4 | fanin=3 fanout=2 | L39
I2 | add4_inst2 | inst of add4 | fanin=3 fanout=2 | L47

CHILD SUMMARIES:
I1 add4_inst1: add4 -- 4-bit ripple-carry adder built from two chained add2 instances, the low half's carry Co_temp feeding the high half.
    interface operands: SIMPLE IN
    interface result: SIMPLE OUT
    key internals: a(INTERFACE_DATA), b(INTERFACE_DATA), y(DATAPATH_MAJOR)
I2 add4_inst2: add4 -- 4-bit ripple-carry adder built from two chained add2 instances, the low half's carry Co_temp feeding the high half.
    interface operands: SIMPLE IN
    interface result: SIMPLE OUT
    key internals: a(INTERFACE_DATA), b(INTERFACE_DATA), y(DATAPATH_MAJOR)

RTL (line-numbered):
  29| module add8 (
  30|     input wire [7:0] a,
  31|     input wire [7:0] b,
  32|     input wire Cin,
  33|     output wire [7:0] y,
  34|     output wire Co
  35| );
  36|  
  37|     wire Co_temp;
  38|  
  39|     add4 add4_inst1 (
  40|         .a(a[7:4]),
  41|         .b(b[7:4]),
  42|         .Cin(Co_temp),
  43|         .y(y[7:4]),
  44|         .Co(Co)
  45|     );
  46|  
  47|     add4 add4_inst2 (
  48|         .a(a[3:0]),
  49|         .b(b[3:0]),
  50|         .Cin(Cin),
  51|         .y(y[3:0]),
  52|         .Co(Co_temp)
  53|     );
  54|  
  55| endmodule

DESIGN SPEC (teacher-only reference; use it to understand intent, but anchors must be grounded in the RTL and entity table, and the RTL wins if they disagree):
NOTE: the spec describes the whole design (top: verified_adder_16bit). This module (add8) is only a SUBMODULE of it; use only the parts of the spec this module implements and do not describe the whole design in module_summary.
Please act as a professional verilog designer.

Implement a module of a 16-bit full adder in combinational logic.

Module name:  
    adder_16bit               
Input ports:
    a[15:0]: 16-bit input operand A.
    b[15:0]: 16-bit input operand B.
    Cin: Carry-in input.
Output ports:
    y[15:0]: 16-bit output representing the sum of A and B.
    Co: Carry-out output.

Implementation:
In the adder_16bit module, you need to design a small bit-width adder(8-bit adder), which will be instantiated multiple times.

Give me the complete code.