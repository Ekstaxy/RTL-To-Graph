MODULE: verified_synchronizer
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk_a | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | CLOCK | L2
E2 | clk_b | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=3 ctrl_fanout=0 addr_fanout=0 | CLOCK | L3
E3 | arstn | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | CLOCK | L4
E4 | brstn | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=1 addr_fanout=0 | RESET | L5
E5 | data_in | port_in | 4b | logic[3:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L6
E6 | data_en | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L7
E7 | dataout | port_out | 4b | reg[3:0] | driven_by=always_ff | fanin=4 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L9
E8 | data_reg | reg | 4b | reg[3:0] | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L12
E9 | en_data_reg | reg | 1b | reg | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L18
E10 | en_clap_one | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L25
E11 | en_clap_two | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=1 addr_fanout=0 | STATE | L26

RTL (line-numbered):
   1| module verified_synchronizer(
   2| 	input 				clk_a	, 
   3| 	input 				clk_b	,   
   4| 	input 				arstn	,
   5| 	input				brstn   ,
   6| 	input		[3:0]	data_in	,
   7| 	input               data_en ,
   8| 
   9| 	output reg  [3:0] 	dataout
  10| );
  11| 
  12| reg	[3:0]	data_reg;
  13| always@(posedge clk_a or negedge arstn)
  14| begin
  15| 	if(!arstn)	data_reg <= 0;
  16| 		else	data_reg <= data_in;
  17| end
  18| reg en_data_reg;	
  19| always@(posedge clk_a or negedge arstn)
  20| begin
  21| 	if(!brstn)	en_data_reg <= 0;
  22| 		else	en_data_reg <= data_en;   
  23| end
  24| 
  25| reg	en_clap_one;	//1
  26| reg en_clap_two;	//2
  27| always@(posedge clk_b or negedge brstn)
  28| begin
  29| 	if(!brstn)	en_clap_one <= 0;
  30| 		else	en_clap_one <= en_data_reg;	
  31| end
  32| always@(posedge clk_b or negedge brstn)
  33| begin
  34| 	if(!brstn)	en_clap_two <= 0;
  35| 		else	en_clap_two <= en_clap_one;
  36| end
  37| 
  38| always@(posedge clk_b or negedge brstn)
  39| begin
  40| 	if(!brstn)	dataout <= 0;
  41| 		else	dataout <= (en_clap_two) ? data_reg : dataout;
  42| end
  43| 
  44| endmodule

DESIGN SPEC (teacher-only reference; use it to understand intent, but anchors must be grounded in the RTL and entity table, and the RTL wins if they disagree):
Please act as a professional verilog designer.

Implement a multi-bit MUX-based synchronizer, data_in will remain constant during the period when data_en is high, and data_en is high for at least 3 clk_b clock cycles. When the value of data_en is high, data can be synchronized. The data change frequency of data_in is very low. The change interval between two adjacent data is at least 10 clk_b clock cycles.
The clock clk_a is responsible for: input data_in is refer to clock a. enable signal data_en is refer to clock a.
The clock clk_b is responsible for the enable signal data_en delays two cycles, that is, two D flip-flops. This is done with reference to clock b. And the data is finally output dataout, and the output refers to clock b.

Module name:  
    synchronizer  

Input ports:
	clk_a: Clock signal A used for synchronous operations.
	clk_b: Clock signal B used for synchronous operations.
	arstn: Active-low reset signal A. Defined as 0 for reset and 1 for reset signal inactive.
	brstn: Active-low reset signal B. Defined as 0 for reset and 1 for reset signal inactive.
	data_in: Input data signal of size 4 bits.
	data_en: Input enable signal that controls the selection operation.

Output ports:
    dataout: Output data signal of size 4 bits.

Implementation:
Data Register:
The module includes a register, data_reg, to store the input data signal, data_in.
On the positive edge of clock signal A (clk_a) or the falling edge of reset signal A (arstn), the module updates the register. If the reset signal A (arstn) is low, indicating a reset condition, the register (data_reg) is set to 0. If the reset signal A (arstn) is high, the register (data_reg) is updated with the input data signal (data_in).
Enable Data Register:
The module includes a register, en_data_reg, to store the input enable signal, data_en.
On the positive edge of clock signal A (clk_a) or the falling edge of reset signal A (arstn), the module updates the register. If the reset signal A (arstn) is low, the register (en_data_reg) is set to 0. If the reset signal A (arstn) is high, the register (en_data_reg) is updated with the input enable signal (data_en).
Enable Control Registers:
The module includes two registers, en_clap_one and en_clap_two, to control the selection of the input data. On the positive edge of clock signal B (clk_b) or the falling edge of reset signal B (brstn), the module updates the registers. If the reset signal B (brstn) is low, indicating a reset condition, both registers (en_clap_one and en_clap_two) are set to 0.
If the reset signal B (brstn) is high, the registers (en_clap_one and en_clap_two) are updated based on the value of en_data_reg. The register en_clap_one is assigned the value of en_data_reg, and en_clap_two is assigned the previous value of en_clap_one.
Output Assignment:
On the positive edge of clock signal B (clk_b) or the falling edge of reset signal B (brstn), the module assigns the output data value. If the reset signal B (brstn) is low, indicating a reset condition, the output data (dataout) is set to 0. If the reset signal B (brstn) is high and the control signal (en_clap_two) is active, the output data (dataout) is assigned the value of the data register (data_reg). If the control signal (en_clap_two) is inactive, the output data (dataout) retains its previous value.

Give me the complete code.