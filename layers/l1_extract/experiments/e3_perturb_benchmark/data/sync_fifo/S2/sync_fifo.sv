module sf_bank #(
  parameter int W = 8,
  parameter int D = 4,
  parameter int A = 2
) (
  input  logic         clk,
  input  logic         we,
  input  logic [A-1:0] wa,
  input  logic [W-1:0] wd,
  input  logic [A-1:0] ra,
  output logic [W-1:0] rd
);
  logic [D*W-1:0] slab;

  genvar gi;
  generate
    for (gi = 0; gi < D; gi = gi + 1) begin : g_row
      always_ff @(posedge clk) begin
        if (we && (wa == gi)) slab[gi*W +: W] <= wd;
      end
    end
  endgenerate

  assign rd = slab[ra*W +: W];
endmodule

module sf_ctl #(
  parameter int D = 4,
  parameter int A = 2
) (
  input  logic         clk,
  input  logic         rst_n,
  input  logic         clr,
  input  logic         inc,
  input  logic         dec,
  output logic [A-1:0] head,
  output logic [A-1:0] tail,
  output logic [A:0]   fill
);
  logic [A:0] delta;

  assign delta = {(A+1){dec & ~inc}} | {{A{1'b0}}, inc ^ dec};

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      head <= {A{1'b0}};
      tail <= {A{1'b0}};
      fill <= {(A+1){1'b0}};
    end else begin
      if (clr) begin
        head <= {A{1'b0}};
        tail <= {A{1'b0}};
      end else begin
        if (inc) tail <= tail + 1'b1;
        if (dec) head <= head + 1'b1;
      end
      fill <= clr ? {(A+1){1'b0}} : fill + delta;
    end
  end
endmodule

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

  logic [PW:0]   lvl;
  logic [PW-1:0] rd_at, wr_at;
  logic          take, give;
  logic          brim, dry;

  assign brim      = (lvl == DEPTH);
  assign dry       = ~|lvl;
  assign in_ready  = ~brim;
  assign out_valid = !dry;
  assign give      = ~(~in_valid | brim);
  assign take      = out_ready & ~dry;
  assign count_o   = lvl;

  sf_ctl #(.D(DEPTH), .A(PW)) u_ctl (
    .clk  (clk),
    .rst_n(rst_n),
    .clr  (flush_i),
    .inc  (give),
    .dec  (take),
    .head (rd_at),
    .tail (wr_at),
    .fill (lvl)
  );

  sf_bank #(.W(WIDTH), .D(DEPTH), .A(PW)) u_bank (
    .clk(clk),
    .we (give),
    .wa (wr_at),
    .wd (in_data),
    .ra (rd_at),
    .rd (out_data)
  );
endmodule
