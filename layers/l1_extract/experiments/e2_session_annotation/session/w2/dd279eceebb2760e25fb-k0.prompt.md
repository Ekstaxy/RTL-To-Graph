MODULE: verified_accu
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | CLOCK | L4
E2 | rst_n | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=0 addr_fanout=0 | RESET | L5
E3 | data_in | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L6
E4 | valid_in | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L7
E5 | valid_out | port_out | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L9
E6 | data_out | port_out | 10b | reg[9:0] | driven_by=always_ff | fanin=5 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L10
E7 | count | reg | 2b | reg[1:0] | driven_by=always_ff | fanin=4 fanout=3 ctrl_fanout=2 addr_fanout=0 | STATE | L13
E8 | add_cnt | wire | 1b | logic | driven_by=assign | fanin=1 fanout=3 ctrl_fanout=3 addr_fanout=0 | - | L14
E9 | ready_add | wire | 1b | logic | driven_by=assign | fanin=2 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L15
E10 | end_cnt | wire | 1b | logic | driven_by=assign | fanin=2 fanout=2 ctrl_fanout=2 addr_fanout=0 | - | L16
E11 | data_out_reg | reg | 10b | reg[9:0] | driven_by=always_ff | fanin=5 fanout=0 ctrl_fanout=0 addr_fanout=0 | STATE | L17

RTL (line-numbered):
   3| module verified_accu(
   4|     input               clk         ,   
   5|     input               rst_n       ,
   6|     input       [7:0]   data_in     ,
   7|     input               valid_in     ,
   8|  
   9|     output  reg         valid_out     ,
  10|     output  reg [9:0]   data_out
  11| );
  12|     
  13|    reg [1:0] count;
  14|    wire add_cnt;
  15|    wire ready_add;
  16|    wire end_cnt;
  17|    reg [9:0]   data_out_reg;
  18| 
  19|    assign add_cnt = ready_add;
  20|    assign end_cnt = ready_add && (count == 'd3);
  21|    
  22|    //count
  23|    always @(posedge clk or negedge rst_n) begin
  24|        if(!rst_n) begin
  25|           count <= 0;
  26|        end
  27|        else if(end_cnt) begin
  28|           count <= 0;
  29|        end
  30|        else if(add_cnt) begin
  31|           count <= count + 1;
  32|        end
  33|    end
  34| 
  35|     //data_out_reg
  36|    always @(posedge clk or negedge rst_n) begin
  37|       if(!rst_n) begin
  38|         data_out_reg <= 0;
  39|       end
  40|       else if (add_cnt && count == 0) begin
  41|           data_out_reg <= data_in;
  42|       end
  43|       else if (add_cnt) begin
  44|           data_out_reg <= data_out_reg + data_in;
  45|       end
  46|    end
  47| 
  48|     //data_out
  49|    always @(posedge clk or negedge rst_n) begin
  50|       if(!rst_n) begin
  51|         data_out <= 0;
  52|       end
  53|       else if (add_cnt && count == 0) begin
  54|           data_out <= data_in;
  55|       end
  56|       else if (add_cnt) begin
  57|           data_out <= data_out + data_in;
  58|       end
  59|    end
  60| 
  61|    //ready_add
  62|    assign ready_add = !valid_out | valid_in;
  63| 
  64|    //valid_out
  65|    always @(posedge clk or negedge rst_n) begin
  66|        if(!rst_n) begin
  67|            valid_out <= 0;
  68|        end
  69|        else if(end_cnt) begin
  70|            valid_out <= 1;
  71|        end
  72|        else begin
  73|            valid_out <= 0;
  74|        end
  75|    end  
  76|      
  77| endmodule

DESIGN SPEC (teacher-only reference; use it to understand intent, but anchors must be grounded in the RTL and entity table, and the RTL wins if they disagree):
Please act as a professional verilog designer.

Implement a module to achieve serial input data accumulation output, input is 8bit data. The valid_in will be set to 1 before the first data comes in. Whenever the module receives 4 input data, the data_out outputs 4 received data accumulation results and sets the valid_out to be 1 (will last only 1 cycle).

Module name:  
    accu               
Input ports:
	clk: Clock input for synchronization.
	rst_n: Active-low reset signal.
	data_in[7:0]: 8-bit input data for addition.
	valid_in: Input signal indicating readiness for new data.   
Output ports:
    valid_out: Output signal indicating when 4 input data accumulation is reached.
	data_out[9:0]: 10-bit output data representing the accumulated sum.

Implementation:
When valid_in is 1, data_in is a valid input. Accumulate four valid input data_in values and calculate the output data_out by adding these four values together. 
There is no output when there are fewer than four data_in inputs in the interim. Along with the output data_out, a cycle of valid_out=1 will appear as a signal. 
The valid_out signal is set to 1 when the data_out outputs 4 received data accumulation results. Otherwise, it is set to 0.

Give me the complete code.