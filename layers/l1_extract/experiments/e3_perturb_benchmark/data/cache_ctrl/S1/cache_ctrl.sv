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
localparam int SW = $clog2(LINES);
localparam int KW = AW - SW - 2;
localparam [2:0] HOME  = 3'b101,
                 PROBE = 3'b011,
                 PUSH  = 3'b110,
                 PULL  = 3'b010,
                 ACK   = 3'b000;

reg  [DW-1:0]       obuf;
reg  [2:0]          cur;
reg  [KW*LINES-1:0] keys;
reg  [DW*LINES-1:0] words;
reg  [LINES-1:0]    vld;
reg                 lat_w;
reg  [DW-1:0]       lat_d;
reg  [AW-1:0]       lat_a;

wire [SW-1:0] sel   = lat_a[SW+1:2];
wire [KW-1:0] key   = lat_a[AW-1:SW+2];
wire [KW-1:0] k_rd  = keys[sel*KW +: KW];
wire [DW-1:0] w_rd  = words[sel*DW +: DW];
wire          match = vld[sel] & ~|(k_rd ^ key);

wire at_home  = (cur == HOME);
wire at_probe = (cur == PROBE);
wire at_push  = (cur == PUSH);
wire at_pull  = (cur == PULL);
wire at_ack   = (cur == ACK);
wire fill_go  = at_pull & mem_ack;
wire wr_go    = at_push && mem_ack && match;

always @(posedge clk or negedge rst_n)
  if (!rst_n) begin
    cur   <= HOME;
    lat_a <= {AW{1'b0}};
    lat_d <= {DW{1'b0}};
    lat_w <= 1'b0;
  end else begin
    if (at_home) begin
      if (cpu_req_valid) begin
        cur   <= PROBE;
        lat_a <= cpu_addr;
        lat_d <= cpu_wdata;
        lat_w <= cpu_we;
      end
    end else if (at_probe) begin
      if (lat_w)      cur <= PUSH;
      else if (match) cur <= ACK;
      else            cur <= PULL;
    end else if (at_push || at_pull) begin
      if (mem_ack) cur <= ACK;
    end else begin
      cur <= HOME;
    end
  end

always @(posedge clk or negedge rst_n)
  if (!rst_n) begin
    vld  <= {LINES{1'b0}};
    obuf <= {DW{1'b0}};
  end else if (fill_go) begin
    vld[sel] <= 1'b1;
    obuf     <= mem_rdata;
  end else if (wr_go) begin
    obuf <= lat_d;
  end else if (at_probe & match & ~lat_w) begin
    obuf <= w_rd;
  end

always @(posedge clk) begin
  if (fill_go) keys[sel*KW +: KW] <= key;
  if (fill_go)
    words[sel*DW +: DW] <= mem_rdata;
  else if (wr_go)
    words[sel*DW +: DW] <= lat_d;
end

assign cpu_rdata      = obuf;
assign cpu_req_ready  = at_home;
assign cpu_resp_valid = at_ack;
assign stall_o        = ~(at_home | at_ack);
assign mem_we         = at_push;
assign mem_req        = at_pull | mem_we;
assign mem_wdata      = lat_d;
assign mem_addr       = lat_a;
endmodule
