module ugly_mul(c, rn, s, a, b, d, p, bz);
input c;
input rn;
input s;
input [15:0] a;
input [15:0] b;
output d;
output bz;
output [31:0] p;

localparam [2:0] HOLD = 3'b001, SPIN = 3'b010, FIN = 3'b100;

reg  [31:0] sum;
reg  [4:0]  ctr;
reg  [2:0]  st, st_nx;
reg  [15:0] mplier;
reg  [31:0] mcand;
reg         d;
wire        last;
wire [31:0] part;
wire        load;

assign part = mcand & {32{mplier[0]}};
assign last = ~|(ctr ^ 5'b10000);
assign load = st[0] & s;

always @* begin
  st_nx = st;
  if (st[0]) begin
    if (s) st_nx = SPIN;
  end else if (st[1]) begin
    if (last) st_nx = FIN;
  end else begin
    st_nx = HOLD;
  end
end

always @(posedge c or negedge rn)
  if (~rn) st <= HOLD;
  else     st <= st_nx;

always @(posedge c or negedge rn)
  if (~rn) d <= 1'b0;
  else     d <= st[2];

always @(posedge c or negedge rn) begin
  if (~rn) begin
    sum <= 32'd0; mcand <= 32'd0; mplier <= 16'd0; ctr <= 5'd0;
  end else if (load) begin
    mcand <= {16'h0000, a};
    mplier <= b;
    sum <= 32'd0;
    ctr <= 5'd0;
  end else if (st[1]) begin
    sum    <= sum + part;
    mcand  <= {mcand[30:0], 1'b0};
    mplier <= {1'b0, mplier[15:1]};
    ctr    <= ctr - 5'b11111;
  end
end

assign p  = sum;
assign bz = st[1];
endmodule
