"""roles-v2 taxonomy (SPEC §4). Changing anything here requires a TAXONOMY_VERSION bump.

v2 (2026-10-01): added STATUS, COMMAND, INDEX, HOLDING_REG, DECODE, CLOCK_GEN after the
first session-annotation round showed CONTROL_FLAG / PIPELINE_REG / INTERFACE_ADDR being
used as catch-alls (see docs/VALIDATION.md).
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    FSM_STATE = "FSM_STATE"
    CONTROL_FLAG = "CONTROL_FLAG"
    ENABLE = "ENABLE"
    MUX_SELECT = "MUX_SELECT"
    COUNTER = "COUNTER"
    HANDSHAKE_VALID = "HANDSHAKE_VALID"
    HANDSHAKE_READY = "HANDSHAKE_READY"
    INTERFACE_DATA = "INTERFACE_DATA"
    INTERFACE_ADDR = "INTERFACE_ADDR"
    DATAPATH_MAJOR = "DATAPATH_MAJOR"
    PIPELINE_REG = "PIPELINE_REG"
    STORAGE = "STORAGE"
    FIFO_PTR = "FIFO_PTR"
    CONFIG_REG = "CONFIG_REG"
    ARBITRATION = "ARBITRATION"
    STATUS = "STATUS"
    COMMAND = "COMMAND"
    INDEX = "INDEX"
    HOLDING_REG = "HOLDING_REG"
    DECODE = "DECODE"
    CLOCK_GEN = "CLOCK_GEN"


ROLE_DEFS: dict[Role, str] = {
    Role.FSM_STATE: "Controller state register (incl. one-hot and 2-state machines). If a state_q/state_d pair exists, select only the register.",
    Role.CONTROL_FLAG: "INTERNAL flag that gates several assignments: stall/flush/pending/hit/miss/full/empty/lock. Not for ports that only report status (use STATUS) and not for command inputs (use COMMAND).",
    Role.ENABLE: "Write/action enable for a register or path (we, en, load, shift, data-valid chain enabling a stage).",
    Role.MUX_SELECT: "Select that chooses between data sources (not the FSM state itself).",
    Role.COUNTER: "Counter or timer (baud counter, bit counter, timeout, cycle counter).",
    Role.HANDSHAKE_VALID: "valid/req-direction handshake signal.",
    Role.HANDSHAKE_READY: "ready/ack/grant-direction handshake signal.",
    Role.INTERFACE_DATA: "Data payload that crosses an interface boundary.",
    Role.INTERFACE_ADDR: "Address / ID that crosses the module boundary (a port). Internal indices use INDEX.",
    Role.DATAPATH_MAJOR: "Main computed result or datapath waypoint (alu_result, sum, product).",
    Role.PIPELINE_REG: "Register separating stages of a real pipeline (new data enters every cycle). Latches held across a multi-cycle operation use HOLDING_REG.",
    Role.STORAGE: "Memory, register file, buffer array or shift register holding data.",
    Role.FIFO_PTR: "FIFO/buffer read/write pointer or occupancy count.",
    Role.CONFIG_REG: "Software-programmable configuration/control register.",
    Role.ARBITRATION: "Grant vector, priority or round-robin pointer.",
    Role.STATUS: "Status/observation output or FSM-decoded output (busy, done level, error, mode/state indication, count output).",
    Role.COMMAND: "Command/mode/opcode input that selects WHAT the module does (start, rw, we-as-command, op, mode, flush request).",
    Role.INDEX: "Internal address/index/pointer into storage or a table (cache index, regfile rd/rs, hash index). Not FIFO pointers (FIFO_PTR).",
    Role.HOLDING_REG: "Register latching a request/operand/result and holding it across a multi-cycle operation (addr_q, operand regs, result reg).",
    Role.DECODE: "Decoded instruction/command flag or decoder output that steers many units (instr_add, is_load, opcode class).",
    Role.CLOCK_GEN: "Generated/divided clock or clock-enable produced by this module (clk_div, CLK_50, tick used as a clock).",
}

# tie-break rules shown to the teacher (roles-v2)
ROLE_RULES = [
    "One concept, one anchor: if a port is just a copy of an internal register, anchor the one a diagram would draw (usually the port for handshakes/data, the register for state/storage) and put the other in a group's member_ids.",
    "A 1-cycle done/valid pulse that accompanies result data is HANDSHAKE_VALID; a level 'busy/done/idle' indication is STATUS.",
    "External 1-bit condition inputs that only steer FSM transitions (bump, j/k, x) are not anchored by default; they are covered by `interfaces`. Anchor one only if it is a handshake, a COMMAND, or the module would otherwise have fewer than 2 anchors.",
    "Replicated / bit-sliced structures (skew registers, per-bit carries, address bits A/B/C): anchor ONE representative and list the rest in the group's member_ids.",
    "Logic disabled by parameters/defines (fanin=0 wires, ENABLE_X=0) is at most minor.",
    "Ports are critical only when they are the primary handshake or primary data of the module's main function; other ports are major or minor (they are listed in interfaces anyway).",
    "Keep the MEDIUM view (critical+major) readable as ONE block diagram: normally <= 12 anchors, <= 20 even for a large core; push the rest to minor.",
]


class Importance(str, Enum):
    critical = "critical"
    major = "major"
    minor = "minor"


IMPORTANCE_VALUE = {Importance.critical: 1.0, Importance.major: 0.7, Importance.minor: 0.4}


class TraceHint(str, Enum):
    control_backward = "control_backward"
    data_backward = "data_backward"
    forward = "forward"
    interface = "interface"
    none = "none"


class GroupKind(str, Enum):
    CONTROLLER = "CONTROLLER"
    DATAPATH = "DATAPATH"
    ARBITER = "ARBITER"
    BUFFER = "BUFFER"
    COUNTER_TIMER = "COUNTER_TIMER"
    DECODER = "DECODER"
    SERIALIZER = "SERIALIZER"
    PIPELINE_STAGE = "PIPELINE_STAGE"
    MEMORY = "MEMORY"
    INTERFACE_ADAPTER = "INTERFACE_ADAPTER"
    REGISTER_BANK = "REGISTER_BANK"
    OTHER = "OTHER"


class Protocol(str, Enum):
    VALID_READY = "VALID_READY"
    REQ_ACK = "REQ_ACK"
    MEMORY_BUS = "MEMORY_BUS"
    STREAM = "STREAM"
    SERIAL = "SERIAL"
    SIMPLE = "SIMPLE"
    CLOCK_RESET = "CLOCK_RESET"
    OTHER = "OTHER"


class Direction(str, Enum):
    IN = "IN"
    OUT = "OUT"
    BIDIR = "BIDIR"


class Level(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


LEVEL_DEFS = {
    Level.HIGH: "Only critical anchors: interface bundles, the main FSM, main storage. At most 4 groups.",
    Level.MEDIUM: "critical + major anchors. At most 8 groups. (default)",
    Level.LOW: "Also include minor anchors: internal enables, selects, datapath waypoints.",
}

LEVEL_ALLOWED_IMPORTANCE = {
    Level.HIGH: {Importance.critical},
    Level.MEDIUM: {Importance.critical, Importance.major},
    Level.LOW: {Importance.critical, Importance.major, Importance.minor},
}
LEVEL_MAX_GROUPS = {Level.HIGH: 4, Level.MEDIUM: 8, Level.LOW: 16}
