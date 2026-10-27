module rr_pick #(
  parameter int K = 4
) (
  input  logic [K-1:0] ask,
  input  logic [K-1:0] lead,
  output logic [K-1:0] win
);
  logic [2*K-1:0] twin_ask;
  logic [2*K-1:0] borrow;
  logic [2*K-1:0] picked;

  assign twin_ask = {ask, ask};
  assign borrow   = twin_ask - {{K{1'b0}}, lead};
  assign picked   = ~(~twin_ask | borrow);

  genvar gj;
  generate
    for (gj = 0; gj < K; gj = gj + 1) begin : g_fold
      assign win[gj] = picked[gj] | picked[gj+K];
    end
  endgenerate
endmodule

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
  logic [N-1:0] cand;
  logic [N-1:0] token_r;
  logic [N-1:0] sel_r;
  logic         busy_r;
  logic         any_ask;
  logic         release_now;

  rr_pick #(.K(N)) u_pick (
    .ask (req_i),
    .lead(token_r),
    .win (cand)
  );

  assign any_ask     = |req_i;
  assign release_now = busy_r && accept_i;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      busy_r <= 1'b0;
    else if (~busy_r)
      busy_r <= busy_r | any_ask;
    else if (accept_i)
      busy_r <= 1'b0;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sel_r <= {N{1'b0}};
    end else begin
      if (release_now)
        sel_r <= {N{1'b0}};
      else if (!busy_r)
        sel_r <= cand;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      token_r <= {{(N-1){1'b0}}, 1'b1};
    else if (release_now)
      token_r <= {sel_r[N-2:0], sel_r[N-1]};
  end

  assign gnt_o       = sel_r;
  assign gnt_valid_o = busy_r;
endmodule
