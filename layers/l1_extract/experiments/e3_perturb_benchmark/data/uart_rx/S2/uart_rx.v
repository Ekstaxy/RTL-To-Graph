`timescale 1ns / 1ps

module urx_tmr (
    input  wire        clk_i,
    input  wire        sclr,
    input  wire        ld_long,
    input  wire        ld_half,
    input  wire [15:0] div_i,
    output wire        idle_o
);
    reg  [18:0] tq = 0;
    wire [18:0] wide_div = {3'b000, div_i};

    assign idle_o = ~|tq;

    always @(posedge clk_i) begin
        if (sclr)
            tq <= 19'd0;
        else if (!idle_o)
            tq <= tq + {19{1'b1}};
        else if (ld_long)
            tq <= (wide_div << 3) - 19'd1;
        else if (ld_half)
            tq <= (wide_div << 2) - 19'd2;
    end
endmodule

module urx_sipo #(
    parameter W = 8
) (
    input  wire         clk_i,
    input  wire         hold_n,
    input  wire         wipe,
    input  wire         adv,
    input  wire         s_in,
    output reg  [W-1:0] pq = 0
);
    always @(posedge clk_i) begin
        if (hold_n) begin
            if (wipe)
                pq <= {W{1'b0}};
            else if (adv)
                pq <= {s_in, pq[W-1:1]};
        end
    end
endmodule

module uart_rx #
(
    parameter DATA_WIDTH = 8
)
(
    input  wire                   clk,
    input  wire                   rst,

    output wire [DATA_WIDTH-1:0]  m_axis_tdata,
    output wire                   m_axis_tvalid,
    input  wire                   m_axis_tready,

    input  wire                   rxd,

    output wire                   busy,
    output wire                   overrun_error,
    output wire                   frame_error,

    input  wire [15:0]            prescale

);

reg                  smp = 1;
reg  [3:0]           phase_k = 0;
reg                  ack_v = 0;
reg  [DATA_WIDTH-1:0] hold_w = 0;
reg                  st_a = 0;
reg                  st_b = 0;
reg                  st_c = 0;

wire                 tick_ok;
wire [DATA_WIDTH-1:0] frag;

wire seq_live  = |phase_k;
wire t_go      = tick_ok & seq_live;
wire t_rest    = tick_ok & ~seq_live;
wire in_head   = t_go && (phase_k > DATA_WIDTH+1);
wire in_body   = t_go && !(phase_k > DATA_WIDTH+1) && (phase_k > 1);
wire in_tail   = t_go && (phase_k == 4'd1);
wire kick      = t_rest & ~smp;
wire tail_good = in_tail & smp;

assign m_axis_tdata  = hold_w;
assign m_axis_tvalid = ack_v;
assign busy          = st_a;
assign overrun_error = st_b;
assign frame_error   = st_c;

urx_tmr tm0 (
    .clk_i  (clk),
    .sclr   (rst),
    .ld_long(in_body | (in_head & ~smp)),
    .ld_half(kick),
    .div_i  (prescale),
    .idle_o (tick_ok)
);

urx_sipo #(.W(DATA_WIDTH)) sp0 (
    .clk_i (clk),
    .hold_n(~rst),
    .wipe  (kick),
    .adv   (in_body),
    .s_in  (smp),
    .pq    (frag)
);

always @(posedge clk) begin
    smp <= rst | rxd;
end

always @(posedge clk) begin
    if (rst) begin
        phase_k <= 4'd0;
    end else if (kick) begin
        phase_k <= DATA_WIDTH + 2;
    end else if (in_head && smp) begin
        phase_k <= 4'd0;
    end else if (t_go) begin
        phase_k <= phase_k - 4'd1;
    end
end

always @(posedge clk) begin
    if (rst) begin
        hold_w <= 0;
        ack_v  <= 1'b0;
        st_a   <= 1'b0;
        st_b   <= 1'b0;
        st_c   <= 1'b0;
    end else begin
        st_b <= tail_good ? ack_v : 1'b0;
        st_c <= in_tail & ~smp;
        st_a <= t_rest ? ~smp : st_a;
        if (tail_good) begin
            hold_w <= frag;
            ack_v  <= 1'b1;
        end else if (ack_v & m_axis_tready) begin
            ack_v  <= 1'b0;
        end
    end
end

endmodule
