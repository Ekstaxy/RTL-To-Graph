module ps2_hist (
  input  logic        ck,
  input  logic [7:0]  nb,
  output logic [23:0] win
);
  genvar g;
  generate
    for (g = 0; g < 3; g = g + 1) begin : lane
      if (g == 0) begin : first
        always_ff @(posedge ck) win[7:0] <= nb;
      end else begin : rest
        always_ff @(posedge ck) win[g*8 +: 8] <= win[(g-1)*8 +: 8];
      end
    end
  endgenerate
endmodule

module ps2_step (
  input  logic       ck,
  input  logic       sr,
  input  logic       mark,
  output logic [3:0] hot
);
  localparam [3:0] H_SEEK = 4'b0001,
                   H_B2   = 4'b0010,
                   H_B3   = 4'b0100,
                   H_FIN  = 4'b1000;

  always_ff @(posedge ck) begin
    if (sr)
      hot <= H_SEEK;
    else if (hot[1])
      hot <= H_B3;
    else if (hot[2])
      hot <= H_FIN;
    else if (hot[0] | hot[3])
      hot <= mark ? H_B2 : H_SEEK;
    else
      hot <= {hot[2:0], hot[3]};
  end
endmodule

module RefModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);
  logic [3:0]  tk;
  logic [23:0] sh;
  logic        hdr_bit;

  assign hdr_bit = in[3];

  ps2_step fsm_i (
    .ck  (clk),
    .sr  (reset),
    .mark(hdr_bit),
    .hot (tk)
  );

  ps2_hist hist_i (
    .ck (clk),
    .nb (in),
    .win(sh)
  );

  assign done = tk[3];
  assign out_bytes = tk[3] ? sh : 24'bx;
endmodule
