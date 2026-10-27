# Blind votes

## Round 1 (`blind_v6.html`, one reader, 6 of 8 answered): C A B B B A
| design | chosen | crossings winner |
|---|---|---|
| rtllm_adder_16bit | elk_r12 | elk_part / elk_r12 (tie) |
| verilog-axi_axi_crossbar | elk_r12 | tie |
| common_cells_cc_cdc_2phase_clearable | paper | elk_r12 |
| biriscv_biriscv_csr | elk_part | elk_r12 |
| dark_darksocv | elk_r12 | elk_r12 |
| verilog-ethernet_eth_mac_phy_10g | paper | elk_r12 |

Tally: elk_r12 3, paper 2, elk_part 1. Crossings agreed with the reader 3 of 6.

## Round 2 (`blind2_v7.html`, fresh set, one reader, all 8): A A B A C B B B
| design | chosen | crossings winner |
|---|---|---|
| biriscv_biriscv_lsu | elk_r12 | elk_r12 |
| common_cells_cc_cdc_fifo_gray_clearable | system | paper / elk_r12 (0.09) |
| common_cells_cc_stream_omega_net | paper | elk_r12 (0.62 vs paper 4.04) |
| picorv32_wb | system | elk_r12 |
| verilog-ethernet_eth_mac_10g_fifo | paper | elk_r12 |
| verilog-i2c_i2c_master_wbs_8 | system | system |
| verilog-wishbone_wb_arbiter_2 | system | elk_r12 |
| wb2axip_axidouble | system | system |

Tally: **system 5, paper 2, elk_r12 1.** Crossings agreed with the reader 3 of 8.
Both paper wins are designs where paper shows port names on the blocks; both times the
crossing count was far worse. Reading: the system grammar is the right default for
hierarchical designs; labels and symbols matter more than crossings once the count is low.
