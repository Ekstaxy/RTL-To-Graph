module dead_branch #(parameter S = 2, parameter M = 2) (
    input  wire       clk,
    input  wire [7:0] d,
    input  wire       go,
    output reg  [7:0] q
);
    localparam SEG = M / S;
    reg [1:0] st_reg = 2'd0, st_next;
    reg [7:0] buf_reg = 8'd0, buf_next;
    always @* begin
        st_next = st_reg;
        buf_next = buf_reg;
        if (SEG == 1) begin
            case (st_reg)
                2'd0: if (go) st_next = 2'd1;
                2'd1: begin buf_next = d; st_next = 2'd2; end
                default: st_next = 2'd0;
            endcase
        end else begin
            buf_next[S-1:M] = d[S-1:M];
        end
    end
    always @(posedge clk) begin
        st_reg <= st_next;
        buf_reg <= buf_next;
        q <= buf_reg;
    end
endmodule
