module um_core(ck, nr, ld, go, ia, ib, sum, last);
input ck, nr, ld, go;
input [15:0] ia, ib;
output [31:0] sum;
output last;
reg [31:0] sum, mcand;
reg [15:0] mplier;
reg [4:0] lap;
wire [31:0] addend;
assign addend = mcand & {32{mplier[0]}};
assign last = lap[4] & ~|lap[3:0];
always @(posedge ck or negedge nr)
  if (!nr) begin
    sum <= 32'd0;
    mcand <= 32'd0;
  end else if (ld) begin
    sum <= 32'd0;
    mcand <= {16'd0, ia};
  end else if (go) begin
    sum <= sum + addend;
    mcand <= {mcand[30:0], 1'b0};
  end
always @(posedge ck or negedge nr)
  if (!nr) begin
    mplier <= 16'd0;
    lap <= 5'd0;
  end else begin
    if (ld) mplier <= ib;
    else if (go) mplier <= {1'b0, mplier[15:1]};
    if (ld) lap <= 5'd0;
    else if (go) lap <= lap - 5'b11111;
  end
endmodule

module ugly_mul(c, rn, s, a, b, d, p, bz);
input c, rn, s;
input [15:0] a, b;
output d, bz;
output [31:0] p;
reg [2:0] w;
reg fin;
wire hot_i, hot_r, hot_f, ends;
assign hot_i = w[0];
assign hot_r = w[1];
assign hot_f = w[2];
um_core u_core(.ck(c), .nr(rn), .ld(hot_i & s), .go(hot_r), .ia(a), .ib(b), .sum(p), .last(ends));
always @(posedge c or negedge rn)
  if (!rn) begin
    w <= 3'b001;
    fin <= 1'b0;
  end else begin
    fin <= hot_f;
    if (hot_i) w <= s ? 3'b010 : 3'b001;
    else if (hot_r) w <= ends ? 3'b100 : 3'b010;
    else w <= 3'b001;
  end
assign d = fin;
assign bz = hot_r;
endmodule
