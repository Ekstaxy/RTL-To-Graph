MODULE: sync_fifo
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=2 ctrl_fanout=0 addr_fanout=0 | CLOCK | L66
E2 | rst_n | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | RESET | L67
E3 | flush_i | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | RESET | L68
E4 | in_valid | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L69
E5 | in_ready | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L70
E6 | in_data | port_in | 32b | logic[31:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L71
E7 | out_valid | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L72
E8 | out_ready | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L73
E9 | out_data | port_out | 32b | logic[31:0] | driven_by=inst_out | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L74
E10 | count_o | port_out | 4b | logic[3:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L75
E11 | lvl | wire | 4b | logic[3:0] | driven_by=inst_out | fanin=1 fanout=3 ctrl_fanout=0 addr_fanout=0 | - | L79
E12 | rd_at | wire | 3b | logic[2:0] | driven_by=inst_out | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L80
E13 | wr_at | wire | 3b | logic[2:0] | driven_by=inst_out | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L80
E14 | take | wire | 1b | logic | driven_by=assign | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L81
E15 | give | wire | 1b | logic | driven_by=assign | fanin=2 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L81
E16 | brim | wire | 1b | logic | driven_by=assign | fanin=1 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L82
E17 | dry | wire | 1b | logic | driven_by=assign | fanin=1 fanout=2 ctrl_fanout=0 addr_fanout=0 | - | L82
I1 | u_ctl | inst of sf_ctl | fanin=5 fanout=3 | L92
I2 | u_bank | inst of sf_bank | fanin=5 fanout=1 | L103

CHILD SUMMARIES:
I1 u_ctl: sf_ctl -- FIFO pointer controller: push/pop strobes advance write (tail) and read (head) pointers and update an occupancy count by a signed delta.
    interface clock_reset: CLOCK_RESET IN
    interface push_pop: SIMPLE IN
    interface pointers_out: SIMPLE OUT
    key internals: head(FIFO_PTR), tail(FIFO_PTR), fill(FIFO_PTR)
I2 u_bank: sf_bank -- Small register-file memory: flattened D x W array written synchronously per row on we/wa match, read asynchronously by ra slice.
    interface clock: CLOCK_RESET IN
    interface write_port: MEMORY_BUS IN
    interface read_port: MEMORY_BUS OUT
    key internals: wd(INTERFACE_DATA), rd(INTERFACE_DATA), slab(STORAGE)

RTL (line-numbered):
  62| module sync_fifo #(
  63|   parameter int WIDTH = 32,
  64|   parameter int DEPTH = 8
  65| ) (
  66|   input  logic             clk,
  67|   input  logic             rst_n,
  68|   input  logic             flush_i,
  69|   input  logic             in_valid,
  70|   output logic             in_ready,
  71|   input  logic [WIDTH-1:0] in_data,
  72|   output logic             out_valid,
  73|   input  logic             out_ready,
  74|   output logic [WIDTH-1:0] out_data,
  75|   output logic [$clog2(DEPTH):0] count_o
  76| );
  77|   localparam int PW = $clog2(DEPTH);
  78| 
  79|   logic [PW:0]   lvl;
  80|   logic [PW-1:0] rd_at, wr_at;
  81|   logic          take, give;
  82|   logic          brim, dry;
  83| 
  84|   assign brim      = (lvl == DEPTH);
  85|   assign dry       = ~|lvl;
  86|   assign in_ready  = ~brim;
  87|   assign out_valid = !dry;
  88|   assign give      = ~(~in_valid | brim);
  89|   assign take      = out_ready & ~dry;
  90|   assign count_o   = lvl;
  91| 
  92|   sf_ctl #(.D(DEPTH), .A(PW)) u_ctl (
  93|     .clk  (clk),
  94|     .rst_n(rst_n),
  95|     .clr  (flush_i),
  96|     .inc  (give),
  97|     .dec  (take),
  98|     .head (rd_at),
  99|     .tail (wr_at),
 100|     .fill (lvl)
 101|   );
 102| 
 103|   sf_bank #(.W(WIDTH), .D(DEPTH), .A(PW)) u_bank (
 104|     .clk(clk),
 105|     .we (give),
 106|     .wa (wr_at),
 107|     .wd (in_data),
 108|     .ra (rd_at),
 109|     .rd (out_data)
 110|   );
 111| endmodule