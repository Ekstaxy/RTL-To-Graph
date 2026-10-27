// Small hierarchical SoC-ish top: per-channel FIFOs (generate), an arbiter that
// picks a channel, and a UART that serializes the chosen byte.
module soc_top #(
  parameter int NCH = 4
) (
  input  logic           clk,
  input  logic           rst_n,
  input  logic [NCH-1:0] ch_valid,
  output logic [NCH-1:0] ch_ready,
  input  logic [7:0]     ch_data [NCH],
  output logic           uart_tx,
  output logic           uart_busy
);
  logic [NCH-1:0] fifo_valid, fifo_pop;
  logic [7:0]     fifo_data [NCH];
  logic [NCH-1:0] gnt;
  logic           gnt_valid, tx_ready, tx_valid;
  logic [7:0]     tx_byte;

  genvar g;
  generate
    for (g = 0; g < NCH; g++) begin : gen_ch
      sync_fifo #(.WIDTH(8), .DEPTH(4)) u_fifo (
        .clk(clk), .rst_n(rst_n), .flush_i(1'b0),
        .in_valid(ch_valid[g]), .in_ready(ch_ready[g]), .in_data(ch_data[g]),
        .out_valid(fifo_valid[g]), .out_ready(fifo_pop[g]), .out_data(fifo_data[g]),
        .count_o()
      );
    end
  endgenerate

  rr_arbiter #(.N(NCH)) u_arb (
    .clk(clk), .rst_n(rst_n), .req_i(fifo_valid), .gnt_o(gnt),
    .accept_i(tx_valid && tx_ready), .gnt_valid_o(gnt_valid)
  );

  // one-hot mux of the granted channel
  always_comb begin
    tx_byte = '0;
    for (int i = 0; i < NCH; i++) if (gnt[i]) tx_byte = fifo_data[i];
  end

  assign tx_valid = gnt_valid;
  assign fifo_pop = gnt & {NCH{tx_ready && tx_valid}};

  uart_tx #(.CLK_DIV(8)) u_uart (
    .clk(clk), .rst_n(rst_n), .tx_valid(tx_valid), .tx_ready(tx_ready),
    .tx_data(tx_byte), .tx_o(uart_tx), .busy_o(uart_busy)
  );
endmodule
