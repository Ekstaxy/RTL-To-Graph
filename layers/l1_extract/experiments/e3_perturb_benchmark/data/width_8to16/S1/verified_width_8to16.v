`timescale 1ns/1ns
module verified_width_8to16(
	input 				   clk 		,
	input 				   rst_n		,
	input				      valid_in	,
	input	   [7:0]		   data_in	,

 	output	reg			valid_out,
	output   reg [15:0]	data_out
);

wire        arm_n;
wire        hit;

reg         phz;
reg  [7:0]  hi_q;
reg  [7:0]  hi_q_dup;
reg  [15:0] pk;

assign hit   = valid_in & phz & 1'b1;
assign arm_n = ~valid_in | phz;

always @(*) begin
	pk = {hi_q, data_in};
end

always @(posedge clk or negedge rst_n) begin
	if (~rst_n) begin
		phz       <= 1'b0;
		valid_out <= 1'b0;
	end else begin
		phz       <= valid_in ? !phz : phz;
		valid_out <= hit ? 1'b1 : 1'b0;
	end
end

always @(posedge clk or negedge rst_n) begin
	if (!rst_n) begin
		hi_q     <= 8'h00;
		hi_q_dup <= 8'h00;
	end else if (!arm_n) begin
		hi_q     <= data_in;
		hi_q_dup <= ~(~data_in);
	end
end

always @(posedge clk or negedge rst_n)
	if (!rst_n)
		data_out <= 16'd0;
	else
		data_out <= (hit) ? pk : data_out;

endmodule
