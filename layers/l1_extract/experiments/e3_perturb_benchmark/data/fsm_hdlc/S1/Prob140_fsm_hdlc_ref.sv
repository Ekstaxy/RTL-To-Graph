
module RefModule (
  input clk,
  input reset,
  input in,
  output disc,
  output flag,
  output err
);

  typedef enum logic [3:0] {
    R0  = 4'h0,
    R1  = 4'h3,
    R2  = 4'hC,
    R3  = 4'h5,
    R4  = 4'hE,
    R5  = 4'h1,
    R6  = 4'h8,
    OVF = 4'h6,
    DRP = 4'hF,
    MRK = 4'hA
  } ph_t;

  ph_t cur, upd;
  wire lo = ~in;

  always_ff @(posedge clk)
    cur <= reset ? R0 : upd;

  always_comb begin
    upd = R0;
    if (cur == OVF) begin
      if (in) upd = OVF;
    end else if (cur == R6) begin
      upd = in ? OVF : MRK;
    end else if (cur == R5 && lo) begin
      upd = DRP;
    end else if (lo) begin
      upd = R0;
    end else if (cur == R0) upd = R1;
    else if (cur == R1)     upd = R2;
    else if (cur == R2)     upd = R3;
    else if (cur == R3)     upd = R4;
    else if (cur == R4)     upd = R5;
    else if (cur == R5)     upd = R6;
    else if (cur == MRK || cur == DRP) upd = R1;
  end

  assign err  = !(cur != OVF);
  assign flag = (cur == MRK);
  assign disc = (cur == DRP) ? 1'b1 : 1'b0;

endmodule
