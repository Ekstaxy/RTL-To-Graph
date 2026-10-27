// Direct-mapped write-through cache controller (read-allocate).
module cache_ctrl #(
  parameter int AW    = 32,
  parameter int DW    = 32,
  parameter int LINES = 16
) (
  input  logic          clk,
  input  logic          rst_n,
  // CPU side
  input  logic          cpu_req_valid,
  output logic          cpu_req_ready,
  input  logic          cpu_we,
  input  logic [AW-1:0] cpu_addr,
  input  logic [DW-1:0] cpu_wdata,
  output logic          cpu_resp_valid,
  output logic [DW-1:0] cpu_rdata,
  output logic          stall_o,
  // memory side
  output logic          mem_req,
  output logic          mem_we,
  output logic [AW-1:0] mem_addr,
  output logic [DW-1:0] mem_wdata,
  input  logic          mem_ack,
  input  logic [DW-1:0] mem_rdata
);
  localparam int IW = $clog2(LINES);
  localparam int TW = AW - IW - 2;

  typedef enum logic [2:0] {IDLE, LOOKUP, WRITE_MEM, REFILL, RESPOND} st_e;
  st_e state_q, state_d;

  logic [TW-1:0] tag_array [LINES];
  logic [DW-1:0] data_array [LINES];
  logic [LINES-1:0] valid_bits;

  logic [AW-1:0] addr_q;
  logic [DW-1:0] wdata_q;
  logic          we_q;
  logic [IW-1:0] index;
  logic [TW-1:0] tag;
  logic          hit;
  logic [DW-1:0] rdata_q;

  assign index = addr_q[IW+1:2];
  assign tag   = addr_q[AW-1:IW+2];
  assign hit   = valid_bits[index] && (tag_array[index] == tag);

  always_comb begin
    state_d = state_q;
    case (state_q)
      IDLE:      if (cpu_req_valid) state_d = LOOKUP;
      LOOKUP:    if (we_q) state_d = WRITE_MEM;
                 else if (hit) state_d = RESPOND;
                 else state_d = REFILL;
      WRITE_MEM: if (mem_ack) state_d = RESPOND;
      REFILL:    if (mem_ack) state_d = RESPOND;
      RESPOND:   state_d = IDLE;
      default:   state_d = IDLE;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q    <= IDLE;
      valid_bits <= '0;
      addr_q     <= '0;
      wdata_q    <= '0;
      we_q       <= 1'b0;
      rdata_q    <= '0;
    end else begin
      state_q <= state_d;
      if (state_q == IDLE && cpu_req_valid) begin
        addr_q  <= cpu_addr;
        wdata_q <= cpu_wdata;
        we_q    <= cpu_we;
      end
      if (state_q == LOOKUP && hit && !we_q) rdata_q <= data_array[index];
      if (state_q == REFILL && mem_ack) begin
        valid_bits[index] <= 1'b1;
        rdata_q           <= mem_rdata;
      end
      if (state_q == WRITE_MEM && mem_ack && hit) rdata_q <= wdata_q;
    end
  end

  always_ff @(posedge clk) begin
    if (state_q == REFILL && mem_ack) begin
      tag_array[index]  <= tag;
      data_array[index] <= mem_rdata;
    end else if (state_q == WRITE_MEM && mem_ack && hit) begin
      data_array[index] <= wdata_q;
    end
  end

  assign cpu_req_ready  = (state_q == IDLE);
  assign stall_o        = (state_q != IDLE) && (state_q != RESPOND);
  assign cpu_resp_valid = (state_q == RESPOND);
  assign cpu_rdata      = rdata_q;

  assign mem_req   = (state_q == REFILL) || (state_q == WRITE_MEM);
  assign mem_we    = (state_q == WRITE_MEM);
  assign mem_addr  = addr_q;
  assign mem_wdata = wdata_q;
endmodule
