module uart_tx #(
  parameter int CLK_DIV = 16
) (
  input  logic       clk,
  input  logic       rst_n,
  input  logic       tx_valid,
  output logic       tx_ready,
  input  logic [7:0] tx_data,
  output logic       tx_o,
  output logic       busy_o
);
localparam [3:0] PH_REST = 4'b0001,
                 PH_LEAD = 4'b0010,
                 PH_PAY  = 4'b0100,
                 PH_TAIL = 4'b1000;

reg [7:0] sr, sr_shadow;
reg [3:0] ph;
wire      wrap;
reg [2:0] nb;
reg [$clog2(CLK_DIV)-1:0] tmr;
wire      quiet, grab, roll;

assign quiet = ph[0] & 1'b1;
assign grab  = quiet && tx_valid;
assign roll  = ph[2] & wrap;
assign wrap  = ~(tmr != (CLK_DIV - 1));

always @(posedge clk or negedge rst_n)
  if (~rst_n)
    tmr <= 0;
  else if (~quiet & ~wrap)
    tmr <= tmr + 1'b1;
  else
    tmr <= 0;

always @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
    ph <= PH_REST;
  end else begin
    if (ph[0]) begin
      if (tx_valid) ph <= PH_LEAD;
    end else if (ph[1]) begin
      if (wrap) ph <= PH_PAY;
    end else if (ph[2]) begin
      if (wrap && (&nb)) ph <= PH_TAIL;
    end else begin
      if (wrap) ph <= PH_REST;
    end
  end
end

always @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
    nb <= 3'b000; sr <= 8'h00; sr_shadow <= 8'h00;
  end else if (grab) begin
    sr <= tx_data; sr_shadow <= tx_data;
    nb <= 3'b000;
  end else if (roll) begin
    sr <= sr >> 1;
    nb <= nb - 3'b111;
  end
end

assign tx_ready = quiet;
assign busy_o   = !(!(~ph[0]));
assign tx_o     = ~(ph[1] | (ph[2] & ~sr[0]));
endmodule
