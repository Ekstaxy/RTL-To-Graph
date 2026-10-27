MODULE: verified_width_8to16
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | CLOCK | L3
E2 | rst_n | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | RESET | L4
E3 | valid_in | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=4 addr_fanout=0 | - | L5
E4 | data_in | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L6
E5 | valid_out | port_out | 1b | reg | driven_by=always_ff | fanin=4 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L8
E6 | data_out | port_out | 16b | reg[15:0] | driven_by=always_ff | fanin=6 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L9
E7 | data_lock | reg | 8b | reg[7:0] | driven_by=always_ff | fanin=5 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L11
E8 | flag | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=3 ctrl_fanout=3 addr_fanout=0 | STATE | L12

RTL (line-numbered):
   2| module verified_width_8to16(
   3| 	input 				   clk 		,   
   4| 	input 				   rst_n		,
   5| 	input				      valid_in	,
   6| 	input	   [7:0]		   data_in	,
   7|  
   8|  	output	reg			valid_out,
   9| 	output   reg [15:0]	data_out
  10| );
  11| reg 	[7:0]		data_lock;  //data buffer
  12| reg 				flag	   ;
  13| //input data buff in data_lock
  14| always @(posedge clk or negedge rst_n ) begin
  15| 	if(!rst_n) 
  16| 		data_lock <= 'd0;
  17| 	else if(valid_in && !flag)
  18| 		data_lock <= data_in;
  19| end
  20| //generate flag
  21| always @(posedge clk or negedge rst_n ) begin
  22| 	if(!rst_n) 
  23| 		flag <= 'd0;
  24| 	else if(valid_in)
  25| 		flag <= ~flag;
  26| end
  27| //generate valid_out
  28| always @(posedge clk or negedge rst_n ) begin
  29| 	if(!rst_n) 
  30| 		valid_out <= 'd0;
  31| 	else if(valid_in && flag)
  32| 		valid_out <= 1'd1;
  33| 	else
  34| 		valid_out <= 'd0;
  35| end
  36| //data stitching 
  37| always @(posedge clk or negedge rst_n ) begin
  38| 	if(!rst_n) 
  39| 		data_out <= 'd0;
  40| 	else if(valid_in && flag)
  41| 		data_out <= {data_lock, data_in};
  42| end
  43| 
  44| endmodule