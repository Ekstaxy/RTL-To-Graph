"""Assemble the self-check program into prog.hex (tiny RV32I encoder, no toolchain needed).

Exercises: EX/MEM and MEM/WB forwarding, a taken backward branch (flush), a load-use stall,
lui, jal/jalr. Stores to 0x8000_0000 appear on the core's `result` port: expected 56, 123.
"""

from pathlib import Path


def r(f7, rs2, rs1, f3, rd, op):
    return f7 << 25 | rs2 << 20 | rs1 << 15 | f3 << 12 | rd << 7 | op


def i(imm, rs1, f3, rd, op):
    return (imm & 0xFFF) << 20 | rs1 << 15 | f3 << 12 | rd << 7 | op


def s(imm, rs2, rs1, f3, op=0b0100011):
    return (imm >> 5 & 0x7F) << 25 | rs2 << 20 | rs1 << 15 | f3 << 12 | (imm & 0x1F) << 7 | op


def b(imm, rs2, rs1, f3, op=0b1100011):
    imm &= 0x1FFF
    return (
        (imm >> 12 & 1) << 31
        | (imm >> 5 & 0x3F) << 25
        | rs2 << 20
        | rs1 << 15
        | f3 << 12
        | (imm >> 1 & 0xF) << 8
        | (imm >> 11 & 1) << 7
        | op
    )


def j(imm, rd, op=0b1101111):
    imm &= 0x1FFFFF
    return (
        (imm >> 20 & 1) << 31
        | (imm >> 1 & 0x3FF) << 21
        | (imm >> 11 & 1) << 20
        | (imm >> 12 & 0xFF) << 12
        | rd << 7
        | op
    )


def u(imm20, rd, op):
    return (imm20 & 0xFFFFF) << 12 | rd << 7 | op


ADDI = lambda rd, rs1, imm: i(imm, rs1, 0, rd, 0b0010011)  # noqa: E731
prog = [
    ADDI(1, 0, 0),  # 0x00 sum = 0
    ADDI(2, 0, 1),  # 0x04 i = 1
    ADDI(3, 0, 11),  # 0x08 limit
    r(0, 2, 1, 0, 1, 0b0110011),  # 0x0c loop: sum += i
    ADDI(2, 2, 1),  # 0x10 i++
    b(-8, 3, 2, 0b001),  # 0x14 bne i, limit, loop
    s(0, 1, 0, 0b010),  # 0x18 sw sum, 0(x0)
    i(0, 0, 0b010, 4, 0b0000011),  # 0x1c lw x4, 0(x0)
    ADDI(5, 4, 1),  # 0x20 x5 = x4 + 1   (load-use stall)
    u(0x80000, 6, 0b0110111),  # 0x24 lui x6, 0x80000
    s(0, 5, 6, 0b010),  # 0x28 sw x5 -> result = 56
    j(12, 7),  # 0x2c jal x7, func (0x38)
    s(0, 8, 6, 0b010),  # 0x30 sw x8 -> result = 123
    j(0, 0),  # 0x34 spin
    ADDI(8, 0, 123),  # 0x38 func: x8 = 123
    i(0, 7, 0, 0, 0b1100111),  # 0x3c jalr x0, 0(x7)
]
out = Path(__file__).with_name("prog.hex")
out.write_text("\n".join(f"{w:08x}" for w in prog) + "\n")
print(f"{len(prog)} words -> {out.name}")
