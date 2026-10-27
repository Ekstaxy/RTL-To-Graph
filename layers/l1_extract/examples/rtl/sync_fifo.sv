// Synchronous FIFO with valid/ready on both sides.
module sync_fifo #(
  parameter int WIDTH = 32,
  parameter int DEPTH = 8
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             flush_i,
  // write side
  input  logic             in_valid,
  output logic             in_ready,
  input  logic [WIDTH-1:0] in_data,
  // read side
  output logic             out_valid,
  input  logic             out_ready,
  output logic [WIDTH-1:0] out_data,
  output logic [$clog2(DEPTH):0] count_o
);
  localparam int AW = $clog2(DEPTH);

  logic [WIDTH-1:0] mem_q [DEPTH];
  logic [AW-1:0]    wptr_q, rptr_q;
  logic [AW:0]      count_q;
  logic             do_push, do_pop;

  assign in_ready  = (count_q != DEPTH);
  assign out_valid = (count_q != 0);
  assign do_push   = in_valid && in_ready;
  assign do_pop    = out_valid && out_ready;
  assign out_data  = mem_q[rptr_q];
  assign count_o   = count_q;

  always_ff @(posedge clk) begin
    if (do_push) mem_q[wptr_q] <= in_data;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr_q  <= '0;
      rptr_q  <= '0;
      count_q <= '0;
    end else if (flush_i) begin
      wptr_q  <= '0;
      rptr_q  <= '0;
      count_q <= '0;
    end else begin
      if (do_push) wptr_q <= wptr_q + 1'b1;
      if (do_pop)  rptr_q <= rptr_q + 1'b1;
      case ({do_push, do_pop})
        2'b10:   count_q <= count_q + 1'b1;
        2'b01:   count_q <= count_q - 1'b1;
        default: count_q <= count_q;
      endcase
    end
  end
endmodule
