"""x4: small experiment-local VCD reader (no new dependency).

    uv run python pipeline/experiments/x4_fsm_timing/vcd.py WAVE.vcd [HIER_NAME ...]

Prints the scopes/vars summary, or the normalized change list of each named signal.

Sampling convention (documented choice, used by timing_bridge and timing_check): the value of
a signal "at a posedge t" is the value *just before* the edge, i.e. the last change with time
strictly less than t. That is what a flip-flop clocked at t samples, and it is independent of
delta-cycle ordering at t (a register updated by the edge at t shows its new value only at the
next posedge). Before its first change a signal reads "x".

Normalization: 1-bit values -> "0" | "1" | "x" | "z"; buses -> lower-case hex without prefix or
leading zeros ("0" for zero); a bus with any x bit (or a mix of z and 0/1 bits) -> "x"; an
all-z bus -> "z". Binary vector values shorter than the declared width are left-extended per
IEEE 1364 (0/1 MSB -> 0, x -> x, z -> z). Real (`r`) and string (`s`) changes are kept verbatim.
"""

from __future__ import annotations

import bisect
import sys
from dataclasses import dataclass, field
from pathlib import Path

_BIT = {"0": "0", "1": "1", "x": "x", "X": "x", "z": "z", "Z": "z", "u": "x", "U": "x",
        "w": "x", "W": "x", "l": "0", "L": "0", "h": "1", "H": "1", "-": "x"}


@dataclass
class Var:
    code: str
    name: str  # hierarchical, dot separated, e.g. "tb.dut.in_valid"
    width: int
    kind: str  # wire | reg | parameter | integer | ...


@dataclass
class Vcd:
    timescale: str = ""
    vars: dict[str, Var] = field(default_factory=dict)  # hier name -> Var
    scopes: list[str] = field(default_factory=list)
    end_t: int = 0
    _times: dict[str, list[int]] = field(default_factory=dict)  # code -> change times
    _vals: dict[str, list[str]] = field(default_factory=dict)  # code -> raw values (extended)

    # ---- lookup -------------------------------------------------------------------------
    def has(self, name: str) -> bool:
        return name in self.vars

    def width(self, name: str) -> int:
        return self.vars[name].width

    def raw(self, name: str) -> list[tuple[int, str]]:
        """Changes as (t, raw value): bits left-extended to the declared width."""
        v = self.vars[name]
        return list(zip(self._times.get(v.code, []), self._vals.get(v.code, []), strict=True))

    def signal(self, name: str) -> list[tuple[int, str]]:
        """Normalized changes (t, value); consecutive equal values are kept (as dumped)."""
        w = self.vars[name].width
        return [(t, norm(r, w)) for t, r in self.raw(name)]

    def raw_at(self, name: str, t: int) -> str:
        """Raw value just before t (last change with time < t); "x" before any change."""
        v = self.vars[name]
        times = self._times.get(v.code, [])
        i = bisect.bisect_left(times, t) - 1
        return self._vals[v.code][i] if i >= 0 else "x" * max(v.width, 1)

    def at(self, name: str, t: int) -> str:
        """Normalized value just before t (see module docstring)."""
        return norm(self.raw_at(name, t), self.vars[name].width)

    def posedges(self, name: str) -> list[int]:
        """Times of 0/x/z -> 1 transitions (the initial value at the first dump is not an edge)."""
        out: list[int] = []
        prev: str | None = None
        for t, v in self.signal(name):
            if prev is not None and prev != "1" and v == "1":
                out.append(t)
            prev = v
        return out


def norm(raw: str, width: int) -> str:
    if raw[:1] in ("r", "s"):
        return raw
    bits = raw.lower()
    if width <= 1 and len(bits) == 1:
        return _BIT.get(bits, "x")
    if "x" in bits:
        return "x"
    if "z" in bits:
        return "z" if set(bits) == {"z"} else "x"
    return format(int(bits, 2), "x") if bits else "x"


def _extend(bits: str, width: int) -> str:
    bits = "".join(_BIT.get(c, "x") for c in bits)
    if len(bits) >= width:
        return bits[-width:] if width > 0 else bits
    pad = bits[0] if bits[0] in "xz" else "0"
    return pad * (width - len(bits)) + bits


def parse(path: Path | str) -> Vcd:
    text = Path(path).read_text(errors="replace")
    vcd = Vcd()
    toks = text.split()
    widths: dict[str, int] = {}
    i = _header(toks, vcd, widths)
    t = 0
    last_t = 0
    n = len(toks)
    while i < n:
        tok = toks[i]
        c = tok[0]
        if c == "#":
            t = int(tok[1:])
            last_t = max(last_t, t)
        elif c in "bBrR":
            val, code = tok[1:], toks[i + 1]
            i += 1
            if c in "bB":
                val = _extend(val, widths.get(code, len(val)))
            else:
                val = "r" + val
            _add(vcd, code, t, val)
        elif c in "sS":
            _add(vcd, toks[i + 1], t, "s" + tok[1:])
            i += 1
        elif c in _BIT and len(tok) > 1:
            _add(vcd, tok[1:], t, _extend(c, max(widths.get(tok[1:], 1), 1)))
        # $dumpvars/$dumpall/$dumpon/$dumpoff/$end/$comment keywords: values inside are changes
        elif tok == "$comment":
            while i < n and toks[i] != "$end":
                i += 1
        i += 1
    vcd.end_t = last_t
    return vcd


def _add(vcd: Vcd, code: str, t: int, val: str) -> None:
    times = vcd._times.setdefault(code, [])
    vals = vcd._vals.setdefault(code, [])
    if times and times[-1] == t:  # several changes in one time step: the last one wins
        vals[-1] = val
        return
    times.append(t)
    vals.append(val)


def _header(toks: list[str], vcd: Vcd, widths: dict[str, int]) -> int:
    """Consume declarations up to $enddefinitions; returns the index after it."""
    stack: list[str] = []
    i, n = 0, len(toks)
    while i < n:
        tok = toks[i]
        if tok == "$enddefinitions":
            while i < n and toks[i] != "$end":
                i += 1
            return i + 1
        j = i + 1
        while j < n and toks[j] != "$end":
            j += 1
        body = toks[i + 1:j]
        if tok == "$scope" and len(body) >= 2:
            stack.append(body[1])
            vcd.scopes.append(".".join(stack))
        elif tok == "$upscope" and stack:
            stack.pop()
        elif tok == "$timescale":
            vcd.timescale = "".join(body)
        elif tok == "$var" and len(body) >= 4:
            kind, width, code, ref = body[0], int(body[1]), body[2], body[3]
            name = ".".join([*stack, ref.lstrip("\\")])
            vcd.vars.setdefault(name, Var(code, name, width, kind))
            widths.setdefault(code, width)
        i = j + 1 if tok.startswith("$") else i + 1
    return n


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    v = parse(Path(argv[0]))
    if len(argv) == 1:
        print(f"timescale {v.timescale}  end_t {v.end_t}  vars {len(v.vars)}  "
              f"scopes {len(v.scopes)}")
        for name, var in sorted(v.vars.items()):
            print(f"  {name:40s} w={var.width:<3d} {var.kind} changes={len(v.raw(name))}")
        return 0
    for name in argv[1:]:
        print(name, v.signal(name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
