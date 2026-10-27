module sequence_detector(
     input  clk,
     input  rst_n,
     input  data_in,
     output sequence_detected
     );

`define SQD_A 3'b101
`define SQD_B 3'b011
`define SQD_C 3'b110
`define SQD_D 3'b000
`define SQD_E 3'b010

reg  [2:0] pos;
wire       b = data_in;
wire       on_e = (pos == `SQD_E);

always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        pos <= `SQD_A;
    else if (pos == `SQD_D && b)
        pos <= `SQD_E;
    else if (b)
        pos <= `SQD_B;
    else if (pos == `SQD_B || on_e)
        pos <= `SQD_C;
    else if (pos == `SQD_C)
        pos <= `SQD_D;
    else
        pos <= `SQD_A;
end

assign sequence_detected = on_e & 1'b1;

endmodule
