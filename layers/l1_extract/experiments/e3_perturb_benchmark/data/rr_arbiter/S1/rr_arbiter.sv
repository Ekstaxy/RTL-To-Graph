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
reg  [N-1:0]   cur_sel;
reg            busy_flag;
reg  [N-1:0]   tok;
wire [2*N-1:0] wide_r;
wire [2*N-1:0] wide_m;
wire [2*N-1:0] pick;
wire [N-1:0]   folded;
wire [N-1:0]   spun;
wire           any_r;

assign wide_r = {2{req_i}};
assign wide_m = ~wide_r + {{N{1'b0}}, tok};
assign pick   = wide_r & wide_m;
assign folded = pick[2*N-1:N] | pick[N-1:0];
assign spun   = (cur_sel << 1) | (cur_sel >> (N-1));
assign any_r  = ~(req_i == {N{1'b0}});

always @(posedge clk or negedge rst_n)
  if (!rst_n) begin
    busy_flag <= 1'b0;
    cur_sel   <= {N{1'b0}};
    tok       <= {{(N-1){1'b0}}, 1'b1};
  end else if (busy_flag) begin
    if (accept_i) begin
      busy_flag <= 1'b0;
      tok       <= spun;
      cur_sel   <= {N{1'b0}};
    end
  end else begin
    cur_sel   <= folded;
    busy_flag <= any_r;
  end

assign gnt_valid_o = busy_flag;
assign gnt_o       = cur_sel;
endmodule
