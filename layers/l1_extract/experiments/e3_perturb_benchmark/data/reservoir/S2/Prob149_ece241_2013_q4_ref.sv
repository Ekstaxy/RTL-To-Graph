
module rsv_track (
  input            c,
  input            sr,
  input      [2:0] lv,
  output reg [2:0] cur
);
  localparam [2:0] Z_BOT = 3'd0, Z_1U = 3'd3, Z_1D = 3'd6,
                   Z_2U = 3'd1, Z_2D = 3'd5, Z_TOP = 3'd2;
  reg [2:0] tmp_n;

  always_comb begin
    tmp_n = cur;
    if (cur == Z_BOT) begin
      if (lv[0]) tmp_n = Z_1U;
    end else if (cur == Z_1U || cur == Z_1D) begin
      if (lv[1]) tmp_n = Z_2U;
      else if (!lv[0]) tmp_n = Z_BOT;
    end else if (cur == Z_2U || cur == Z_2D) begin
      if (lv[2]) tmp_n = Z_TOP;
      else if (!lv[1]) tmp_n = Z_1D;
    end else if (cur == Z_TOP) begin
      if (!lv[2]) tmp_n = Z_2D;
    end
  end

  always_ff @(posedge c) begin
    if (sr) cur <= Z_BOT;
    else cur <= tmp_n;
  end
endmodule

module RefModule (
  input clk,
  input reset,
  input [2:0] s,
  output reg fr2,
  output reg fr1,
  output reg fr0,
  output reg dfr
);

  wire [2:0] zq;
  wire [3:0] flow_vec;

  function [3:0] zmap;
    input [2:0] k;
    case (k)
      3'd0: zmap = 4'b1111;
      3'd3: zmap = 4'b0110;
      3'd6: zmap = 4'b0111;
      3'd1: zmap = 4'b0010;
      3'd5: zmap = 4'b0011;
      default: zmap = 4'b0000;
    endcase
  endfunction

  rsv_track trk0 (
    .c(clk),
    .sr(reset),
    .lv(s),
    .cur(zq)
  );

  assign flow_vec = zmap(zq);

  always @(*) begin
    {fr2, fr1} = flow_vec[3:2];
    fr0 = flow_vec[1];
    dfr = flow_vec[0] & 1'b1;
  end

endmodule
