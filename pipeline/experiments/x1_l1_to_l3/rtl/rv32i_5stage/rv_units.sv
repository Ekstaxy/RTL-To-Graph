// Classic 5-stage RV32I pipeline (IF ID EX MEM WB), textbook organisation:
// branches/jumps resolve in EX, full forwarding EX/MEM->EX and MEM/WB->EX, one-cycle
// load-use stall, register file written in the first half (write-through bypass).
// Written for rtl2diagram as a reference design with a known architecture.
// SPDX-License-Identifier: MIT

// ---------------------------------------------------------------- small datapath parts
module rv_adder #(parameter W = 32) (
    input  logic [W-1:0] a,
    input  logic [W-1:0] b,
    output logic [W-1:0] y
);
    assign y = a + b;
endmodule

module rv_mux2 #(parameter W = 32) (
    input  logic         sel,
    input  logic [W-1:0] d0,
    input  logic [W-1:0] d1,
    output logic [W-1:0] y
);
    assign y = sel ? d1 : d0;
endmodule

module rv_mux3 #(parameter W = 32) (
    input  logic [1:0]   sel,
    input  logic [W-1:0] d0,
    input  logic [W-1:0] d1,
    input  logic [W-1:0] d2,
    output logic [W-1:0] y
);
    always_comb begin
        case (sel)
            2'd1:    y = d1;
            2'd2:    y = d2;
            default: y = d0;
        endcase
    end
endmodule

// ---------------------------------------------------------------- IF
module rv_pc_reg (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        stall,
    input  logic [31:0] pc_next,
    output logic [31:0] pc
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) pc <= 32'h0;
        else if (!stall) pc <= pc_next;
    end
endmodule

module rv_imem #(parameter DEPTH = 256, parameter INIT = "prog.hex") (
    input  logic [31:0] addr,
    output logic [31:0] instr
);
    logic [31:0] rom [0:DEPTH-1];
    initial $readmemh(INIT, rom);
    assign instr = rom[addr[$clog2(DEPTH)+1:2]];
endmodule

module rv_if_id (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        stall,
    input  logic        flush,
    input  logic [31:0] pc_in,
    input  logic [31:0] pc4_in,
    input  logic [31:0] instr_in,
    output logic [31:0] pc,
    output logic [31:0] pc4,
    output logic [31:0] instr
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pc <= 32'h0; pc4 <= 32'h0; instr <= 32'h0000_0013;  // nop
        end else if (flush) begin
            instr <= 32'h0000_0013;
        end else if (!stall) begin
            pc <= pc_in; pc4 <= pc4_in; instr <= instr_in;
        end
    end
endmodule

// ---------------------------------------------------------------- ID
module rv_decoder (
    input  logic [31:0] instr,
    output logic        reg_write,
    output logic        mem_read,
    output logic        mem_write,
    output logic [1:0]  wb_sel,     // 0 alu, 1 mem, 2 pc+4
    output logic        alu_src,    // 0 rs2, 1 imm
    output logic        alu_pc,     // operand a is pc (auipc, jal)
    output logic [3:0]  alu_op,
    output logic        branch,
    output logic        jump,
    output logic        jalr,
    output logic [2:0]  funct3
);
    logic [6:0] opcode;
    logic [6:0] funct7;
    assign opcode = instr[6:0];
    assign funct3 = instr[14:12];
    assign funct7 = instr[31:25];

    always_comb begin
        reg_write = 1'b0; mem_read = 1'b0; mem_write = 1'b0; wb_sel = 2'd0;
        alu_src = 1'b0; alu_pc = 1'b0; alu_op = 4'd0; branch = 1'b0; jump = 1'b0;
        jalr = 1'b0;
        case (opcode)
            7'b0110011: begin  // R-type
                reg_write = 1'b1;
                alu_op = {funct7[5], funct3};
            end
            7'b0010011: begin  // I-type ALU
                reg_write = 1'b1; alu_src = 1'b1;
                alu_op = {(funct3 == 3'b101) & funct7[5], funct3};
            end
            7'b0000011: begin  // load
                reg_write = 1'b1; mem_read = 1'b1; alu_src = 1'b1; wb_sel = 2'd1;
            end
            7'b0100011: begin  // store
                mem_write = 1'b1; alu_src = 1'b1;
            end
            7'b1100011: begin  // branch
                branch = 1'b1;
            end
            7'b1101111: begin  // jal
                reg_write = 1'b1; jump = 1'b1; wb_sel = 2'd2;
            end
            7'b1100111: begin  // jalr
                reg_write = 1'b1; jump = 1'b1; jalr = 1'b1; alu_src = 1'b1; wb_sel = 2'd2;
            end
            7'b0110111: begin  // lui: 0 + imm
                reg_write = 1'b1; alu_src = 1'b1; alu_op = 4'd15;
            end
            7'b0010111: begin  // auipc: pc + imm
                reg_write = 1'b1; alu_src = 1'b1; alu_pc = 1'b1;
            end
            default: ;
        endcase
    end
endmodule

module rv_imm_gen (
    input  logic [31:0] instr,
    output logic [31:0] imm
);
    always_comb begin
        case (instr[6:0])
            7'b0100011: imm = {{20{instr[31]}}, instr[31:25], instr[11:7]};
            7'b1100011: imm = {{19{instr[31]}}, instr[31], instr[7], instr[30:25], instr[11:8], 1'b0};
            7'b1101111: imm = {{11{instr[31]}}, instr[31], instr[19:12], instr[20], instr[30:21], 1'b0};
            7'b0110111, 7'b0010111: imm = {instr[31:12], 12'b0};
            default:    imm = {{20{instr[31]}}, instr[31:20]};
        endcase
    end
endmodule

module rv_regfile (
    input  logic        clk,
    input  logic [4:0]  ra1,
    input  logic [4:0]  ra2,
    output logic [31:0] rd1,
    output logic [31:0] rd2,
    input  logic        we,
    input  logic [4:0]  wa,
    input  logic [31:0] wd
);
    logic [31:0] regs [0:31];
    always_ff @(posedge clk) begin
        if (we && wa != 5'd0) regs[wa] <= wd;
    end
    // write-through: a register written in WB this cycle is read with its new value in ID
    assign rd1 = (ra1 == 5'd0) ? 32'h0 : (we && wa == ra1) ? wd : regs[ra1];
    assign rd2 = (ra2 == 5'd0) ? 32'h0 : (we && wa == ra2) ? wd : regs[ra2];
endmodule

module rv_hazard_unit (
    input  logic [4:0] id_rs1,
    input  logic [4:0] id_rs2,
    input  logic [4:0] ex_rd,
    input  logic       ex_mem_read,
    input  logic       ex_redirect,
    output logic       stall_if,
    output logic       stall_id,
    output logic       flush_id,
    output logic       flush_ex
);
    logic load_use;
    assign load_use = ex_mem_read && (ex_rd != 5'd0) && (ex_rd == id_rs1 || ex_rd == id_rs2);
    assign stall_if = load_use;
    assign stall_id = load_use;
    assign flush_id = ex_redirect;              // squash the instruction fetched behind a taken branch
    assign flush_ex = load_use | ex_redirect;   // insert a bubble
endmodule

module rv_id_ex (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        flush,
    input  logic [31:0] pc_in,
    input  logic [31:0] pc4_in,
    input  logic [31:0] rs1_val_in,
    input  logic [31:0] rs2_val_in,
    input  logic [31:0] imm_in,
    input  logic [4:0]  rs1_in,
    input  logic [4:0]  rs2_in,
    input  logic [4:0]  rd_in,
    input  logic [2:0]  funct3_in,
    input  logic        reg_write_in,
    input  logic        mem_read_in,
    input  logic        mem_write_in,
    input  logic [1:0]  wb_sel_in,
    input  logic        alu_src_in,
    input  logic        alu_pc_in,
    input  logic [3:0]  alu_op_in,
    input  logic        branch_in,
    input  logic        jump_in,
    input  logic        jalr_in,
    output logic [31:0] pc,
    output logic [31:0] pc4,
    output logic [31:0] rs1_val,
    output logic [31:0] rs2_val,
    output logic [31:0] imm,
    output logic [4:0]  rs1,
    output logic [4:0]  rs2,
    output logic [4:0]  rd,
    output logic [2:0]  funct3,
    output logic        reg_write,
    output logic        mem_read,
    output logic        mem_write,
    output logic [1:0]  wb_sel,
    output logic        alu_src,
    output logic        alu_pc,
    output logic [3:0]  alu_op,
    output logic        branch,
    output logic        jump,
    output logic        jalr
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_write <= 1'b0; mem_read <= 1'b0; mem_write <= 1'b0; branch <= 1'b0;
            jump <= 1'b0; jalr <= 1'b0; rd <= 5'd0; rs1 <= 5'd0; rs2 <= 5'd0;
        end else if (flush) begin  // bubble
            reg_write <= 1'b0; mem_read <= 1'b0; mem_write <= 1'b0; branch <= 1'b0;
            jump <= 1'b0; jalr <= 1'b0; rd <= 5'd0; rs1 <= 5'd0; rs2 <= 5'd0;
        end else begin
            reg_write <= reg_write_in; mem_read <= mem_read_in; mem_write <= mem_write_in;
            branch <= branch_in; jump <= jump_in; jalr <= jalr_in;
            rd <= rd_in; rs1 <= rs1_in; rs2 <= rs2_in;
        end
    end
    always_ff @(posedge clk) begin
        pc <= pc_in; pc4 <= pc4_in; rs1_val <= rs1_val_in; rs2_val <= rs2_val_in; imm <= imm_in;
        funct3 <= funct3_in; wb_sel <= wb_sel_in; alu_src <= alu_src_in; alu_pc <= alu_pc_in;
        alu_op <= alu_op_in;
    end
endmodule

// ---------------------------------------------------------------- EX
module rv_forward_unit (
    input  logic [4:0] ex_rs1,
    input  logic [4:0] ex_rs2,
    input  logic [4:0] mem_rd,
    input  logic       mem_reg_write,
    input  logic [4:0] wb_rd,
    input  logic       wb_reg_write,
    output logic [1:0] fwd_a,   // 0 regfile, 1 from WB, 2 from MEM
    output logic [1:0] fwd_b
);
    always_comb begin
        fwd_a = 2'd0; fwd_b = 2'd0;
        if (mem_reg_write && mem_rd != 5'd0 && mem_rd == ex_rs1) fwd_a = 2'd2;
        else if (wb_reg_write && wb_rd != 5'd0 && wb_rd == ex_rs1) fwd_a = 2'd1;
        if (mem_reg_write && mem_rd != 5'd0 && mem_rd == ex_rs2) fwd_b = 2'd2;
        else if (wb_reg_write && wb_rd != 5'd0 && wb_rd == ex_rs2) fwd_b = 2'd1;
    end
endmodule

module rv_alu (
    input  logic [3:0]  op,     // {funct7[5], funct3}; 15 = pass b (lui)
    input  logic [31:0] a,
    input  logic [31:0] b,
    output logic [31:0] y
);
    always_comb begin
        case (op)
            4'b0000: y = a + b;
            4'b1000: y = a - b;
            4'b0001: y = a << b[4:0];
            4'b0010: y = {31'b0, $signed(a) < $signed(b)};
            4'b0011: y = {31'b0, a < b};
            4'b0100: y = a ^ b;
            4'b0101: y = a >> b[4:0];
            4'b1101: y = $unsigned($signed(a) >>> b[4:0]);
            4'b0110: y = a | b;
            4'b0111: y = a & b;
            4'b1111: y = b;
            default: y = a + b;
        endcase
    end
endmodule

module rv_branch_unit (
    input  logic        branch,
    input  logic        jump,
    input  logic        jalr,
    input  logic [2:0]  funct3,
    input  logic [31:0] rs1_val,
    input  logic [31:0] rs2_val,
    input  logic [31:0] pc,
    input  logic [31:0] imm,
    output logic        redirect,
    output logic [31:0] target
);
    logic taken;
    always_comb begin
        case (funct3)
            3'b000:  taken = rs1_val == rs2_val;
            3'b001:  taken = rs1_val != rs2_val;
            3'b100:  taken = $signed(rs1_val) < $signed(rs2_val);
            3'b101:  taken = $signed(rs1_val) >= $signed(rs2_val);
            3'b110:  taken = rs1_val < rs2_val;
            3'b111:  taken = rs1_val >= rs2_val;
            default: taken = 1'b0;
        endcase
    end
    assign redirect = jump | (branch & taken);
    assign target = jalr ? ((rs1_val + imm) & ~32'h1) : (pc + imm);
endmodule

module rv_ex_mem (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [31:0] alu_in,
    input  logic [31:0] store_in,
    input  logic [31:0] pc4_in,
    input  logic [4:0]  rd_in,
    input  logic [2:0]  funct3_in,
    input  logic        reg_write_in,
    input  logic        mem_read_in,
    input  logic        mem_write_in,
    input  logic [1:0]  wb_sel_in,
    output logic [31:0] alu,
    output logic [31:0] store,
    output logic [31:0] pc4,
    output logic [4:0]  rd,
    output logic [2:0]  funct3,
    output logic        reg_write,
    output logic        mem_read,
    output logic        mem_write,
    output logic [1:0]  wb_sel
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_write <= 1'b0; mem_read <= 1'b0; mem_write <= 1'b0; rd <= 5'd0;
        end else begin
            reg_write <= reg_write_in; mem_read <= mem_read_in; mem_write <= mem_write_in;
            rd <= rd_in;
        end
    end
    always_ff @(posedge clk) begin
        alu <= alu_in; store <= store_in; pc4 <= pc4_in; funct3 <= funct3_in;
        wb_sel <= wb_sel_in;
    end
endmodule

// ---------------------------------------------------------------- MEM
module rv_dmem #(parameter DEPTH = 256) (
    input  logic        clk,
    input  logic        we,
    input  logic        re,
    input  logic [2:0]  funct3,
    input  logic [31:0] addr,
    input  logic [31:0] wdata,
    output logic [31:0] rdata,
    output logic        io_we,       // memory-mapped result port at 0x8000_0000
    output logic [31:0] io_data
);
    logic [31:0] ram [0:DEPTH-1];
    logic [31:0] word;
    logic [$clog2(DEPTH)-1:0] idx;
    assign idx = addr[$clog2(DEPTH)+1:2];
    assign word = ram[idx];
    assign io_we = we && addr[31];
    assign io_data = wdata;
    always_ff @(posedge clk) begin
        if (we && !addr[31]) begin
            case (funct3[1:0])
                2'b00: ram[idx][8*addr[1:0] +: 8] <= wdata[7:0];
                2'b01: ram[idx][16*addr[1] +: 16] <= wdata[15:0];
                default: ram[idx] <= wdata;
            endcase
        end
    end
    always_comb begin
        case (funct3)
            3'b000: rdata = {{24{word[8*addr[1:0]+7]}}, word[8*addr[1:0] +: 8]};
            3'b100: rdata = {24'b0, word[8*addr[1:0] +: 8]};
            3'b001: rdata = {{16{word[16*addr[1]+15]}}, word[16*addr[1] +: 16]};
            3'b101: rdata = {16'b0, word[16*addr[1] +: 16]};
            default: rdata = word;
        endcase
        if (!re) rdata = 32'h0;
    end
endmodule

module rv_mem_wb (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [31:0] alu_in,
    input  logic [31:0] mem_in,
    input  logic [31:0] pc4_in,
    input  logic [4:0]  rd_in,
    input  logic        reg_write_in,
    input  logic [1:0]  wb_sel_in,
    output logic [31:0] alu,
    output logic [31:0] mem,
    output logic [31:0] pc4,
    output logic [4:0]  rd,
    output logic        reg_write,
    output logic [1:0]  wb_sel
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_write <= 1'b0; rd <= 5'd0;
        end else begin
            reg_write <= reg_write_in; rd <= rd_in;
        end
    end
    always_ff @(posedge clk) begin
        alu <= alu_in; mem <= mem_in; pc4 <= pc4_in; wb_sel <= wb_sel_in;
    end
endmodule
