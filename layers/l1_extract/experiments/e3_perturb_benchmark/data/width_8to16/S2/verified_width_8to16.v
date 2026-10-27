`timescale 1ns/1ns

module w8_phase_hold (
    input  wire       ck,
    input  wire       arst_b,
    input  wire       stb,
    input  wire [7:0] bus_i,
    output reg  [7:0] hi_byte,
    output reg        odd_q
);
    wire grab_w = stb & ~odd_q;

    always @(posedge ck or negedge arst_b) begin
        if (~arst_b) begin
            odd_q   <= 1'b0;
            hi_byte <= 8'h00;
        end else begin
            if (grab_w)
                hi_byte <= bus_i;
            if (stb == 1'b1)
                odd_q <= !odd_q;
        end
    end
endmodule

module verified_width_8to16(
	input 				   clk 		,
	input 				   rst_n		,
	input				      valid_in	,
	input	   [7:0]		   data_in	,

 	output	reg			valid_out,
	output   reg [15:0]	data_out
);
    wire [7:0] u_pending;
    wire       u_parity;
    wire       fire_k;
    wire       spare_tap;

    assign fire_k    = ~(~valid_in | ~u_parity);
    assign spare_tap = fire_k & 1'b1;

    w8_phase_hold u_ph (
        .ck     (clk),
        .arst_b (rst_n),
        .stb    (valid_in),
        .bus_i  (data_in),
        .hi_byte(u_pending),
        .odd_q  (u_parity)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            data_out  <= 16'd0;
            valid_out <= 1'b0;
        end else begin
            valid_out <= spare_tap ? 1'b1 : 1'b0;
            data_out  <= fire_k ? {u_pending, data_in} : data_out;
        end
    end
endmodule
