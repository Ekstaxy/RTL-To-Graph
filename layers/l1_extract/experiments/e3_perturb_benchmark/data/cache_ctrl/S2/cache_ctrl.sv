module cc_bank #(
  parameter int NL  = 16,
  parameter int SW  = 4,
  parameter int KW  = 26,
  parameter int VW  = 32
) (
  input  logic          clk,
  input  logic          rst_n,
  input  logic [SW-1:0] slot,
  input  logic [KW-1:0] key,
  input  logic          fill,
  input  logic          poke,
  input  logic [VW-1:0] fill_val,
  input  logic [VW-1:0] poke_val,
  output logic          match,
  output logic [VW-1:0] q
);
  logic [NL*KW-1:0] keys_flat;
  logic [NL*VW-1:0] vals_flat;
  logic [NL-1:0]    live;

  genvar gk;
  generate
    for (gk = 0; gk < NL; gk = gk + 1) begin : g_line
      always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
          live[gk] <= 1'b0;
        else if (fill && (slot == gk))
          live[gk] <= 1'b1;
      end

      always_ff @(posedge clk) begin
        if (fill && (slot == gk)) begin
          keys_flat[gk*KW +: KW] <= key;
          vals_flat[gk*VW +: VW] <= fill_val;
        end else if (poke && (slot == gk)) begin
          vals_flat[gk*VW +: VW] <= poke_val;
        end
      end
    end
  endgenerate

  assign match = live[slot] & (keys_flat[slot*KW +: KW] == key);
  assign q     = vals_flat[slot*VW +: VW];
endmodule

module cache_ctrl #(
  parameter int AW    = 32,
  parameter int DW    = 32,
  parameter int LINES = 16
) (
  input  logic          clk,
  input  logic          rst_n,
  input  logic          cpu_req_valid,
  output logic          cpu_req_ready,
  input  logic          cpu_we,
  input  logic [AW-1:0] cpu_addr,
  input  logic [DW-1:0] cpu_wdata,
  output logic          cpu_resp_valid,
  output logic [DW-1:0] cpu_rdata,
  output logic          stall_o,
  output logic          mem_req,
  output logic          mem_we,
  output logic [AW-1:0] mem_addr,
  output logic [DW-1:0] mem_wdata,
  input  logic          mem_ack,
  input  logic [DW-1:0] mem_rdata
);
  localparam int SLW = $clog2(LINES);
  localparam int KYW = AW - SLW - 2;

  localparam logic [2:0] M_WAIT = 3'b110;
  localparam logic [2:0] M_PEEK = 3'b011;
  localparam logic [2:0] M_PUSH = 3'b101;
  localparam logic [2:0] M_PULL = 3'b000;
  localparam logic [2:0] M_DONE = 3'b010;

  logic [2:0]    mode;
  logic [AW-1:0] lat_a;
  logic [DW-1:0] lat_d;
  logic [DW-1:0] out_r;
  logic          lat_w;
  logic          found;
  logic [DW-1:0] bank_q;
  logic          is_wait, is_peek, is_push, is_pull, is_done;
  logic          refill_ok, write_ok;

  assign is_wait = (mode == M_WAIT);
  assign is_peek = (mode == M_PEEK);
  assign is_push = (mode == M_PUSH);
  assign is_pull = (mode == M_PULL);
  assign is_done = (mode == M_DONE);

  assign refill_ok = is_pull & mem_ack;
  assign write_ok  = is_push & mem_ack & found;

  cc_bank #(.NL(LINES), .SW(SLW), .KW(KYW), .VW(DW)) u_bank (
    .clk     (clk),
    .rst_n   (rst_n),
    .slot    (lat_a[SLW+1:2]),
    .key     (lat_a[AW-1:SLW+2]),
    .fill    (refill_ok),
    .poke    (write_ok),
    .fill_val(mem_rdata),
    .poke_val(lat_d),
    .match   (found),
    .q       (bank_q)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      mode <= M_WAIT;
    end else if (is_wait) begin
      if (cpu_req_valid) mode <= M_PEEK;
    end else if (is_peek) begin
      mode <= lat_w ? M_PUSH : (found ? M_DONE : M_PULL);
    end else if (is_push || is_pull) begin
      if (mem_ack) mode <= M_DONE;
    end else begin
      mode <= M_WAIT;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lat_a <= {AW{1'b0}};
      lat_d <= {DW{1'b0}};
      lat_w <= 1'b0;
    end else if (is_wait && cpu_req_valid) begin
      lat_a <= cpu_addr;
      lat_d <= cpu_wdata;
      lat_w <= cpu_we;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      out_r <= {DW{1'b0}};
    else if (write_ok)
      out_r <= lat_d;
    else if (refill_ok)
      out_r <= mem_rdata;
    else if (is_peek && found && !lat_w)
      out_r <= bank_q;
  end

  assign cpu_req_ready  = is_wait;
  assign stall_o        = ~(is_wait | is_done);
  assign cpu_resp_valid = is_done;
  assign cpu_rdata      = out_r;

  assign mem_req   = is_pull | is_push;
  assign mem_we    = is_push;
  assign mem_addr  = lat_a;
  assign mem_wdata = lat_d;
endmodule
