module RefModule (
  input clk,
  input areset,
  input bump_left,
  input bump_right,
  input ground,
  output walk_left,
  output walk_right,
  output aaah
);

  wire gnd_lost;
  wire to_east;
  reg [3:0] mv;
  reg [3:0] mv_shadow;

  localparam [3:0] TRK_W = 4'b0010,
                   TRK_E = 4'b1000,
                   DROP_W = 4'b0001,
                   DROP_E = 4'b0100;

  assign aaah = ~(~mv[0] & ~mv[2]);
  assign walk_right = mv[3] & 1'b1;

  assign gnd_lost = ~ground;
  assign to_east = (mv[1] && bump_left) || mv[2] || (mv[3] && !bump_right);

  always @(posedge clk or posedge areset)
    if (areset)
      mv <= TRK_W;
    else if (gnd_lost) begin
      if (mv[1])
        mv <= DROP_W;
      else if (mv[3])
        mv <= DROP_E;
    end
    else
      mv <= to_east ? TRK_E : TRK_W;

  always @(posedge clk or posedge areset)
    if (areset) mv_shadow <= 4'h0;
    else mv_shadow <= {mv[0], mv[3:1]};

  assign walk_left = !(!mv[1]);

endmodule
