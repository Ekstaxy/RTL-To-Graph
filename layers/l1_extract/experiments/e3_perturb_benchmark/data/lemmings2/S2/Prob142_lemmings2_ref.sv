module lm_step_unit (
  input  [1:0] cur,
  input        g,
  input        hit_a,
  input        hit_b,
  output reg [1:0] nxt
);
  localparam [1:0] PH_A = 2'b11, PH_B = 2'b10, PH_C = 2'b01, PH_D = 2'b00;

  always_comb begin
    nxt = cur;
    if (!g) begin
      if (cur == PH_A) nxt = PH_C;
      else if (cur == PH_B) nxt = PH_D;
    end else begin
      case (cur)
        PH_A: nxt = hit_a ? PH_B : PH_A;
        PH_B: nxt = (~hit_b) ? PH_B : PH_A;
        PH_C: nxt = PH_A;
        default: nxt = PH_B;
      endcase
    end
  end
endmodule

module lm_core (
  input  ck,
  input  rst_a,
  input  [2:0] sense,
  output [2:0] act
);
  localparam [1:0] PH_A = 2'b11;
  reg  [1:0] ph;
  wire [1:0] ph_n;

  function [2:0] dec_ph;
    input [1:0] v;
    begin
      dec_ph[2] = v[1] & v[0];
      dec_ph[1] = v[1] & ~v[0];
      dec_ph[0] = ~v[1];
    end
  endfunction

  lm_step_unit u_step (
    .cur(ph),
    .g(sense[0]),
    .hit_a(sense[2]),
    .hit_b(sense[1]),
    .nxt(ph_n)
  );

  always_ff @(posedge ck or posedge rst_a) begin
    if (rst_a) ph <= PH_A;
    else ph <= ph_n;
  end

  assign act = dec_ph(ph);
endmodule

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

  wire [2:0] w_out;

  lm_core u_core (
    .ck(clk),
    .rst_a(areset),
    .sense({bump_left, bump_right, ground}),
    .act(w_out)
  );

  assign {walk_left, walk_right, aaah} = w_out;

endmodule
