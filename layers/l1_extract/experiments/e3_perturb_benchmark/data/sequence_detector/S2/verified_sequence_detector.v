module sd_route (
    input  wire [2:0] here,
    input  wire       b,
    input  wire       live,
    output reg  [2:0] there
);
    localparam [2:0] P_ZERO = 3'b011,
                     P_ONE  = 3'b110,
                     P_TWO  = 3'b101,
                     P_TRI  = 3'b000,
                     P_HIT  = 3'b111;

    always @(*) begin
        there = P_ZERO;
        if (!live)
            there = P_ZERO;
        else if (here == P_ZERO || here == P_TRI)
            there = b ? ((here == P_TRI) ? P_HIT : P_ONE) : P_ZERO;
        else if (here == P_ONE || here == P_HIT)
            there = b ? P_ONE : P_TWO;
        else if (here == P_TWO)
            there = b ? P_ONE : P_TRI;
    end
endmodule

module sequence_detector(
     input  clk,
     input  rst_n,
     input  data_in,
     output sequence_detected
     );

    localparam [2:0] Q_INIT = 3'b011;
    localparam [2:0] Q_MATCH = 3'b111;

    reg  [2:0] ph_r;
    wire [2:0] ph_d;
    wire       eq_w;

    sd_route rt (
        .here (ph_r),
        .b    (data_in),
        .live (rst_n),
        .there(ph_d)
    );

    always @(posedge clk or negedge rst_n)
        if (~rst_n) ph_r <= Q_INIT;
        else        ph_r <= ph_d;

    assign eq_w = &(ph_r ~^ Q_MATCH);
    assign sequence_detected = eq_w;
endmodule
