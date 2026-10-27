module ux_pacer #(
  parameter int LIM = 16
) (
  input  logic ck,
  input  logic arst_b,
  input  logic park,
  output logic fire
);
  localparam int TW = $clog2(LIM);
  logic [TW-1:0] tally;

  assign fire = (tally == LIM - 1);

  always_ff @(posedge ck or negedge arst_b) begin
    if (~arst_b)
      tally <= {TW{1'b0}};
    else if (park | fire)
      tally <= {TW{1'b0}};
    else
      tally <= tally - {TW{1'b1}};
  end
endmodule

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
  localparam logic [3:0] PH_REST = 4'b0001;
  localparam logic [3:0] PH_LEAD = 4'b0010;
  localparam logic [3:0] PH_BODY = 4'b0100;
  localparam logic [3:0] PH_TAIL = 4'b1000;

  logic [7:0] hold_reg;
  logic [3:0] phase_r;
  logic [2:0] nib;
  logic       strobe;
  logic       at_rest;
  logic       shadow_q;

  function automatic logic line_level(input logic [3:0] ph, input logic lsb);
    if (ph[1])
      line_level = 1'b0;
    else if (ph[2])
      line_level = lsb;
    else
      line_level = 1'b1;
  endfunction

  assign at_rest = phase_r[0] & 1'b1;

  ux_pacer #(.LIM(CLK_DIV)) u_pace (
    .ck    (clk),
    .arst_b(rst_n),
    .park  (at_rest),
    .fire  (strobe)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      phase_r  <= PH_REST;
      nib      <= 3'b000;
      hold_reg <= 8'h00;
    end else if (phase_r[0]) begin
      if (tx_valid) begin
        phase_r  <= PH_LEAD;
        hold_reg <= tx_data;
        nib      <= 3'b000;
      end
    end else if (phase_r[1]) begin
      if (strobe) phase_r <= PH_BODY;
    end else if (phase_r[2]) begin
      if (strobe) begin
        hold_reg <= hold_reg >> 1;
        nib      <= nib + 3'd1;
        if (&nib) phase_r <= PH_TAIL;
      end
    end else begin
      if (strobe) phase_r <= PH_REST;
    end
  end

  always_ff @(posedge clk) shadow_q <= ~at_rest;

  assign busy_o   = ~at_rest;
  assign tx_ready = ~busy_o;
  assign tx_o     = line_level(phase_r, hold_reg[0]);
endmodule
