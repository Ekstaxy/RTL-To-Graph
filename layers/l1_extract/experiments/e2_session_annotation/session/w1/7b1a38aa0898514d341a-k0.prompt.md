MODULE: cache_ctrl
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=8 ctrl_fanout=0 addr_fanout=0 | CLOCK | L7
E2 | rst_n | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=6 ctrl_fanout=0 addr_fanout=0 | RESET | L8
E3 | cpu_req_valid | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=4 ctrl_fanout=4 addr_fanout=0 | - | L10
E4 | cpu_req_ready | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L11
E5 | cpu_we | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L12
E6 | cpu_addr | port_in | 32b | logic[31:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L13
E7 | cpu_wdata | port_in | 32b | logic[31:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L14
E8 | cpu_resp_valid | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L15
E9 | cpu_rdata | port_out | 32b | logic[31:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L16
E10 | stall_o | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L17
E11 | mem_req | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L19
E12 | mem_we | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L20
E13 | mem_addr | port_out | 32b | logic[31:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L21
E14 | mem_wdata | port_out | 32b | logic[31:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L22
E15 | mem_ack | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=5 ctrl_fanout=5 addr_fanout=0 | - | L23
E16 | mem_rdata | port_in | 32b | logic[31:0] | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L24
E17 | state_q | reg | 3b | cache_ctrl.st_e{IDLE,LOOKUP,WRITE_MEM,REFILL,RESPOND} | driven_by=always_ff | fanin=3 fanout=13 ctrl_fanout=8 addr_fanout=0 | STATE FSM? | L30
E18 | state_d | comb | 3b | cache_ctrl.st_e{IDLE,LOOKUP,WRITE_MEM,REFILL,RESPOND} | driven_by=always_comb | fanin=5 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L30
E19 | tag_array | mem | 26b x16 | logic[25:0]$[0:15] | driven_by=always_ff | fanin=5 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L32
E20 | data_array | mem | 32b x16 | logic[31:0]$[0:15] | driven_by=always_ff | fanin=7 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L33
E21 | valid_bits | reg | 16b | logic[15:0] | driven_by=always_ff | fanin=5 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L34
E22 | addr_q | reg | 32b | logic[31:0] | driven_by=always_ff | fanin=5 fanout=3 ctrl_fanout=0 addr_fanout=0 | STATE | L36
E23 | wdata_q | reg | 32b | logic[31:0] | driven_by=always_ff | fanin=5 fanout=3 ctrl_fanout=0 addr_fanout=0 | STATE | L37
E24 | we_q | reg | 1b | logic | driven_by=always_ff | fanin=5 fanout=2 ctrl_fanout=2 addr_fanout=0 | STATE | L38
E25 | index | wire | 4b | logic[3:0] | driven_by=assign | fanin=1 fanout=5 ctrl_fanout=0 addr_fanout=5 | - | L39
E26 | tag | wire | 26b | logic[25:0] | driven_by=assign | fanin=1 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L40
E27 | hit | wire | 1b | logic | driven_by=assign | fanin=4 fanout=3 ctrl_fanout=3 addr_fanout=0 | - | L41
E28 | rdata_q | reg | 32b | logic[31:0] | driven_by=always_ff | fanin=10 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L42

RTL (line-numbered):
   2| module cache_ctrl #(
   3|   parameter int AW    = 32,
   4|   parameter int DW    = 32,
   5|   parameter int LINES = 16
   6| ) (
   7|   input  logic          clk,
   8|   input  logic          rst_n,
   9|   // CPU side
  10|   input  logic          cpu_req_valid,
  11|   output logic          cpu_req_ready,
  12|   input  logic          cpu_we,
  13|   input  logic [AW-1:0] cpu_addr,
  14|   input  logic [DW-1:0] cpu_wdata,
  15|   output logic          cpu_resp_valid,
  16|   output logic [DW-1:0] cpu_rdata,
  17|   output logic          stall_o,
  18|   // memory side
  19|   output logic          mem_req,
  20|   output logic          mem_we,
  21|   output logic [AW-1:0] mem_addr,
  22|   output logic [DW-1:0] mem_wdata,
  23|   input  logic          mem_ack,
  24|   input  logic [DW-1:0] mem_rdata
  25| );
  26|   localparam int IW = $clog2(LINES);
  27|   localparam int TW = AW - IW - 2;
  28| 
  29|   typedef enum logic [2:0] {IDLE, LOOKUP, WRITE_MEM, REFILL, RESPOND} st_e;
  30|   st_e state_q, state_d;
  31| 
  32|   logic [TW-1:0] tag_array [LINES];
  33|   logic [DW-1:0] data_array [LINES];
  34|   logic [LINES-1:0] valid_bits;
  35| 
  36|   logic [AW-1:0] addr_q;
  37|   logic [DW-1:0] wdata_q;
  38|   logic          we_q;
  39|   logic [IW-1:0] index;
  40|   logic [TW-1:0] tag;
  41|   logic          hit;
  42|   logic [DW-1:0] rdata_q;
  43| 
  44|   assign index = addr_q[IW+1:2];
  45|   assign tag   = addr_q[AW-1:IW+2];
  46|   assign hit   = valid_bits[index] && (tag_array[index] == tag);
  47| 
  48|   always_comb begin
  49|     state_d = state_q;
  50|     case (state_q)
  51|       IDLE:      if (cpu_req_valid) state_d = LOOKUP;
  52|       LOOKUP:    if (we_q) state_d = WRITE_MEM;
  53|                  else if (hit) state_d = RESPOND;
  54|                  else state_d = REFILL;
  55|       WRITE_MEM: if (mem_ack) state_d = RESPOND;
  56|       REFILL:    if (mem_ack) state_d = RESPOND;
  57|       RESPOND:   state_d = IDLE;
  58|       default:   state_d = IDLE;
  59|     endcase
  60|   end
  61| 
  62|   always_ff @(posedge clk or negedge rst_n) begin
  63|     if (!rst_n) begin
  64|       state_q    <= IDLE;
  65|       valid_bits <= '0;
  66|       addr_q     <= '0;
  67|       wdata_q    <= '0;
  68|       we_q       <= 1'b0;
  69|       rdata_q    <= '0;
  70|     end else begin
  71|       state_q <= state_d;
  72|       if (state_q == IDLE && cpu_req_valid) begin
  73|         addr_q  <= cpu_addr;
  74|         wdata_q <= cpu_wdata;
  75|         we_q    <= cpu_we;
  76|       end
  77|       if (state_q == LOOKUP && hit && !we_q) rdata_q <= data_array[index];
  78|       if (state_q == REFILL && mem_ack) begin
  79|         valid_bits[index] <= 1'b1;
  80|         rdata_q           <= mem_rdata;
  81|       end
  82|       if (state_q == WRITE_MEM && mem_ack && hit) rdata_q <= wdata_q;
  83|     end
  84|   end
  85| 
  86|   always_ff @(posedge clk) begin
  87|     if (state_q == REFILL && mem_ack) begin
  88|       tag_array[index]  <= tag;
  89|       data_array[index] <= mem_rdata;
  90|     end else if (state_q == WRITE_MEM && mem_ack && hit) begin
  91|       data_array[index] <= wdata_q;
  92|     end
  93|   end
  94| 
  95|   assign cpu_req_ready  = (state_q == IDLE);
  96|   assign stall_o        = (state_q != IDLE) && (state_q != RESPOND);
  97|   assign cpu_resp_valid = (state_q == RESPOND);
  98|   assign cpu_rdata      = rdata_q;
  99| 
 100|   assign mem_req   = (state_q == REFILL) || (state_q == WRITE_MEM);
 101|   assign mem_we    = (state_q == WRITE_MEM);
 102|   assign mem_addr  = addr_q;
 103|   assign mem_wdata = wdata_q;
 104| endmodule