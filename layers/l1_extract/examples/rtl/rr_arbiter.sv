// Round-robin arbiter with one-hot grant and grant hold until accepted.
module rr_arbiter #(
  parameter int N = 4
) (
  input  logic         clk,
  input  logic         rst_n,
  input  logic [N-1:0] req_i,
  output logic [N-1:0] gnt_o,
  input  logic         accept_i,
  output logic         gnt_valid_o
);
  logic [N-1:0] prio_q;      // one-hot pointer: highest priority requester
  logic [N-1:0] gnt_q, gnt_d;
  logic         locked_q;
  logic [2*N-1:0] dbl_req, dbl_gnt;

  // classic double-width priority trick
  assign dbl_req = {req_i, req_i};
  assign dbl_gnt = dbl_req & ~(dbl_req - {{N{1'b0}}, prio_q});

  always_comb begin
    gnt_d = gnt_q;
    if (!locked_q) gnt_d = dbl_gnt[N-1:0] | dbl_gnt[2*N-1:N];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prio_q   <= {{(N-1){1'b0}}, 1'b1};
      gnt_q    <= '0;
      locked_q <= 1'b0;
    end else begin
      gnt_q <= gnt_d;
      if (!locked_q && |req_i) locked_q <= 1'b1;
      else if (locked_q && accept_i) begin
        locked_q <= 1'b0;
        prio_q   <= {gnt_q[N-2:0], gnt_q[N-1]};
        gnt_q    <= '0;
      end
    end
  end

  assign gnt_o       = gnt_q;
  assign gnt_valid_o = locked_q;
endmodule
