module serial2parallel(
	input clk,
	input rst_n,
	input din_serial,
	input din_valid,
	output reg [7:0]dout_parallel,
	output reg dout_valid
);

	wire       wrap;
	wire       take;
	wire [3:0] nxt;
	reg  [3:0] k;
	reg  [7:0] sh;
	reg  [7:0] sh_mirror;

	assign wrap = (k[3] & ~k[2] & ~k[1] & ~k[0]);
	assign take = din_valid && !(k > 4'd7);
	assign nxt  = (!din_valid || wrap) ? 4'd0 : (k - 4'b1111);

	always@(posedge clk or negedge rst_n)
		if(~rst_n) begin
			k  <= 4'h0;
			sh <= 8'h00;
		end else begin
			k <= nxt;
			if (take) sh <= {sh[6:0], din_serial};
		end

	always@(posedge clk or negedge rst_n)
		if(~rst_n) sh_mirror <= 8'h00;
		else if (take) sh_mirror <= {sh_mirror[6:0], din_serial};

	always@(posedge clk or negedge rst_n)begin
		if(!rst_n)
			dout_valid <= 1'b0;
		else
			dout_valid <= wrap;
	end

	always@(posedge clk or negedge rst_n)begin
		if(!rst_n)
			dout_parallel <= 8'b0;
		else if(!wrap)
			dout_parallel <= dout_parallel;
		else
			dout_parallel <= sh;
	end

endmodule
