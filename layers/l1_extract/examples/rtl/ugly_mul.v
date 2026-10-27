// Iterative shift-add multiplier, written in deliberately ugly legacy Verilog:
// flat, terse names, no enums, legacy always blocks, start/done handshake.
module ugly_mul(c, rn, s, a, b, d, p, bz);
input c, rn, s;
input [15:0] a, b;
output d, bz;
output [31:0] p;
reg [1:0] m;
reg [31:0] x, acc;
reg [15:0] y;
reg [4:0] k;
reg d;
wire z;
wire [31:0] t;
localparam I = 2'd0, R = 2'd1, F = 2'd2;
assign z = (k == 5'd16);
assign t = y[0] ? acc + x : acc;
assign bz = (m == R);
assign p = acc;
always @(posedge c or negedge rn)
  if (!rn) begin m <= I; x <= 0; y <= 0; acc <= 0; k <= 0; d <= 1'b0; end
  else begin
    d <= 1'b0;
    case (m)
      I: if (s) begin m <= R; x <= {16'd0, a}; y <= b; acc <= 0; k <= 0; end
      R: begin
           acc <= t; x <= x << 1; y <= y >> 1; k <= k + 1'b1;
           if (z) m <= F;
         end
      F: begin d <= 1'b1; m <= I; end
      default: m <= I;
    endcase
  end
endmodule
