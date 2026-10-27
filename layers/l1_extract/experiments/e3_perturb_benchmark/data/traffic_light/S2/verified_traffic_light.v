`timescale 1ns/1ns

module tl_timer
    (
        input            ck,
        input            nrst,
        input            ped,
        input            g_now,
        input            y_now,
        input            r_now,
        input            g_pre,
        input            y_pre,
        input            r_pre,
        output reg [7:0] ticks
    );

    wire cut_short;
    wire g_fall, y_fall, r_fall;

    assign cut_short = ped & g_now & (ticks > 8'd10);
    assign g_fall    = ~(g_now | ~g_pre);
    assign y_fall    = ~(y_now | ~y_pre);
    assign r_fall    = ~(r_now | ~r_pre);

    always @(posedge ck or negedge nrst)
        if (!nrst)
            ticks <= 8'd10;
        else
            case (1'b1)
                cut_short: ticks <= 8'd10;
                g_fall:    ticks <= 8'd60;
                y_fall:    ticks <= 8'd5;
                r_fall:    ticks <= 8'd10;
                default:   ticks <= ticks + 8'hFF;
            endcase
endmodule

module verified_traffic_light
    (
        input rst_n,
        input clk,
        input pass_request,
        output wire[7:0]clock,
        output reg red,
        output reg yellow,
        output reg green
    );

    localparam [3:0] PH_OFF  = 4'b1000,
                     PH_STOP = 4'b0100,
                     PH_WARN = 4'b0010,
                     PH_GO   = 4'b0001;

    reg  [3:0] lamp_sel, lamp_sel_nx;
    reg        ahead_r, ahead_y, ahead_g;
    wire [7:0] remain;
    wire       expired;

    assign expired = (remain == 8'd3);

    tl_timer u_timer
        (
            .ck   (clk),
            .nrst (rst_n),
            .ped  (pass_request),
            .g_now(green),
            .y_now(yellow),
            .r_now(red),
            .g_pre(ahead_g),
            .y_pre(ahead_y),
            .r_pre(ahead_r),
            .ticks(remain)
        );

    always @(*) begin
        lamp_sel_nx = lamp_sel;
        if (lamp_sel[3])
            lamp_sel_nx = PH_STOP;
        else if (lamp_sel[2] && expired)
            lamp_sel_nx = PH_GO;
        else if (lamp_sel[1] && expired)
            lamp_sel_nx = PH_STOP;
        else if (lamp_sel[0] && expired)
            lamp_sel_nx = PH_WARN;
    end

    always @(posedge clk or negedge rst_n)
        if (!rst_n) begin
            lamp_sel <= PH_OFF;
            ahead_r  <= 1'b0;
            ahead_y  <= 1'b0;
            ahead_g  <= 1'b0;
        end else begin
            lamp_sel <= lamp_sel_nx;
            {ahead_r, ahead_y, ahead_g} <= lamp_sel[2:0];
        end

    always @(posedge clk or negedge rst_n)
        if (!rst_n)
            {red, yellow, green} <= 3'b000;
        else
            {red, yellow, green} <= {ahead_r, ahead_y, ahead_g};

    assign clock = remain;
endmodule
