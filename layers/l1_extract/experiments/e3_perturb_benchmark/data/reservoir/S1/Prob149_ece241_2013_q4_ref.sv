
module RefModule (
  input clk,
  input reset,
  input [2:0] s,
  output reg fr2,
  output reg fr1,
  output reg fr0,
  output reg dfr
);

  wire hi, mid, lo;
  wire n_hi, n_mid, n_lo;
  reg  [5:0] lvl;
  reg  [5:0] lvl_d;
  wire up_band, low_pair;

  wire bot;
  localparam [5:0] LV_EMPTY = 6'b000000,
                   LV_LO_R  = 6'b100001,
                   LV_LO_F  = 6'b101000,
                   LV_MD_R  = 6'b100010,
                   LV_MD_F  = 6'b110000,
                   LV_FULL  = 6'b100100;

  assign {hi, mid, lo} = s;
  assign n_hi  = ~hi;
  assign n_mid = ~mid;
  assign n_lo  = ~lo;
  assign bot = ~lvl[5];
  assign up_band  = lvl[1] | lvl[4];
  assign low_pair = lvl[0] | lvl[3];

  always_comb begin
    lvl_d[2] = (up_band | lvl[2]) & hi;
    lvl_d[1] = (low_pair & mid) | (lvl[1] & n_hi & mid);
    lvl_d[4] = (lvl[4] & n_hi & mid) | (lvl[2] & n_hi);
    lvl_d[3] = (up_band & ~(hi | mid)) | (lvl[3] & n_mid & lo);
    lvl_d[0] = (bot & lo) | (lvl[0] & n_mid & lo);
    lvl_d[5] = ~((bot & n_lo) | (low_pair & ~(mid | lo)));
  end

  always @(posedge clk)
    lvl <= reset ? LV_EMPTY : lvl_d;

  always_comb begin
    fr2 = lvl[5] ? 1'b0 : 1'b1;
    fr1 = bot | low_pair;
    fr0 = ~(lvl[2] | ~(bot | low_pair | up_band));
    if (!lvl[5] || lvl[3] || lvl[4]) dfr = 1'b1;
    else dfr = 1'b0;
  end

endmodule
