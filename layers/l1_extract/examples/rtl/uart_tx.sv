// UART transmitter: 8N1, valid/ready input, configurable baud divider.
module uart_tx #(
  parameter int CLK_DIV = 16
) (
  input  logic       clk,
  input  logic       rst_n,
  input  logic       tx_valid,
  output logic       tx_ready,
  input  logic [7:0] tx_data,
  output logic       tx_o,
  output logic       busy_o
);
  typedef enum logic [1:0] {S_IDLE, S_START, S_DATA, S_STOP} state_t;
  state_t state_q, state_d;

  logic [$clog2(CLK_DIV)-1:0] baud_cnt_q;
  logic                       baud_tick;
  logic [2:0]                 bit_idx_q;
  logic [7:0]                 shift_q;

  assign baud_tick = (baud_cnt_q == CLK_DIV - 1);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) baud_cnt_q <= '0;
    else if (state_q == S_IDLE || baud_tick) baud_cnt_q <= '0;
    else baud_cnt_q <= baud_cnt_q + 1'b1;
  end

  always_comb begin
    state_d = state_q;
    unique case (state_q)
      S_IDLE:  if (tx_valid) state_d = S_START;
      S_START: if (baud_tick) state_d = S_DATA;
      S_DATA:  if (baud_tick && bit_idx_q == 3'd7) state_d = S_STOP;
      S_STOP:  if (baud_tick) state_d = S_IDLE;
    endcase
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state_q   <= S_IDLE;
      bit_idx_q <= '0;
      shift_q   <= '0;
    end else begin
      state_q <= state_d;
      if (state_q == S_IDLE && tx_valid) begin
        shift_q   <= tx_data;
        bit_idx_q <= '0;
      end else if (state_q == S_DATA && baud_tick) begin
        shift_q   <= {1'b0, shift_q[7:1]};
        bit_idx_q <= bit_idx_q + 3'd1;
      end
    end
  end

  assign tx_ready = (state_q == S_IDLE);
  assign busy_o   = (state_q != S_IDLE);

  always_comb begin
    case (state_q)
      S_START: tx_o = 1'b0;
      S_DATA:  tx_o = shift_q[0];
      default: tx_o = 1'b1;
    endcase
  end
endmodule
