MODULE: axis_async_fifo
DETAIL: full (importance tiers drive the coarser views)

ENTITY TABLE:
id | name | kind | size | type | driven_by | fan | flags | line
E1 | s_clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=28 ctrl_fanout=0 addr_fanout=0 | CLOCK | L97
E2 | s_rst | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=21 ctrl_fanout=0 addr_fanout=0 | RESET | L98
E3 | s_axis_tdata | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L99
E4 | s_axis_tkeep | port_in | 1b | logic[0:0] | driven_by=port_in | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L100
E5 | s_axis_tvalid | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=15 ctrl_fanout=15 addr_fanout=0 | - | L101
E6 | s_axis_tready | port_out | 1b | logic | driven_by=assign | fanin=3 fanout=15 ctrl_fanout=15 addr_fanout=0 | - | L102
E7 | s_axis_tlast | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=16 ctrl_fanout=14 addr_fanout=0 | - | L103
E8 | s_axis_tid | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L104
E9 | s_axis_tdest | port_in | 8b | logic[7:0] | driven_by=port_in | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L105
E10 | s_axis_tuser | port_in | 1b | logic[0:0] | driven_by=port_in | fanin=0 fanout=10 ctrl_fanout=9 addr_fanout=0 | - | L106
E11 | m_clk | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=29 ctrl_fanout=0 addr_fanout=0 | CLOCK | L111
E12 | m_rst | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=22 ctrl_fanout=0 addr_fanout=0 | RESET | L112
E13 | m_axis_tdata | port_out | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L113
E14 | m_axis_tkeep | port_out | 1b | logic[0:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L114
E15 | m_axis_tvalid | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L115
E16 | m_axis_tready | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L116
E17 | m_axis_tlast | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L117
E18 | m_axis_tid | port_out | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L118
E19 | m_axis_tdest | port_out | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L119
E20 | m_axis_tuser | port_out | 1b | logic[0:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L120
E21 | s_pause_req | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L125
E22 | s_pause_ack | port_out | 1b | logic | driven_by=assign | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L126
E23 | m_pause_req | port_in | 1b | logic | driven_by=port_in | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L127
E24 | m_pause_ack | port_out | 1b | logic | driven_by=assign | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L128
E25 | s_status_depth | port_out | 13b | logic[12:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L133
E26 | s_status_depth_commit | port_out | 13b | logic[12:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L134
E27 | s_status_overflow | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L135
E28 | s_status_bad_frame | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L136
E29 | s_status_good_frame | port_out | 1b | logic | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L137
E30 | m_status_depth | port_out | 13b | logic[12:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L138
E31 | m_status_depth_commit | port_out | 13b | logic[12:0] | driven_by=assign | fanin=1 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L139
E32 | m_status_overflow | port_out | 1b | logic | driven_by=assign | fanin=2 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L140
E33 | m_status_bad_frame | port_out | 1b | logic | driven_by=assign | fanin=2 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L141
E34 | m_status_good_frame | port_out | 1b | logic | driven_by=assign | fanin=2 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L142
E35 | wr_ptr_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=13 fanout=4 ctrl_fanout=0 addr_fanout=1 | STATE | L206
E36 | wr_ptr_commit_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=13 fanout=4 ctrl_fanout=0 addr_fanout=0 | STATE | L207
E37 | wr_ptr_gray_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=13 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L208
E38 | wr_ptr_sync_commit_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=16 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L209
E39 | rd_ptr_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=9 fanout=5 ctrl_fanout=0 addr_fanout=1 | STATE | L210
E40 | rd_ptr_gray_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=9 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L211
E41 | wr_ptr_conv_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=2 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L212
E42 | rd_ptr_conv_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=2 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L213
E43 | wr_ptr_temp | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=12 fanout=4 ctrl_fanout=0 addr_fanout=0 | STATE | L215
E44 | rd_ptr_temp | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=8 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L216
E45 | wr_ptr_gray_sync1_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L219
E46 | wr_ptr_gray_sync2_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L221
E47 | wr_ptr_commit_sync_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=5 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L223
E48 | rd_ptr_gray_sync1_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L225
E49 | rd_ptr_gray_sync2_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L227
E50 | wr_ptr_update_valid_reg | reg | 1b | reg | driven_by=always_ff | fanin=13 fanout=2 ctrl_fanout=2 addr_fanout=0 | STATE | L229
E51 | wr_ptr_update_reg | reg | 1b | reg | driven_by=always_ff | fanin=13 fanout=3 ctrl_fanout=2 addr_fanout=0 | STATE | L230
E52 | wr_ptr_update_sync1_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L232
E53 | wr_ptr_update_sync2_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=1 addr_fanout=0 | STATE | L234
E54 | wr_ptr_update_sync3_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=1 addr_fanout=0 | STATE | L236
E55 | wr_ptr_update_ack_sync1_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L238
E56 | wr_ptr_update_ack_sync2_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=3 ctrl_fanout=3 addr_fanout=0 | STATE | L240
E57 | s_rst_sync1_reg | reg | 1b | reg | driven_by=always_ff | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L243
E58 | s_rst_sync2_reg | reg | 1b | reg | driven_by=always_ff | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L245
E59 | s_rst_sync3_reg | reg | 1b | reg | driven_by=always_ff | fanin=2 fanout=8 ctrl_fanout=0 addr_fanout=0 | STATE RESET | L247
E60 | m_rst_sync1_reg | reg | 1b | reg | driven_by=always_ff | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L249
E61 | m_rst_sync2_reg | reg | 1b | reg | driven_by=always_ff | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L251
E62 | m_rst_sync3_reg | reg | 1b | reg | driven_by=always_ff | fanin=2 fanout=6 ctrl_fanout=4 addr_fanout=0 | STATE RESET | L253
E63 | mem | mem | 10b x4096 | reg[9:0]$[4095:0] | driven_by=always_ff | fanin=10 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L256
E64 | mem_read_data_valid_reg | wire | 1b | reg | driven_by=- | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L257
E65 | m_axis_pipe_reg | mem | 10b x2 | reg[9:0]$[1:0] | driven_by=always_ff | fanin=5 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L260
E66 | m_axis_tvalid_pipe_reg | reg | 2b | reg[1:0] | driven_by=always_ff | fanin=8 fanout=5 ctrl_fanout=4 addr_fanout=0 | STATE | L261
E67 | full | wire | 1b | logic | driven_by=assign | fanin=2 fanout=15 ctrl_fanout=14 addr_fanout=0 | - | L265
E68 | empty | wire | 1b | logic | driven_by=assign | fanin=4 fanout=4 ctrl_fanout=4 addr_fanout=0 | - | L267
E69 | full_wr | wire | 1b | logic | driven_by=assign | fanin=2 fanout=14 ctrl_fanout=13 addr_fanout=0 | - | L269
E70 | write | wire | 1b | reg | driven_by=- | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L272
E71 | read | wire | 1b | reg | driven_by=- | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L273
E72 | store_output | wire | 1b | reg | driven_by=- | fanin=0 fanout=0 ctrl_fanout=0 addr_fanout=0 | - | L274
E73 | s_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=5 fanout=2 ctrl_fanout=1 addr_fanout=0 | STATE | L276
E74 | m_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=5 fanout=1 ctrl_fanout=1 addr_fanout=0 | STATE | L277
E75 | drop_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=10 fanout=13 ctrl_fanout=13 addr_fanout=0 | STATE | L279
E76 | mark_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=8 fanout=8 ctrl_fanout=8 addr_fanout=0 | STATE | L280
E77 | send_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=8 fanout=9 ctrl_fanout=9 addr_fanout=0 | STATE | L281
E78 | overflow_reg | reg | 1b | reg | driven_by=always_ff | fanin=9 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L282
E79 | bad_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=10 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L283
E80 | good_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=10 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L284
E81 | m_drop_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=9 fanout=5 ctrl_fanout=5 addr_fanout=0 | STATE | L286
E82 | m_terminate_frame_reg | reg | 1b | reg | driven_by=always_ff | fanin=6 fanout=3 ctrl_fanout=2 addr_fanout=0 | STATE | L287
E83 | s_depth_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L289
E84 | s_depth_commit_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L290
E85 | m_depth_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L291
E86 | m_depth_commit_reg | reg | 13b | reg[12:0] | driven_by=always_ff | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L292
E87 | overflow_sync1_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L294
E88 | overflow_sync2_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L295
E89 | overflow_sync3_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L296
E90 | overflow_sync4_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L297
E91 | bad_frame_sync1_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L298
E92 | bad_frame_sync2_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L299
E93 | bad_frame_sync3_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L300
E94 | bad_frame_sync4_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L301
E95 | good_frame_sync1_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L302
E96 | good_frame_sync2_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L303
E97 | good_frame_sync3_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=2 ctrl_fanout=0 addr_fanout=0 | STATE | L304
E98 | good_frame_sync4_reg | reg | 1b | reg | driven_by=always_ff | fanin=3 fanout=1 ctrl_fanout=0 addr_fanout=0 | STATE | L305
E99 | s_axis | wire | 10b | logic[9:0] | driven_by=assign | fanin=4 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L309
E100 | m_axis | wire | 10b | logic[9:0] | driven_by=assign | fanin=1 fanout=6 ctrl_fanout=0 addr_fanout=0 | - | L320
E101 | m_axis_tready_pipe | wire | 1b | logic | driven_by=assign | fanin=1 fanout=8 ctrl_fanout=8 addr_fanout=0 | - | L322
E102 | m_axis_tvalid_pipe | wire | 1b | logic | driven_by=assign | fanin=1 fanout=5 ctrl_fanout=4 addr_fanout=0 | - | L323
E103 | m_axis_tdata_pipe | wire | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L325
E104 | m_axis_tkeep_pipe | wire | 1b | logic[0:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L326
E105 | m_axis_tlast_pipe | wire | 1b | logic | driven_by=assign | fanin=2 fanout=3 ctrl_fanout=2 addr_fanout=0 | - | L327
E106 | m_axis_tid_pipe | wire | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L328
E107 | m_axis_tdest_pipe | wire | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L329
E108 | m_axis_tuser_pipe | wire | 1b | logic[0:0] | driven_by=assign | fanin=2 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L330
E109 | m_axis_tready_out | wire | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L332
E110 | m_axis_tvalid_out | wire | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L333
E111 | m_axis_tdata_out | wire | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L335
E112 | m_axis_tkeep_out | wire | 1b | logic[0:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L336
E113 | m_axis_tlast_out | wire | 1b | logic | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L337
E114 | m_axis_tid_out | wire | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L338
E115 | m_axis_tdest_out | wire | 8b | logic[7:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L339
E116 | m_axis_tuser_out | wire | 1b | logic[0:0] | driven_by=assign | fanin=1 fanout=1 ctrl_fanout=0 addr_fanout=0 | - | L340
E117 | pipe_ready | wire | 1b | logic | driven_by=assign | fanin=0 fanout=6 ctrl_fanout=6 addr_fanout=0 | - | L342

RTL (line-numbered):
  34| module axis_async_fifo #
  35| (
  36|     // FIFO depth in words
  37|     // KEEP_WIDTH words per cycle if KEEP_ENABLE set
  38|     // Rounded up to nearest power of 2 cycles
  39|     parameter DEPTH = 4096,
  40|     // Width of AXI stream interfaces in bits
  41|     parameter DATA_WIDTH = 8,
  42|     // Propagate tkeep signal
  43|     // If disabled, tkeep assumed to be 1'b1
  44|     parameter KEEP_ENABLE = (DATA_WIDTH>8),
  45|     // tkeep signal width (words per cycle)
  46|     parameter KEEP_WIDTH = ((DATA_WIDTH+7)/8),
  47|     // Propagate tlast signal
  48|     parameter LAST_ENABLE = 1,
  49|     // Propagate tid signal
  50|     parameter ID_ENABLE = 0,
  51|     // tid signal width
  52|     parameter ID_WIDTH = 8,
  53|     // Propagate tdest signal
  54|     parameter DEST_ENABLE = 0,
  55|     // tdest signal width
  56|     parameter DEST_WIDTH = 8,
  57|     // Propagate tuser signal
  58|     parameter USER_ENABLE = 1,
  59|     // tuser signal width
  60|     parameter USER_WIDTH = 1,
  61|     // number of RAM pipeline registers
  62|     parameter RAM_PIPELINE = 1,
  63|     // use output FIFO
  64|     // When set, the RAM read enable and pipeline clock enables are removed
  65|     parameter OUTPUT_FIFO_ENABLE = 0,
  66|     // Frame FIFO mode - operate on frames instead of cycles
  67|     // When set, m_axis_tvalid will not be deasserted within a frame
  68|     // Requires LAST_ENABLE set
  69|     parameter FRAME_FIFO = 0,
  70|     // tuser value for bad frame marker
  71|     parameter USER_BAD_FRAME_VALUE = 1'b1,
  72|     // tuser mask for bad frame marker
  73|     parameter USER_BAD_FRAME_MASK = 1'b1,
  74|     // Drop frames larger than FIFO
  75|     // Requires FRAME_FIFO set
  76|     parameter DROP_OVERSIZE_FRAME = FRAME_FIFO,
  77|     // Drop frames marked bad
  78|     // Requires FRAME_FIFO and DROP_OVERSIZE_FRAME set
  79|     parameter DROP_BAD_FRAME = 0,
  80|     // Drop incoming frames when full
  81|     // When set, s_axis_tready is always asserted
  82|     // Requires FRAME_FIFO and DROP_OVERSIZE_FRAME set
  83|     parameter DROP_WHEN_FULL = 0,
  84|     // Mark incoming frames as bad frames when full
  85|     // When set, s_axis_tready is always asserted
  86|     // Requires FRAME_FIFO to be clear
  87|     parameter MARK_WHEN_FULL = 0,
  88|     // Enable pause request input
  89|     parameter PAUSE_ENABLE = 0,
  90|     // Pause between frames
  91|     parameter FRAME_PAUSE = FRAME_FIFO
  92| )
  93| (
  94|     /*
  95|      * AXI input
  96|      */
  97|     input  wire                   s_clk,
  98|     input  wire                   s_rst,
  99|     input  wire [DATA_WIDTH-1:0]  s_axis_tdata,
 100|     input  wire [KEEP_WIDTH-1:0]  s_axis_tkeep,
 101|     input  wire                   s_axis_tvalid,
 102|     output wire                   s_axis_tready,
 103|     input  wire                   s_axis_tlast,
 104|     input  wire [ID_WIDTH-1:0]    s_axis_tid,
 105|     input  wire [DEST_WIDTH-1:0]  s_axis_tdest,
 106|     input  wire [USER_WIDTH-1:0]  s_axis_tuser,
 107| 
 108|     /*
 109|      * AXI output
 110|      */
 111|     input  wire                   m_clk,
 112|     input  wire                   m_rst,
 113|     output wire [DATA_WIDTH-1:0]  m_axis_tdata,
 114|     output wire [KEEP_WIDTH-1:0]  m_axis_tkeep,
 115|     output wire                   m_axis_tvalid,
 116|     input  wire                   m_axis_tready,
 117|     output wire                   m_axis_tlast,
 118|     output wire [ID_WIDTH-1:0]    m_axis_tid,
 119|     output wire [DEST_WIDTH-1:0]  m_axis_tdest,
 120|     output wire [USER_WIDTH-1:0]  m_axis_tuser,
 121| 
 122|     /*
 123|      * Pause
 124|      */
 125|     input  wire                   s_pause_req,
 126|     output wire                   s_pause_ack,
 127|     input  wire                   m_pause_req,
 128|     output wire                   m_pause_ack,
 129| 
 130|     /*
 131|      * Status
 132|      */
 133|     output wire [$clog2(DEPTH):0] s_status_depth,
 134|     output wire [$clog2(DEPTH):0] s_status_depth_commit,
 135|     output wire                   s_status_overflow,
 136|     output wire                   s_status_bad_frame,
 137|     output wire                   s_status_good_frame,
 138|     output wire [$clog2(DEPTH):0] m_status_depth,
 139|     output wire [$clog2(DEPTH):0] m_status_depth_commit,
 140|     output wire                   m_status_overflow,
 141|     output wire                   m_status_bad_frame,
 142|     output wire                   m_status_good_frame
 143| );
 144| 
 145| parameter ADDR_WIDTH = (KEEP_ENABLE && KEEP_WIDTH > 1) ? $clog2(DEPTH/KEEP_WIDTH) : $clog2(DEPTH);
 146| parameter CL_KEEP_WDITH = $clog2(KEEP_WIDTH);
 147| 
 148| parameter OUTPUT_FIFO_ADDR_WIDTH = RAM_PIPELINE < 2 ? 3 : $clog2(RAM_PIPELINE*2+7);
 149| 
 150| // check configuration
 151| initial begin
 152|     if (FRAME_FIFO && !LAST_ENABLE) begin
 153|         $error("Error: FRAME_FIFO set requires LAST_ENABLE set (instance %m)");
 154|         $finish;
 155|     end
 156| 
 157|     if (DROP_OVERSIZE_FRAME && !FRAME_FIFO) begin
 158|         $error("Error: DROP_OVERSIZE_FRAME set requires FRAME_FIFO set (instance %m)");
 159|         $finish;
 160|     end
 161| 
 162|     if (DROP_BAD_FRAME && !(FRAME_FIFO && DROP_OVERSIZE_FRAME)) begin
 163|         $error("Error: DROP_BAD_FRAME set requires FRAME_FIFO and DROP_OVERSIZE_FRAME set (instance %m)");
 164|         $finish;
 165|     end
 166| 
 167|     if (DROP_WHEN_FULL && !(FRAME_FIFO && DROP_OVERSIZE_FRAME)) begin
 168|         $error("Error: DROP_WHEN_FULL set requires FRAME_FIFO and DROP_OVERSIZE_FRAME set (instance %m)");
 169|         $finish;
 170|     end
 171| 
 172|     if ((DROP_BAD_FRAME || MARK_WHEN_FULL) && (USER_BAD_FRAME_MASK & {USER_WIDTH{1'b1}}) == 0) begin
 173|         $error("Error: Invalid USER_BAD_FRAME_MASK value (instance %m)");
 174|         $finish;
 175|     end
 176| 
 177|     if (MARK_WHEN_FULL && FRAME_FIFO) begin
 178|         $error("Error: MARK_WHEN_FULL is not compatible with FRAME_FIFO (instance %m)");
 179|         $finish;
 180|     end
 181| 
 182|     if (MARK_WHEN_FULL && !LAST_ENABLE) begin
 183|         $error("Error: MARK_WHEN_FULL set requires LAST_ENABLE set (instance %m)");
 184|         $finish;
 185|     end
 186| end
 187| 
 188| localparam KEEP_OFFSET = DATA_WIDTH;
 189| localparam LAST_OFFSET = KEEP_OFFSET + (KEEP_ENABLE ? KEEP_WIDTH : 0);
 190| localparam ID_OFFSET   = LAST_OFFSET + (LAST_ENABLE ? 1          : 0);
 191| localparam DEST_OFFSET = ID_OFFSET   + (ID_ENABLE   ? ID_WIDTH   : 0);
 192| localparam USER_OFFSET = DEST_OFFSET + (DEST_ENABLE ? DEST_WIDTH : 0);
 193| localparam WIDTH       = USER_OFFSET + (USER_ENABLE ? USER_WIDTH : 0);
 194| 
 195| function [ADDR_WIDTH:0] bin2gray(input [ADDR_WIDTH:0] b);
 196|     bin2gray = b ^ (b >> 1);
 197| endfunction
 198| 
 199| function [ADDR_WIDTH:0] gray2bin(input [ADDR_WIDTH:0] g);
 200|     integer i;
 201|     for (i = 0; i <= ADDR_WIDTH; i = i + 1) begin
 202|         gray2bin[i] = ^(g >> i);
 203|     end
 204| endfunction
 205| 
 206| reg [ADDR_WIDTH:0] wr_ptr_reg = {ADDR_WIDTH+1{1'b0}};
 207| reg [ADDR_WIDTH:0] wr_ptr_commit_reg = {ADDR_WIDTH+1{1'b0}};
 208| reg [ADDR_WIDTH:0] wr_ptr_gray_reg = {ADDR_WIDTH+1{1'b0}};
 209| reg [ADDR_WIDTH:0] wr_ptr_sync_commit_reg = {ADDR_WIDTH+1{1'b0}};
 210| reg [ADDR_WIDTH:0] rd_ptr_reg = {ADDR_WIDTH+1{1'b0}};
 211| reg [ADDR_WIDTH:0] rd_ptr_gray_reg = {ADDR_WIDTH+1{1'b0}};
 212| reg [ADDR_WIDTH:0] wr_ptr_conv_reg = {ADDR_WIDTH+1{1'b0}};
 213| reg [ADDR_WIDTH:0] rd_ptr_conv_reg = {ADDR_WIDTH+1{1'b0}};
 214| 
 215| reg [ADDR_WIDTH:0] wr_ptr_temp;
 216| reg [ADDR_WIDTH:0] rd_ptr_temp;
 217| 
 218| (* SHREG_EXTRACT = "NO" *)
 219| reg [ADDR_WIDTH:0] wr_ptr_gray_sync1_reg = {ADDR_WIDTH+1{1'b0}};
 220| (* SHREG_EXTRACT = "NO" *)
 221| reg [ADDR_WIDTH:0] wr_ptr_gray_sync2_reg = {ADDR_WIDTH+1{1'b0}};
 222| (* SHREG_EXTRACT = "NO" *)
 223| reg [ADDR_WIDTH:0] wr_ptr_commit_sync_reg = {ADDR_WIDTH+1{1'b0}};
 224| (* SHREG_EXTRACT = "NO" *)
 225| reg [ADDR_WIDTH:0] rd_ptr_gray_sync1_reg = {ADDR_WIDTH+1{1'b0}};
 226| (* SHREG_EXTRACT = "NO" *)
 227| reg [ADDR_WIDTH:0] rd_ptr_gray_sync2_reg = {ADDR_WIDTH+1{1'b0}};
 228| 
 229| reg wr_ptr_update_valid_reg = 1'b0;
 230| reg wr_ptr_update_reg = 1'b0;
 231| (* SHREG_EXTRACT = "NO" *)
 232| reg wr_ptr_update_sync1_reg = 1'b0;
 233| (* SHREG_EXTRACT = "NO" *)
 234| reg wr_ptr_update_sync2_reg = 1'b0;
 235| (* SHREG_EXTRACT = "NO" *)
 236| reg wr_ptr_update_sync3_reg = 1'b0;
 237| (* SHREG_EXTRACT = "NO" *)
 238| reg wr_ptr_update_ack_sync1_reg = 1'b0;
 239| (* SHREG_EXTRACT = "NO" *)
 240| reg wr_ptr_update_ack_sync2_reg = 1'b0;
 241| 
 242| (* SHREG_EXTRACT = "NO" *)
 243| reg s_rst_sync1_reg = 1'b1;
 244| (* SHREG_EXTRACT = "NO" *)
 245| reg s_rst_sync2_reg = 1'b1;
 246| (* SHREG_EXTRACT = "NO" *)
 247| reg s_rst_sync3_reg = 1'b1;
 248| (* SHREG_EXTRACT = "NO" *)
 249| reg m_rst_sync1_reg = 1'b1;
 250| (* SHREG_EXTRACT = "NO" *)
 251| reg m_rst_sync2_reg = 1'b1;
 252| (* SHREG_EXTRACT = "NO" *)
 253| reg m_rst_sync3_reg = 1'b1;
 254| 
 255| (* ramstyle = "no_rw_check" *)
 256| reg [WIDTH-1:0] mem[(2**ADDR_WIDTH)-1:0];
 257| reg mem_read_data_valid_reg = 1'b0;
 258| 
 259| (* shreg_extract = "no" *)
 260| reg [WIDTH-1:0] m_axis_pipe_reg[RAM_PIPELINE+1-1:0];
 261| reg [RAM_PIPELINE+1-1:0] m_axis_tvalid_pipe_reg = 0;
 262| 
 263| // full when first TWO MSBs do NOT match, but rest matches
 264| // (gray code equivalent of first MSB different but rest same)
 265| wire full = wr_ptr_gray_reg == (rd_ptr_gray_sync2_reg ^ {2'b11, {ADDR_WIDTH-1{1'b0}}});
 266| // empty when pointers match exactly
 267| wire empty = FRAME_FIFO ? (rd_ptr_reg == wr_ptr_commit_sync_reg) : (rd_ptr_gray_reg == wr_ptr_gray_sync2_reg);
 268| // overflow within packet
 269| wire full_wr = wr_ptr_reg == (wr_ptr_commit_reg ^ {1'b1, {ADDR_WIDTH{1'b0}}});
 270| 
 271| // control signals
 272| reg write;
 273| reg read;
 274| reg store_output;
 275| 
 276| reg s_frame_reg = 1'b0;
 277| reg m_frame_reg = 1'b0;
 278| 
 279| reg drop_frame_reg = 1'b0;
 280| reg mark_frame_reg = 1'b0;
 281| reg send_frame_reg = 1'b0;
 282| reg overflow_reg = 1'b0;
 283| reg bad_frame_reg = 1'b0;
 284| reg good_frame_reg = 1'b0;
 285| 
 286| reg m_drop_frame_reg = 1'b0;
 287| reg m_terminate_frame_reg = 1'b0;
 288| 
 289| reg [ADDR_WIDTH:0] s_depth_reg = 0;
 290| reg [ADDR_WIDTH:0] s_depth_commit_reg = 0;
 291| reg [ADDR_WIDTH:0] m_depth_reg = 0;
 292| reg [ADDR_WIDTH:0] m_depth_commit_reg = 0;
 293| 
 294| reg overflow_sync1_reg = 1'b0;
 295| reg overflow_sync2_reg = 1'b0;
 296| reg overflow_sync3_reg = 1'b0;
 297| reg overflow_sync4_reg = 1'b0;
 298| reg bad_frame_sync1_reg = 1'b0;
 299| reg bad_frame_sync2_reg = 1'b0;
 300| reg bad_frame_sync3_reg = 1'b0;
 301| reg bad_frame_sync4_reg = 1'b0;
 302| reg good_frame_sync1_reg = 1'b0;
 303| reg good_frame_sync2_reg = 1'b0;
 304| reg good_frame_sync3_reg = 1'b0;
 305| reg good_frame_sync4_reg = 1'b0;
 306| 
 307| assign s_axis_tready = (FRAME_FIFO ? (!full || (full_wr && DROP_OVERSIZE_FRAME) || DROP_WHEN_FULL) : (!full || MARK_WHEN_FULL)) && !s_rst_sync3_reg;
 308| 
 309| wire [WIDTH-1:0] s_axis;
 310| 
 311| generate
 312|     assign s_axis[DATA_WIDTH-1:0] = s_axis_tdata;
 313|     if (KEEP_ENABLE) assign s_axis[KEEP_OFFSET +: KEEP_WIDTH] = s_axis_tkeep;
 314|     if (LAST_ENABLE) assign s_axis[LAST_OFFSET]               = s_axis_tlast | mark_frame_reg;
 315|     if (ID_ENABLE)   assign s_axis[ID_OFFSET   +: ID_WIDTH]   = s_axis_tid;
 316|     if (DEST_ENABLE) assign s_axis[DEST_OFFSET +: DEST_WIDTH] = s_axis_tdest;
 317|     if (USER_ENABLE) assign s_axis[USER_OFFSET +: USER_WIDTH] = mark_frame_reg ? USER_BAD_FRAME_VALUE : s_axis_tuser;
 318| endgenerate
 319| 
 320| wire [WIDTH-1:0] m_axis = m_axis_pipe_reg[RAM_PIPELINE+1-1];
 321| 
 322| wire                   m_axis_tready_pipe;
 323| wire                   m_axis_tvalid_pipe = m_axis_tvalid_pipe_reg[RAM_PIPELINE+1-1];
 324| 
 325| wire [DATA_WIDTH-1:0]  m_axis_tdata_pipe  = m_axis[DATA_WIDTH-1:0];
 326| wire [KEEP_WIDTH-1:0]  m_axis_tkeep_pipe  = KEEP_ENABLE ? m_axis[KEEP_OFFSET +: KEEP_WIDTH] : {KEEP_WIDTH{1'b1}};
 327| wire                   m_axis_tlast_pipe  = LAST_ENABLE ? m_axis[LAST_OFFSET] | m_terminate_frame_reg : 1'b1;
 328| wire [ID_WIDTH-1:0]    m_axis_tid_pipe    = ID_ENABLE   ? m_axis[ID_OFFSET +: ID_WIDTH] : {ID_WIDTH{1'b0}};
 329| wire [DEST_WIDTH-1:0]  m_axis_tdest_pipe  = DEST_ENABLE ? m_axis[DEST_OFFSET +: DEST_WIDTH] : {DEST_WIDTH{1'b0}};
 330| wire [USER_WIDTH-1:0]  m_axis_tuser_pipe  = USER_ENABLE ? (m_terminate_frame_reg ? USER_BAD_FRAME_VALUE : m_axis[USER_OFFSET +: USER_WIDTH]) : {USER_WIDTH{1'b0}};
 331| 
 332| wire                   m_axis_tready_out;
 333| wire                   m_axis_tvalid_out;
 334| 
 335| wire [DATA_WIDTH-1:0]  m_axis_tdata_out;
 336| wire [KEEP_WIDTH-1:0]  m_axis_tkeep_out;
 337| wire                   m_axis_tlast_out;
 338| wire [ID_WIDTH-1:0]    m_axis_tid_out;
 339| wire [DEST_WIDTH-1:0]  m_axis_tdest_out;
 340| wire [USER_WIDTH-1:0]  m_axis_tuser_out;
 341| 
 342| wire pipe_ready;
 343| 
 344| assign s_status_depth = (KEEP_ENABLE && KEEP_WIDTH > 1) ? {s_depth_reg, {CL_KEEP_WDITH{1'b0}}} : s_depth_reg;
 345| assign s_status_depth_commit = (KEEP_ENABLE && KEEP_WIDTH > 1) ? {s_depth_commit_reg, {CL_KEEP_WDITH{1'b0}}} : s_depth_commit_reg;
 346| assign s_status_overflow = overflow_reg;
 347| assign s_status_bad_frame = bad_frame_reg;
 348| assign s_status_good_frame = good_frame_reg;
 349| 
 350| assign m_status_depth = (KEEP_ENABLE && KEEP_WIDTH > 1) ? {m_depth_reg, {CL_KEEP_WDITH{1'b0}}} : m_depth_reg;
 351| assign m_status_depth_commit = (KEEP_ENABLE && KEEP_WIDTH > 1) ? {m_depth_commit_reg, {CL_KEEP_WDITH{1'b0}}} : m_depth_commit_reg;
 352| assign m_status_overflow = overflow_sync3_reg ^ overflow_sync4_reg;
 353| assign m_status_bad_frame = bad_frame_sync3_reg ^ bad_frame_sync4_reg;
 354| assign m_status_good_frame = good_frame_sync3_reg ^ good_frame_sync4_reg;
 355| 
 356| // reset synchronization
 357| always @(posedge m_clk or posedge m_rst) begin
 358|     if (m_rst) begin
 359|         s_rst_sync1_reg <= 1'b1;
 360|     end else begin
 361|         s_rst_sync1_reg <= 1'b0;
 362|     end
 363| end
 364| 
 365| always @(posedge s_clk) begin
 366|     s_rst_sync2_reg <= s_rst_sync1_reg;
 367|     s_rst_sync3_reg <= s_rst_sync2_reg;
 368| end
 369| 
 370| always @(posedge s_clk or posedge s_rst) begin
 371|     if (s_rst) begin
 372|         m_rst_sync1_reg <= 1'b1;
 373|     end else begin
 374|         m_rst_sync1_reg <= 1'b0;
 375|     end
 376| end
 377| 
 378| always @(posedge m_clk) begin
 379|     m_rst_sync2_reg <= m_rst_sync1_reg;
 380|     m_rst_sync3_reg <= m_rst_sync2_reg;
 381| end
 382| 
 383| // Write logic
 384| always @(posedge s_clk) begin
 385|     overflow_reg <= 1'b0;
 386|     bad_frame_reg <= 1'b0;
 387|     good_frame_reg <= 1'b0;
 388| 
 389|     if (FRAME_FIFO && wr_ptr_update_valid_reg) begin
 390|         // have updated pointer to sync
 391|         if (wr_ptr_update_reg == wr_ptr_update_ack_sync2_reg) begin
 392|             // no sync in progress; sync update
 393|             wr_ptr_update_valid_reg <= 1'b0;
 394|             wr_ptr_sync_commit_reg <= wr_ptr_commit_reg;
 395|             wr_ptr_update_reg <= !wr_ptr_update_ack_sync2_reg;
 396|         end
 397|     end
 398| 
 399|     if (s_axis_tready && s_axis_tvalid && LAST_ENABLE) begin
 400|         // track input frame status
 401|         s_frame_reg <= !s_axis_tlast;
 402|     end
 403| 
 404|     if (s_rst_sync3_reg && LAST_ENABLE) begin
 405|         // if sink side is reset during transfer, drop partial frame
 406|         if (s_frame_reg && !(s_axis_tready && s_axis_tvalid && s_axis_tlast)) begin
 407|             drop_frame_reg <= 1'b1;
 408|         end
 409|         if (s_axis_tready && s_axis_tvalid && !s_axis_tlast) begin
 410|             drop_frame_reg <= 1'b1;
 411|         end
 412|     end
 413| 
 414|     if (FRAME_FIFO) begin
 415|         // frame FIFO mode
 416|         if (s_axis_tready && s_axis_tvalid) begin
 417|             // transfer in
 418|             if ((full && DROP_WHEN_FULL) || (full_wr && DROP_OVERSIZE_FRAME) || drop_frame_reg) begin
 419|                 // full, packet overflow, or currently dropping frame
 420|                 // drop frame
 421|                 drop_frame_reg <= 1'b1;
 422|                 if (s_axis_tlast) begin
 423|                     // end of frame, reset write pointer
 424|                     wr_ptr_temp = wr_ptr_commit_reg;
 425|                     wr_ptr_reg <= wr_ptr_temp;
 426|                     wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 427|                     drop_frame_reg <= 1'b0;
 428|                     overflow_reg <= 1'b1;
 429|                 end
 430|             end else begin
 431|                 mem[wr_ptr_reg[ADDR_WIDTH-1:0]] <= s_axis;
 432|                 wr_ptr_temp = wr_ptr_reg + 1;
 433|                 wr_ptr_reg <= wr_ptr_temp;
 434|                 wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 435|                 if (s_axis_tlast || (!DROP_OVERSIZE_FRAME && (full_wr || send_frame_reg))) begin
 436|                     // end of frame or send frame
 437|                     send_frame_reg <= !s_axis_tlast;
 438|                     if (s_axis_tlast && DROP_BAD_FRAME && USER_BAD_FRAME_MASK & ~(s_axis_tuser ^ USER_BAD_FRAME_VALUE)) begin
 439|                         // bad packet, reset write pointer
 440|                         wr_ptr_temp = wr_ptr_commit_reg;
 441|                         wr_ptr_reg <= wr_ptr_temp;
 442|                         wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 443|                         bad_frame_reg <= 1'b1;
 444|                     end else begin
 445|                         // good packet or packet overflow, update write pointer
 446|                         wr_ptr_temp = wr_ptr_reg + 1;
 447|                         wr_ptr_reg <= wr_ptr_temp;
 448|                         wr_ptr_commit_reg <= wr_ptr_temp;
 449|                         wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 450| 
 451|                         if (wr_ptr_update_reg == wr_ptr_update_ack_sync2_reg) begin
 452|                             // no sync in progress; sync update
 453|                             wr_ptr_update_valid_reg <= 1'b0;
 454|                             wr_ptr_sync_commit_reg <= wr_ptr_temp;
 455|                             wr_ptr_update_reg <= !wr_ptr_update_ack_sync2_reg;
 456|                         end else begin
 457|                             // sync in progress; flag it for later
 458|                             wr_ptr_update_valid_reg <= 1'b1;
 459|                         end
 460| 
 461|                         good_frame_reg <= s_axis_tlast;
 462|                     end
 463|                 end
 464|             end
 465|         end else if (s_axis_tvalid && full_wr && FRAME_FIFO && !DROP_OVERSIZE_FRAME) begin
 466|             // data valid with packet overflow
 467|             // update write pointer
 468|             send_frame_reg <= 1'b1;
 469|             wr_ptr_temp = wr_ptr_reg;
 470|             wr_ptr_reg <= wr_ptr_temp;
 471|             wr_ptr_commit_reg <= wr_ptr_temp;
 472|             wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 473| 
 474|             if (wr_ptr_update_reg == wr_ptr_update_ack_sync2_reg) begin
 475|                 // no sync in progress; sync update
 476|                 wr_ptr_update_valid_reg <= 1'b0;
 477|                 wr_ptr_sync_commit_reg <= wr_ptr_temp;
 478|                 wr_ptr_update_reg <= !wr_ptr_update_ack_sync2_reg;
 479|             end else begin
 480|                 // sync in progress; flag it for later
 481|                 wr_ptr_update_valid_reg <= 1'b1;
 482|             end
 483|         end
 484|     end else begin
 485|         // normal FIFO mode
 486|         if (s_axis_tready && s_axis_tvalid) begin
 487|             if (drop_frame_reg && LAST_ENABLE) begin
 488|                 // currently dropping frame
 489|                 if (s_axis_tlast) begin
 490|                     // end of frame
 491|                     if (!full && mark_frame_reg && MARK_WHEN_FULL) begin
 492|                         // terminate marked frame
 493|                         mark_frame_reg <= 1'b0;
 494|                         mem[wr_ptr_reg[ADDR_WIDTH-1:0]] <= s_axis;
 495|                         wr_ptr_temp = wr_ptr_reg + 1;
 496|                         wr_ptr_reg <= wr_ptr_temp;
 497|                         wr_ptr_commit_reg <= wr_ptr_temp;
 498|                         wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 499|                     end
 500|                     // end of frame, clear drop flag
 501|                     drop_frame_reg <= 1'b0;
 502|                     overflow_reg <= 1'b1;
 503|                 end
 504|             end else if ((full || mark_frame_reg) && MARK_WHEN_FULL) begin
 505|                 // full or marking frame
 506|                 // drop frame; mark if this isn't the first cycle
 507|                 drop_frame_reg <= 1'b1;
 508|                 mark_frame_reg <= mark_frame_reg || s_frame_reg;
 509|                 if (s_axis_tlast) begin
 510|                     drop_frame_reg <= 1'b0;
 511|                     overflow_reg <= 1'b1;
 512|                 end
 513|             end else begin
 514|                 // transfer in
 515|                 mem[wr_ptr_reg[ADDR_WIDTH-1:0]] <= s_axis;
 516|                 wr_ptr_temp = wr_ptr_reg + 1;
 517|                 wr_ptr_reg <= wr_ptr_temp;
 518|                 wr_ptr_commit_reg <= wr_ptr_temp;
 519|                 wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 520|             end
 521|         end else if ((!full && !drop_frame_reg && mark_frame_reg) && MARK_WHEN_FULL) begin
 522|             // terminate marked frame
 523|             mark_frame_reg <= 1'b0;
 524|             mem[wr_ptr_reg[ADDR_WIDTH-1:0]] <= s_axis;
 525|             wr_ptr_temp = wr_ptr_reg + 1;
 526|             wr_ptr_reg <= wr_ptr_temp;
 527|             wr_ptr_commit_reg <= wr_ptr_temp;
 528|             wr_ptr_gray_reg <= bin2gray(wr_ptr_temp);
 529|         end
 530|     end
 531| 
 532|     if (s_rst_sync3_reg) begin
 533|         wr_ptr_reg <= {ADDR_WIDTH+1{1'b0}};
 534|         wr_ptr_commit_reg <= {ADDR_WIDTH+1{1'b0}};
 535|         wr_ptr_gray_reg <= {ADDR_WIDTH+1{1'b0}};
 536|         wr_ptr_sync_commit_reg <= {ADDR_WIDTH+1{1'b0}};
 537| 
 538|         wr_ptr_update_valid_reg <= 1'b0;
 539|         wr_ptr_update_reg <= 1'b0;
 540|     end
 541| 
 542|     if (s_rst) begin
 543|         wr_ptr_reg <= {ADDR_WIDTH+1{1'b0}};
 544|         wr_ptr_commit_reg <= {ADDR_WIDTH+1{1'b0}};
 545|         wr_ptr_gray_reg <= {ADDR_WIDTH+1{1'b0}};
 546|         wr_ptr_sync_commit_reg <= {ADDR_WIDTH+1{1'b0}};
 547| 
 548|         wr_ptr_update_valid_reg <= 1'b0;
 549|         wr_ptr_update_reg <= 1'b0;
 550| 
 551|         s_frame_reg <= 1'b0;
 552| 
 553|         drop_frame_reg <= 1'b0;
 554|         mark_frame_reg <= 1'b0;
 555|         send_frame_reg <= 1'b0;
 556|         overflow_reg <= 1'b0;
 557|         bad_frame_reg <= 1'b0;
 558|         good_frame_reg <= 1'b0;
 559|     end
 560| end
 561| 
 562| // Write-side status
 563| always @(posedge s_clk) begin
 564|     rd_ptr_conv_reg <= gray2bin(rd_ptr_gray_sync2_reg);
 565|     s_depth_reg <= wr_ptr_reg - rd_ptr_conv_reg;
 566|     s_depth_commit_reg <= wr_ptr_commit_reg - rd_ptr_conv_reg;
 567| end
 568| 
 569| // pointer synchronization
 570| always @(posedge s_clk) begin
 571|     rd_ptr_gray_sync1_reg <= rd_ptr_gray_reg;
 572|     rd_ptr_gray_sync2_reg <= rd_ptr_gray_sync1_reg;
 573|     wr_ptr_update_ack_sync1_reg <= wr_ptr_update_sync3_reg;
 574|     wr_ptr_update_ack_sync2_reg <= wr_ptr_update_ack_sync1_reg;
 575| 
 576|     if (s_rst) begin
 577|         rd_ptr_gray_sync1_reg <= {ADDR_WIDTH+1{1'b0}};
 578|         rd_ptr_gray_sync2_reg <= {ADDR_WIDTH+1{1'b0}};
 579|         wr_ptr_update_ack_sync1_reg <= 1'b0;
 580|         wr_ptr_update_ack_sync2_reg <= 1'b0;
 581|     end
 582| end
 583| 
 584| always @(posedge m_clk) begin
 585|     wr_ptr_gray_sync1_reg <= wr_ptr_gray_reg;
 586|     wr_ptr_gray_sync2_reg <= wr_ptr_gray_sync1_reg;
 587|     if (FRAME_FIFO && wr_ptr_update_sync2_reg ^ wr_ptr_update_sync3_reg) begin
 588|         wr_ptr_commit_sync_reg <= wr_ptr_sync_commit_reg;
 589|     end
 590|     wr_ptr_update_sync1_reg <= wr_ptr_update_reg;
 591|     wr_ptr_update_sync2_reg <= wr_ptr_update_sync1_reg;
 592|     wr_ptr_update_sync3_reg <= wr_ptr_update_sync2_reg;
 593| 
 594|     if (FRAME_FIFO && m_rst_sync3_reg) begin
 595|         wr_ptr_gray_sync1_reg <= {ADDR_WIDTH+1{1'b0}};
 596|     end
 597| 
 598|     if (m_rst) begin
 599|         wr_ptr_gray_sync1_reg <= {ADDR_WIDTH+1{1'b0}};
 600|         wr_ptr_gray_sync2_reg <= {ADDR_WIDTH+1{1'b0}};
 601|         wr_ptr_commit_sync_reg <= {ADDR_WIDTH+1{1'b0}};
 602|         wr_ptr_update_sync1_reg <= 1'b0;
 603|         wr_ptr_update_sync2_reg <= 1'b0;
 604|         wr_ptr_update_sync3_reg <= 1'b0;
 605|     end
 606| end
 607| 
 608| // status synchronization
 609| always @(posedge s_clk) begin
 610|     overflow_sync1_reg <= overflow_sync1_reg ^ overflow_reg;
 611|     bad_frame_sync1_reg <= bad_frame_sync1_reg ^ bad_frame_reg;
 612|     good_frame_sync1_reg <= good_frame_sync1_reg ^ good_frame_reg;
 613| 
 614|     if (s_rst) begin
 615|         overflow_sync1_reg <= 1'b0;
 616|         bad_frame_sync1_reg <= 1'b0;
 617|         good_frame_sync1_reg <= 1'b0;
 618|     end
 619| end
 620| 
 621| always @(posedge m_clk) begin
 622|     overflow_sync2_reg <= overflow_sync1_reg;
 623|     overflow_sync3_reg <= overflow_sync2_reg;
 624|     overflow_sync4_reg <= overflow_sync3_reg;
 625|     bad_frame_sync2_reg <= bad_frame_sync1_reg;
 626|     bad_frame_sync3_reg <= bad_frame_sync2_reg;
 627|     bad_frame_sync4_reg <= bad_frame_sync3_reg;
 628|     good_frame_sync2_reg <= good_frame_sync1_reg;
 629|     good_frame_sync3_reg <= good_frame_sync2_reg;
 630|     good_frame_sync4_reg <= good_frame_sync3_reg;
 631| 
 632|     if (m_rst) begin
 633|         overflow_sync2_reg <= 1'b0;
 634|         overflow_sync3_reg <= 1'b0;
 635|         overflow_sync4_reg <= 1'b0;
 636|         bad_frame_sync2_reg <= 1'b0;
 637|         bad_frame_sync3_reg <= 1'b0;
 638|         bad_frame_sync4_reg <= 1'b0;
 639|         good_frame_sync2_reg <= 1'b0;
 640|         good_frame_sync3_reg <= 1'b0;
 641|         good_frame_sync4_reg <= 1'b0;
 642|     end
 643| end
 644| 
 645| // Read logic
 646| integer j;
 647| 
 648| always @(posedge m_clk) begin
 649|     if (m_axis_tready_pipe) begin
 650|         // output ready; invalidate stage
 651|         m_axis_tvalid_pipe_reg[RAM_PIPELINE+1-1] <= 1'b0;
 652|         m_terminate_frame_reg <= 1'b0;
 653|     end
 654| 
 655|     for (j = RAM_PIPELINE+1-1; j > 0; j = j - 1) begin
 656|         if (m_axis_tready_pipe || ((~m_axis_tvalid_pipe_reg) >> j)) begin
 657|             // output ready or bubble in pipeline; transfer down pipeline
 658|             m_axis_tvalid_pipe_reg[j] <= m_axis_tvalid_pipe_reg[j-1];
 659|             m_axis_pipe_reg[j] <= m_axis_pipe_reg[j-1];
 660|             m_axis_tvalid_pipe_reg[j-1] <= 1'b0;
 661|         end
 662|     end
 663| 
 664|     if (m_axis_tready_pipe || ~m_axis_tvalid_pipe_reg) begin
 665|         // output ready or bubble in pipeline; read new data from FIFO
 666|         m_axis_tvalid_pipe_reg[0] <= 1'b0;
 667|         m_axis_pipe_reg[0] <= mem[rd_ptr_reg[ADDR_WIDTH-1:0]];
 668|         if (!empty && !m_rst_sync3_reg && !m_drop_frame_reg && pipe_ready) begin
 669|             // not empty, increment pointer
 670|             m_axis_tvalid_pipe_reg[0] <= 1'b1;
 671|             rd_ptr_temp = rd_ptr_reg + 1;
 672|             rd_ptr_reg <= rd_ptr_temp;
 673|             rd_ptr_gray_reg <= rd_ptr_temp ^ (rd_ptr_temp >> 1);
 674|         end
 675|     end
 676| 
 677|     if (m_axis_tvalid_pipe && LAST_ENABLE) begin
 678|         // track output frame status
 679|         if (m_axis_tlast_pipe && m_axis_tready_pipe) begin
 680|             m_frame_reg <= 1'b0;
 681|         end else begin
 682|             m_frame_reg <= 1'b1;
 683|         end
 684|     end
 685| 
 686|     if (m_drop_frame_reg && (OUTPUT_FIFO_ENABLE ? pipe_ready : m_axis_tready_pipe || !m_axis_tvalid_pipe) && LAST_ENABLE) begin
 687|         // terminate frame
 688|         // (only for frame transfers interrupted by source reset)
 689|         m_axis_tvalid_pipe_reg[RAM_PIPELINE+1-1] <= 1'b1;
 690|         m_terminate_frame_reg <= 1'b1;
 691|         m_drop_frame_reg <= 1'b0;
 692|     end
 693| 
 694|     if (m_rst_sync3_reg && LAST_ENABLE) begin
 695|         // if source side is reset during transfer, drop partial frame
 696| 
 697|         // empty output pipeline, except for last stage
 698|         if (RAM_PIPELINE > 0) begin
 699|             m_axis_tvalid_pipe_reg[RAM_PIPELINE+1-2:0] <= 0;
 700|         end
 701| 
 702|         if (m_frame_reg && (!m_axis_tvalid_pipe || (m_axis_tvalid_pipe && !m_axis_tlast_pipe)) &&
 703|                 !(m_drop_frame_reg || m_terminate_frame_reg)) begin
 704|             // terminate frame
 705|             m_drop_frame_reg <= 1'b1;
 706|         end
 707|     end
 708| 
 709|     if (m_rst_sync3_reg) begin
 710|         rd_ptr_reg <= {ADDR_WIDTH+1{1'b0}};
 711|         rd_ptr_gray_reg <= {ADDR_WIDTH+1{1'b0}};
 712|     end
 713| 
 714|     if (m_rst) begin
 715|         rd_ptr_reg <= {ADDR_WIDTH+1{1'b0}};
 716|         rd_ptr_gray_reg <= {ADDR_WIDTH+1{1'b0}};
 717|         m_axis_tvalid_pipe_reg <= 0;
 718|         m_frame_reg <= 1'b0;
 719|         m_drop_frame_reg <= 1'b0;
 720|         m_terminate_frame_reg <= 1'b0;
 721|     end
 722| end
 723| 
 724| // Read-side status
 725| always @(posedge m_clk) begin
 726|     wr_ptr_conv_reg <= gray2bin(wr_ptr_gray_sync2_reg);
 727|     m_depth_reg <= wr_ptr_conv_reg - rd_ptr_reg;
 728|     m_depth_commit_reg <= FRAME_FIFO ? wr_ptr_commit_sync_reg - rd_ptr_reg : wr_ptr_conv_reg - rd_ptr_reg;
 729| end
 730| 
 731| generate
 732| 
 733| if (!OUTPUT_FIFO_ENABLE) begin
 734| 
 735|     assign pipe_ready = 1'b1;
 736| 
 737|     assign m_axis_tready_pipe = m_axis_tready_out;
 738|     assign m_axis_tvalid_out = m_axis_tvalid_pipe;
 739| 
 740|     assign m_axis_tdata_out = m_axis_tdata_pipe;
 741|     assign m_axis_tkeep_out = m_axis_tkeep_pipe;
 742|     assign m_axis_tlast_out = m_axis_tlast_pipe;
 743|     assign m_axis_tid_out   = m_axis_tid_pipe;
 744|     assign m_axis_tdest_out = m_axis_tdest_pipe;
 745|     assign m_axis_tuser_out = m_axis_tuser_pipe;
 746| 
 747| end else begin : output_fifo
 748| 
 749|     // output datapath logic
 750|     reg [DATA_WIDTH-1:0] m_axis_tdata_reg  = {DATA_WIDTH{1'b0}};
 751|     reg [KEEP_WIDTH-1:0] m_axis_tkeep_reg  = {KEEP_WIDTH{1'b0}};
 752|     reg                  m_axis_tvalid_reg = 1'b0;
 753|     reg                  m_axis_tlast_reg  = 1'b0;
 754|     reg [ID_WIDTH-1:0]   m_axis_tid_reg    = {ID_WIDTH{1'b0}};
 755|     reg [DEST_WIDTH-1:0] m_axis_tdest_reg  = {DEST_WIDTH{1'b0}};
 756|     reg [USER_WIDTH-1:0] m_axis_tuser_reg  = {USER_WIDTH{1'b0}};
 757| 
 758|     reg [OUTPUT_FIFO_ADDR_WIDTH+1-1:0] out_fifo_wr_ptr_reg = 0;
 759|     reg [OUTPUT_FIFO_ADDR_WIDTH+1-1:0] out_fifo_rd_ptr_reg = 0;
 760|     reg out_fifo_half_full_reg = 1'b0;
 761| 
 762|     wire out_fifo_full = out_fifo_wr_ptr_reg == (out_fifo_rd_ptr_reg ^ {1'b1, {OUTPUT_FIFO_ADDR_WIDTH{1'b0}}});
 763|     wire out_fifo_empty = out_fifo_wr_ptr_reg == out_fifo_rd_ptr_reg;
 764| 
 765|     (* ram_style = "distributed", ramstyle = "no_rw_check, mlab" *)
 766|     reg [DATA_WIDTH-1:0] out_fifo_tdata[2**OUTPUT_FIFO_ADDR_WIDTH-1:0];
 767|     (* ram_style = "distributed", ramstyle = "no_rw_check, mlab" *)
 768|     reg [KEEP_WIDTH-1:0] out_fifo_tkeep[2**OUTPUT_FIFO_ADDR_WIDTH-1:0];
 769|     (* ram_style = "distributed", ramstyle = "no_rw_check, mlab" *)
 770|     reg                  out_fifo_tlast[2**OUTPUT_FIFO_ADDR_WIDTH-1:0];
 771|     (* ram_style = "distributed", ramstyle = "no_rw_check, mlab" *)
 772|     reg [ID_WIDTH-1:0]   out_fifo_tid[2**OUTPUT_FIFO_ADDR_WIDTH-1:0];
 773|     (* ram_style = "distributed", ramstyle = "no_rw_check, mlab" *)
 774|     reg [DEST_WIDTH-1:0] out_fifo_tdest[2**OUTPUT_FIFO_ADDR_WIDTH-1:0];
 775|     (* ram_style = "distributed", ramstyle = "no_rw_check, mlab" *)
 776|     reg [USER_WIDTH-1:0] out_fifo_tuser[2**OUTPUT_FIFO_ADDR_WIDTH-1:0];
 777| 
 778|     assign pipe_ready = !out_fifo_half_full_reg;
 779| 
 780|     assign m_axis_tready_pipe = 1'b1;
 781| 
 782|     assign m_axis_tdata_out  = m_axis_tdata_reg;
 783|     assign m_axis_tkeep_out  = KEEP_ENABLE ? m_axis_tkeep_reg : {KEEP_WIDTH{1'b1}};
 784|     assign m_axis_tvalid_out = m_axis_tvalid_reg;
 785|     assign m_axis_tlast_out  = LAST_ENABLE ? m_axis_tlast_reg : 1'b1;
 786|     assign m_axis_tid_out    = ID_ENABLE   ? m_axis_tid_reg   : {ID_WIDTH{1'b0}};
 787|     assign m_axis_tdest_out  = DEST_ENABLE ? m_axis_tdest_reg : {DEST_WIDTH{1'b0}};
 788|     assign m_axis_tuser_out  = USER_ENABLE ? m_axis_tuser_reg : {USER_WIDTH{1'b0}};
 789| 
 790|     always @(posedge m_clk) begin
 791|         m_axis_tvalid_reg <= m_axis_tvalid_reg && !m_axis_tready_out;
 792| 
 793|         out_fifo_half_full_reg <= $unsigned(out_fifo_wr_ptr_reg - out_fifo_rd_ptr_reg) >= 2**(OUTPUT_FIFO_ADDR_WIDTH-1);
 794| 
 795|         if (!out_fifo_full && m_axis_tvalid_pipe) begin
 796|             out_fifo_tdata[out_fifo_wr_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]] <= m_axis_tdata_pipe;
 797|             out_fifo_tkeep[out_fifo_wr_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]] <= m_axis_tkeep_pipe;
 798|             out_fifo_tlast[out_fifo_wr_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]] <= m_axis_tlast_pipe;
 799|             out_fifo_tid[out_fifo_wr_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]] <= m_axis_tid_pipe;
 800|             out_fifo_tdest[out_fifo_wr_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]] <= m_axis_tdest_pipe;
 801|             out_fifo_tuser[out_fifo_wr_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]] <= m_axis_tuser_pipe;
 802|             out_fifo_wr_ptr_reg <= out_fifo_wr_ptr_reg + 1;
 803|         end
 804| 
 805|         if (!out_fifo_empty && (!m_axis_tvalid_reg || m_axis_tready_out)) begin
 806|             m_axis_tdata_reg <= out_fifo_tdata[out_fifo_rd_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]];
 807|             m_axis_tkeep_reg <= out_fifo_tkeep[out_fifo_rd_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]];
 808|             m_axis_tvalid_reg <= 1'b1;
 809|             m_axis_tlast_reg <= out_fifo_tlast[out_fifo_rd_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]];
 810|             m_axis_tid_reg <= out_fifo_tid[out_fifo_rd_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]];
 811|             m_axis_tdest_reg <= out_fifo_tdest[out_fifo_rd_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]];
 812|             m_axis_tuser_reg <= out_fifo_tuser[out_fifo_rd_ptr_reg[OUTPUT_FIFO_ADDR_WIDTH-1:0]];
 813|             out_fifo_rd_ptr_reg <= out_fifo_rd_ptr_reg + 1;
 814|         end
 815| 
 816|         if (m_rst) begin
 817|             out_fifo_wr_ptr_reg <= 0;
 818|             out_fifo_rd_ptr_reg <= 0;
 819|             m_axis_tvalid_reg <= 1'b0;
 820|         end
 821|     end
 822| 
 823| end
 824| 
 825| if (PAUSE_ENABLE) begin : pause
 826| 
 827|     // Pause logic
 828|     reg pause_reg = 1'b0;
 829|     reg pause_frame_reg = 1'b0;
 830| 
 831|     reg s_pause_req_sync1_reg;
 832|     reg s_pause_req_sync2_reg;
 833|     reg s_pause_req_sync3_reg;
 834|     reg s_pause_ack_sync1_reg;
 835|     reg s_pause_ack_sync2_reg;
 836|     reg s_pause_ack_sync3_reg;
 837| 
 838|     always @(posedge s_clk) begin
 839|         s_pause_req_sync1_reg <= s_pause_req;
 840|         s_pause_ack_sync2_reg <= s_pause_ack_sync1_reg;
 841|         s_pause_ack_sync3_reg <= s_pause_ack_sync2_reg;
 842|     end
 843| 
 844|     always @(posedge m_clk) begin
 845|         s_pause_req_sync2_reg <= s_pause_req_sync1_reg;
 846|         s_pause_req_sync3_reg <= s_pause_req_sync2_reg;
 847|         s_pause_ack_sync1_reg <= pause_reg;
 848|     end
 849| 
 850|     assign m_axis_tready_out = m_axis_tready && !pause_reg;
 851|     assign m_axis_tvalid = m_axis_tvalid_out && !pause_reg;
 852| 
 853|     assign m_axis_tdata = m_axis_tdata_out;
 854|     assign m_axis_tkeep = m_axis_tkeep_out;
 855|     assign m_axis_tlast = m_axis_tlast_out;
 856|     assign m_axis_tid   = m_axis_tid_out;
 857|     assign m_axis_tdest = m_axis_tdest_out;
 858|     assign m_axis_tuser = m_axis_tuser_out;
 859| 
 860|     assign s_pause_ack = s_pause_ack_sync3_reg;
 861|     assign m_pause_ack = pause_reg;
 862| 
 863|     always @(posedge m_clk) begin
 864|         if (FRAME_PAUSE) begin
 865|             if (pause_reg) begin
 866|                 // paused; update pause status
 867|                 pause_reg <= m_pause_req || s_pause_req_sync3_reg;
 868|             end else if (m_axis_tvalid_out) begin
 869|                 // frame transfer; set frame bit
 870|                 pause_frame_reg <= 1'b1;
 871|                 if (m_axis_tready && m_axis_tlast) begin
 872|                     // end of frame; clear frame bit and update pause status
 873|                     pause_frame_reg <= 1'b0;
 874|                     pause_reg <= m_pause_req || s_pause_req_sync3_reg;
 875|                 end
 876|             end else if (!pause_frame_reg) begin
 877|                 // idle; update pause status
 878|                 pause_reg <= m_pause_req || s_pause_req_sync3_reg;
 879|             end
 880|         end else begin
 881|             pause_reg <= m_pause_req || s_pause_req_sync3_reg;
 882|         end
 883| 
 884|         if (m_rst) begin
 885|             pause_frame_reg <= 1'b0;
 886|             pause_reg <= 1'b0;
 887|         end
 888|     end
 889| 
 890| end else begin
 891| 
 892|     assign m_axis_tready_out = m_axis_tready;
 893|     assign m_axis_tvalid = m_axis_tvalid_out;
 894| 
 895|     assign m_axis_tdata = m_axis_tdata_out;
 896|     assign m_axis_tkeep = m_axis_tkeep_out;
 897|     assign m_axis_tlast = m_axis_tlast_out;
 898|     assign m_axis_tid   = m_axis_tid_out;
 899|     assign m_axis_tdest = m_axis_tdest_out;
 900|     assign m_axis_tuser = m_axis_tuser_out;
 901| 
 902|     assign s_pause_ack = 1'b0;
 903|     assign m_pause_ack = 1'b0;
 904| 
 905| end
 906| 
 907| endgenerate
 908| 
 909| endmodule