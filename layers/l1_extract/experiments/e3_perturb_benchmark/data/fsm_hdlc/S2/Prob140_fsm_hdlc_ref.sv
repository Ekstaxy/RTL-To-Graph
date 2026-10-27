`define HD_Z0  4'hC
`define HD_Z1  4'h6
`define HD_Z2  4'h3
`define HD_Z3  4'hB
`define HD_Z4  4'h9
`define HD_Z5  4'h1
`define HD_Z6  4'h0
`define HD_BAD 4'hE
`define HD_DRP 4'h7
`define HD_FRM 4'hD

module hd_next (
  input  wire [3:0] cur,
  input  wire       d,
  output reg  [3:0] nxt
);
  always @* begin
    nxt = 4'bxxxx;
    if (cur == `HD_Z0)       nxt = d ? `HD_Z1 : `HD_Z0;
    else if (cur == `HD_Z1)  nxt = d ? `HD_Z2 : `HD_Z0;
    else if (cur == `HD_Z2)  nxt = d ? `HD_Z3 : `HD_Z0;
    else if (cur == `HD_Z3)  nxt = d ? `HD_Z4 : `HD_Z0;
    else if (cur == `HD_Z4)  nxt = d ? `HD_Z5 : `HD_Z0;
    else if (cur == `HD_Z5)  nxt = d ? `HD_Z6 : `HD_DRP;
    else if (cur == `HD_Z6)  nxt = d ? `HD_BAD : `HD_FRM;
    else if (cur == `HD_BAD) nxt = d ? `HD_BAD : `HD_Z0;
    else if ((cur == `HD_FRM) || (cur == `HD_DRP))
                             nxt = d ? `HD_Z1 : `HD_Z0;
  end
endmodule

module hd_dec (
  input  wire [3:0] q,
  output wire [2:0] tags
);
  function automatic match4(input [3:0] a, input [3:0] b);
    match4 = ~|(a ^ b);
  endfunction

  assign tags = {match4(q, `HD_BAD), match4(q, `HD_FRM), match4(q, `HD_DRP)};
endmodule

module RefModule (
  input clk,
  input reset,
  input in,
  output disc,
  output flag,
  output err
);
  reg  [3:0] run_st;
  wire [3:0] run_nx;
  wire [2:0] st_flags;

  hd_next nx_u (.cur(run_st), .d(in), .nxt(run_nx));

  always @(posedge clk)
    run_st <= (reset == 1'b1) ? `HD_Z0 : run_nx;

  hd_dec dec_u (.q(run_st), .tags(st_flags));

  assign {err, flag, disc} = st_flags;
endmodule
