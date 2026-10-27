module sync_fifo #(
  parameter int WIDTH = 32,
  parameter int DEPTH = 8
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             flush_i,
  input  logic             in_valid,
  output logic             in_ready,
  input  logic [WIDTH-1:0] in_data,
  output logic             out_valid,
  input  logic             out_ready,
  output logic [WIDTH-1:0] out_data,
  output logic [$clog2(DEPTH):0] count_o
);
localparam int PW = $clog2(DEPTH);

reg  [PW:0]          lvl;
reg  [PW-1:0]        hd;
reg  [PW-1:0]        tl;
reg  [WIDTH*DEPTH-1:0] bank;
wire                 ins, rem, nfull, nempty;
wire [1:0]           act;

assign nfull  = ~(lvl == DEPTH);
assign nempty = |lvl;
assign ins    = ~(~in_valid | ~nfull);
assign rem    = nempty & out_ready;
assign act    = {ins, rem};

always @(posedge clk)
  if (ins) bank[tl*WIDTH +: WIDTH] <= in_data;

always @(posedge clk or negedge rst_n)
  if (!rst_n)       tl <= {PW{1'b0}};
  else if (flush_i) tl <= {PW{1'b0}};
  else if (ins)     tl <= tl + 1'b1;

always @(posedge clk or negedge rst_n)
  if (!rst_n)       hd <= {PW{1'b0}};
  else if (flush_i) hd <= {PW{1'b0}};
  else              hd <= rem ? hd + 1'b1 : hd;

always @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
    lvl <= 0;
  end else if (flush_i) begin
    lvl <= {(PW+1){1'b0}};
  end else if (act == 2'b10) begin
    lvl <= lvl + 1'b1;
  end else if (act == 2'b01) begin
    lvl <= lvl - 1'b1;
  end
end

assign out_data  = bank[hd*WIDTH +: WIDTH];
assign count_o   = lvl;
assign in_ready  = nfull;
assign out_valid = nempty;
endmodule
