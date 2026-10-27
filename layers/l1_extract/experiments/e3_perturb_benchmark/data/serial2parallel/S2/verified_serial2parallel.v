module s2p_tick (
    input  wire       c,
    input  wire       rb,
    input  wire       en,
    output reg  [3:0] pos,
    output wire       wrap
);
    assign wrap = (pos == 4'b1000);

    always @(posedge c or negedge rb) begin
        if (rb == 1'b0)
            pos <= 4'h0;
        else if (en && !wrap)
            pos <= pos - 4'hF;
        else
            pos <= 4'h0;
    end
endmodule

module s2p_shreg (
    input  wire       c,
    input  wire       rb,
    input  wire       shift_en,
    input  wire       bit_in,
    output reg  [7:0] word
);
    always @(posedge c or negedge rb) begin
        if (!rb)
            word <= {8{1'b0}};
        else if (shift_en)
            word <= {word[6:0], bit_in};
    end
endmodule

module serial2parallel(
	input clk,
	input rst_n,
	input din_serial,
	input din_valid,
	output reg [7:0]dout_parallel,
	output reg dout_valid
);
    wire [3:0] beat;
    wire       full_k;
    wire [7:0] acc_bus;
    wire       low_half;

    assign low_half = ~beat[3];

    s2p_tick ctr0 (
        .c   (clk),
        .rb  (rst_n),
        .en  (din_valid),
        .pos (beat),
        .wrap(full_k)
    );

    s2p_shreg sr0 (
        .c       (clk),
        .rb      (rst_n),
        .shift_en(din_valid & low_half),
        .bit_in  (din_serial),
        .word    (acc_bus)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            dout_valid <= 1'b0;
        else
            dout_valid <= full_k;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            dout_parallel <= 8'b0;
        else if (full_k)
            dout_parallel <= acc_bus;
    end
endmodule
