`timescale 1ns / 1ps

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

reg [3:0] ph = 0;
reg [18:0] tk = 0;
reg smp = 1;
reg [DATA_WIDTH-1:0] acc = 0;
reg [DATA_WIDTH-1:0] latch_q = 0;
reg vq = 0;
reg act = 0;
reg e_ov = 0;
reg e_fr = 0;
reg [3:0] ph_echo = 0;

wire tk_live  = |tk;
wire ph_live  = ~(ph == 4'd0);
wire hdr      = ph > (DATA_WIDTH+1);
wire mid      = !hdr && (ph > 4'd1);
wire tail     = (ph == 4'd1);
wire step     = !tk_live && ph_live;
wire park     = !(tk_live || ph_live);
wire fin_ok   = step & tail & smp;
wire fin_bad  = step & tail & ~smp;
wire [18:0] rl_long  = {prescale, 3'b000} - 19'd1;
wire [18:0] rl_short = {1'b0, prescale, 2'b00} - 19'd2;

assign m_axis_tdata  = latch_q;
assign m_axis_tvalid = vq;
assign busy          = act;
assign overrun_error = e_ov;
assign frame_error   = e_fr;

always @(posedge clk) begin
    if (rst) smp <= 1'b1;
    else     smp <= rxd;
end

always @(posedge clk) begin
    if (rst) begin
        tk <= 19'd0;
    end else if (tk_live) begin
        tk <= tk + 19'h7FFFF;
    end else if (ph_live) begin
        if (hdr && smp)
            tk <= 19'd0;
        else if (hdr || mid)
            tk <= rl_long;
    end else if (~smp) begin
        tk <= rl_short;
    end
end

always @(posedge clk) begin
    if (rst) begin
        ph <= 4'd0;
        ph_echo <= 4'd0;
    end else begin
        ph_echo <= ph;
        if (step)
            ph <= (hdr && smp) ? 4'd0 : ph - 4'd1;
        else if (park && !smp)
            ph <= DATA_WIDTH + 2;
    end
end

always @(posedge clk) begin
    if (!rst) begin
        if (step && mid)
            acc <= {smp, acc[DATA_WIDTH-1:1]};
        else if (park && !smp)
            acc <= {DATA_WIDTH{1'b0}};
    end
end

always @(posedge clk) begin
    if (rst) begin
        latch_q <= 0;
        vq <= 1'b0;
        e_ov <= 1'b0;
        e_fr <= 1'b0;
        act <= 1'b0;
    end else begin
        latch_q <= fin_ok ? acc : latch_q;
        vq <= fin_ok | (vq & ~m_axis_tready);
        e_ov <= fin_ok & vq;
        e_fr <= fin_bad;
        if (park) act <= ~smp;
    end
end

endmodule
