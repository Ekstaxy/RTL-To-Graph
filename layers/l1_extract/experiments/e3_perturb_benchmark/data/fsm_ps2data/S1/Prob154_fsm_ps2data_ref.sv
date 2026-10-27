
module RefModule (
  input clk,
  input [7:0] in,
  input reset,
  output [23:0] out_bytes,
  output done
);

  localparam integer HUNT = 0;
  localparam integer MID0 = 1;
  localparam integer MID1 = 2;
  localparam integer FIN  = 3;

  logic [3:0] oh;
  logic [23:0] win;
  logic        mk;
  logic        go_mid;

  assign mk     = in[3];
  assign go_mid = (oh[HUNT] | oh[FIN]) & mk;

  always_ff @(posedge clk) begin
    win <= {win[15:8], win[7:0], in};
  end

  always_ff @(posedge clk) begin
    if (reset) begin
      oh <= 4'b0001;
    end else begin
      oh[MID0] <= go_mid;
      oh[MID1] <= oh[MID0];
      oh[FIN]  <= oh[MID1];
      oh[HUNT] <= ~(oh[MID0] | oh[MID1] | go_mid);
    end
  end

  assign done = oh[FIN] == 1'b1;

  assign out_bytes = (!done) ? 'x : win;

endmodule
