// Top level of the 5-stage RV32I pipeline: every functional unit is an instance, so the
// architecture is visible in the hierarchy. A store to 0x8000_0000 drives `result`.
// SPDX-License-Identifier: MIT
module rv32i_core #(parameter IMEM_INIT = "prog.hex") (
    input  logic        clk,
    input  logic        rst_n,
    output logic        result_valid,
    output logic [31:0] result
);
    // ------------------------------------------------------------ IF
    logic [31:0] if_pc, if_pc4, if_instr, pc_next;
    logic        stall_if, stall_id, flush_id, flush_ex;
    logic        ex_redirect;
    logic [31:0] ex_target;

    rv_mux2  u_pc_mux  (.sel(ex_redirect), .d0(if_pc4), .d1(ex_target), .y(pc_next));
    rv_pc_reg u_pc     (.clk, .rst_n, .stall(stall_if), .pc_next, .pc(if_pc));
    rv_adder u_pc_plus4 (.a(if_pc), .b(32'd4), .y(if_pc4));
    rv_imem #(.INIT(IMEM_INIT)) u_imem (.addr(if_pc), .instr(if_instr));

    // ------------------------------------------------------------ IF/ID
    logic [31:0] id_pc, id_pc4, id_instr;
    rv_if_id u_if_id (
        .clk, .rst_n, .stall(stall_id), .flush(flush_id),
        .pc_in(if_pc), .pc4_in(if_pc4), .instr_in(if_instr),
        .pc(id_pc), .pc4(id_pc4), .instr(id_instr)
    );

    // ------------------------------------------------------------ ID
    logic        id_reg_write, id_mem_read, id_mem_write, id_alu_src, id_alu_pc;
    logic        id_branch, id_jump, id_jalr;
    logic [1:0]  id_wb_sel;
    logic [3:0]  id_alu_op;
    logic [2:0]  id_funct3;
    logic [31:0] id_imm, id_rs1_val, id_rs2_val;
    logic [4:0]  id_rs1, id_rs2, id_rd;
    assign id_rs1 = id_instr[19:15];
    assign id_rs2 = id_instr[24:20];
    assign id_rd  = id_instr[11:7];

    logic        wb_reg_write;
    logic [4:0]  wb_rd;
    logic [31:0] wb_data;

    rv_decoder u_decoder (
        .instr(id_instr), .reg_write(id_reg_write), .mem_read(id_mem_read),
        .mem_write(id_mem_write), .wb_sel(id_wb_sel), .alu_src(id_alu_src),
        .alu_pc(id_alu_pc), .alu_op(id_alu_op), .branch(id_branch), .jump(id_jump),
        .jalr(id_jalr), .funct3(id_funct3)
    );
    rv_imm_gen u_imm_gen (.instr(id_instr), .imm(id_imm));
    rv_regfile u_regfile (
        .clk, .ra1(id_rs1), .ra2(id_rs2), .rd1(id_rs1_val), .rd2(id_rs2_val),
        .we(wb_reg_write), .wa(wb_rd), .wd(wb_data)
    );

    logic [4:0] ex_rd;
    logic       ex_mem_read;
    rv_hazard_unit u_hazard (
        .id_rs1, .id_rs2, .ex_rd, .ex_mem_read, .ex_redirect,
        .stall_if, .stall_id, .flush_id, .flush_ex
    );

    // ------------------------------------------------------------ ID/EX
    logic [31:0] ex_pc, ex_pc4, ex_rs1_val, ex_rs2_val, ex_imm;
    logic [4:0]  ex_rs1, ex_rs2;
    logic [2:0]  ex_funct3;
    logic        ex_reg_write, ex_mem_write, ex_alu_src, ex_alu_pc, ex_branch, ex_jump;
    logic        ex_jalr;
    logic [1:0]  ex_wb_sel;
    logic [3:0]  ex_alu_op;
    rv_id_ex u_id_ex (
        .clk, .rst_n, .flush(flush_ex),
        .pc_in(id_pc), .pc4_in(id_pc4), .rs1_val_in(id_rs1_val), .rs2_val_in(id_rs2_val),
        .imm_in(id_imm), .rs1_in(id_rs1), .rs2_in(id_rs2), .rd_in(id_rd),
        .funct3_in(id_funct3), .reg_write_in(id_reg_write), .mem_read_in(id_mem_read),
        .mem_write_in(id_mem_write), .wb_sel_in(id_wb_sel), .alu_src_in(id_alu_src),
        .alu_pc_in(id_alu_pc), .alu_op_in(id_alu_op), .branch_in(id_branch),
        .jump_in(id_jump), .jalr_in(id_jalr),
        .pc(ex_pc), .pc4(ex_pc4), .rs1_val(ex_rs1_val), .rs2_val(ex_rs2_val), .imm(ex_imm),
        .rs1(ex_rs1), .rs2(ex_rs2), .rd(ex_rd), .funct3(ex_funct3),
        .reg_write(ex_reg_write), .mem_read(ex_mem_read), .mem_write(ex_mem_write),
        .wb_sel(ex_wb_sel), .alu_src(ex_alu_src), .alu_pc(ex_alu_pc), .alu_op(ex_alu_op),
        .branch(ex_branch), .jump(ex_jump), .jalr(ex_jalr)
    );

    // ------------------------------------------------------------ EX
    logic [1:0]  fwd_a, fwd_b;
    logic [31:0] ex_op_a_fwd, ex_op_b_fwd, ex_alu_a, ex_alu_b, ex_alu_y;
    logic [4:0]  mem_rd;
    logic        mem_reg_write;
    logic [31:0] mem_alu;

    rv_forward_unit u_forward (
        .ex_rs1, .ex_rs2, .mem_rd, .mem_reg_write, .wb_rd, .wb_reg_write, .fwd_a, .fwd_b
    );
    rv_mux3 u_fwd_a_mux (.sel(fwd_a), .d0(ex_rs1_val), .d1(wb_data), .d2(mem_alu), .y(ex_op_a_fwd));
    rv_mux3 u_fwd_b_mux (.sel(fwd_b), .d0(ex_rs2_val), .d1(wb_data), .d2(mem_alu), .y(ex_op_b_fwd));
    rv_mux2 u_alu_a_mux (.sel(ex_alu_pc), .d0(ex_op_a_fwd), .d1(ex_pc), .y(ex_alu_a));
    rv_mux2 u_alu_b_mux (.sel(ex_alu_src), .d0(ex_op_b_fwd), .d1(ex_imm), .y(ex_alu_b));
    rv_alu u_alu (.op(ex_alu_op), .a(ex_alu_a), .b(ex_alu_b), .y(ex_alu_y));
    rv_branch_unit u_branch (
        .branch(ex_branch), .jump(ex_jump), .jalr(ex_jalr), .funct3(ex_funct3),
        .rs1_val(ex_op_a_fwd), .rs2_val(ex_op_b_fwd), .pc(ex_pc), .imm(ex_imm),
        .redirect(ex_redirect), .target(ex_target)
    );

    // ------------------------------------------------------------ EX/MEM
    logic [31:0] mem_store, mem_pc4;
    logic [2:0]  mem_funct3;
    logic        mem_mem_read, mem_mem_write;
    logic [1:0]  mem_wb_sel;
    rv_ex_mem u_ex_mem (
        .clk, .rst_n,
        .alu_in(ex_alu_y), .store_in(ex_op_b_fwd), .pc4_in(ex_pc4), .rd_in(ex_rd),
        .funct3_in(ex_funct3), .reg_write_in(ex_reg_write), .mem_read_in(ex_mem_read),
        .mem_write_in(ex_mem_write), .wb_sel_in(ex_wb_sel),
        .alu(mem_alu), .store(mem_store), .pc4(mem_pc4), .rd(mem_rd), .funct3(mem_funct3),
        .reg_write(mem_reg_write), .mem_read(mem_mem_read), .mem_write(mem_mem_write),
        .wb_sel(mem_wb_sel)
    );

    // ------------------------------------------------------------ MEM
    logic [31:0] mem_rdata;
    rv_dmem u_dmem (
        .clk, .we(mem_mem_write), .re(mem_mem_read), .funct3(mem_funct3), .addr(mem_alu),
        .wdata(mem_store), .rdata(mem_rdata), .io_we(result_valid), .io_data(result)
    );

    // ------------------------------------------------------------ MEM/WB
    logic [31:0] wb_alu, wb_mem, wb_pc4;
    logic [1:0]  wb_sel;
    rv_mem_wb u_mem_wb (
        .clk, .rst_n,
        .alu_in(mem_alu), .mem_in(mem_rdata), .pc4_in(mem_pc4), .rd_in(mem_rd),
        .reg_write_in(mem_reg_write), .wb_sel_in(mem_wb_sel),
        .alu(wb_alu), .mem(wb_mem), .pc4(wb_pc4), .rd(wb_rd), .reg_write(wb_reg_write),
        .wb_sel(wb_sel)
    );

    // ------------------------------------------------------------ WB
    rv_mux3 u_wb_mux (.sel(wb_sel), .d0(wb_alu), .d1(wb_mem), .d2(wb_pc4), .y(wb_data));
endmodule
