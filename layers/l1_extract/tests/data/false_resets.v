// Signals that look like sync resets but are not (low-power coding, FSM-driven clears).
module false_resets (
    input  wire       clk,
    input  wire       i_reset,
    input  wire       i_valid,
    input  wire [7:0] i_data,
    output reg        o_valid,
    output reg  [7:0] o_data,
    output reg  [7:0] crc
);
    reg [1:0] st = 2'd0;
    wire reset_crc = (st == 2'd0);
    always @(posedge clk) begin
        if (i_reset) o_valid <= 1'b0;
        else o_valid <= i_valid;
    end
    always @(posedge clk) begin
        if (!i_valid) o_data <= 8'd0;  // low-power clear, not a reset
        else o_data <= i_data;
    end
    always @(posedge clk) begin
        if (i_reset) st <= 2'd0;
        else st <= st + 2'd1;
    end
    always @(posedge clk) begin
        if (reset_crc) crc <= 8'hff;    // FSM-driven clear, not a reset
        else crc <= crc ^ i_data;
    end
endmodule

module fr_child (input wire clk, input wire rst, input wire [7:0] d, output reg [7:0] q);
    always @(posedge clk) begin
        if (rst) q <= 8'd0;
        else q <= d;
    end
endmodule

// a child's reset driven by an expression, and a compound condition containing the reset
module false_resets2 (
    input  wire       clk,
    input  wire       i_reset,
    input  wire       i_valid,
    input  wire       i_stall,
    input  wire [7:0] i_data,
    output wire [7:0] o,
    output reg  [7:0] r
);
    fr_child u (.clk(clk), .rst(i_reset || !i_valid), .d(i_data), .q(o));
    always @(posedge clk) begin
        if (i_reset) r <= 8'd0;
        else if (!i_stall) r <= i_data;
    end
    always @(posedge clk) begin
        if (i_reset || !i_stall) r <= 8'd0;
    end
endmodule
