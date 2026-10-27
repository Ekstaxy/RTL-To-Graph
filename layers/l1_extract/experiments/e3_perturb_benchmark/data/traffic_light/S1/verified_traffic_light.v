module verified_traffic_light
(
  input rst_n,
  input clk,
  input pass_request,
  output wire [7:0] clock,
  output reg red,
  output reg yellow,
  output reg green
);

localparam [1:0] BOOT = 2'b11,
                 STOP = 2'b10,
                 SLOW = 2'b00,
                 GO   = 2'b01;

reg  [1:0] lamp, lamp_nx;
reg  [7:0] tmr;
reg        hr, hy, hg;
wire       hit3;
wire       cut_short, fresh_g, fresh_y, fresh_r;

assign hit3      = ~|(tmr ^ 8'd3);
assign cut_short = pass_request & green & (tmr > 8'd10);
assign fresh_g   = ~(green | ~hg);
assign fresh_y   = ~(yellow | ~hy);
assign fresh_r   = ~(red | ~hr);

always @* begin
  lamp_nx = lamp;
  if (lamp == BOOT)
    lamp_nx = STOP;
  else if (hit3) begin
    if (lamp == STOP)    lamp_nx = GO;
    else if (lamp == GO) lamp_nx = SLOW;
    else                 lamp_nx = STOP;
  end
end

always @(posedge clk or negedge rst_n)
  if (!rst_n) lamp <= BOOT;
  else        lamp <= lamp_nx;

always @(posedge clk or negedge rst_n)
  if (!rst_n) begin
    {hr, hy, hg} <= 3'b000;
    {red, yellow, green} <= 3'b000;
  end else begin
    {red, yellow, green} <= {hr, hy, hg};
    {hr, hy, hg} <= {lamp == STOP, lamp == SLOW, lamp == GO};
  end

always @(posedge clk or negedge rst_n)
  if (!rst_n)
    tmr <= 8'd10;
  else
    tmr <= cut_short ? 8'd10 :
           fresh_g   ? 8'd60 :
           fresh_y   ? 8'd5  :
           fresh_r   ? 8'd10 :
                       tmr + 8'hff;

assign clock = tmr;
endmodule
