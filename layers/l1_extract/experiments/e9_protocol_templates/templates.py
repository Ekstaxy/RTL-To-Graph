"""e9 pair-first protocol templates over the L1 DesignGraph (plan §3 Stage 1, `templates.py`).

Library module (no command line); used by e9_select.py.

Order (each step only sees ports no earlier step claimed):
  1. handshake pairs: every valid-class port (valid/vld) is matched with a ready-class port
     (ready/rdy) of the opposite direction, every req-class port (req/stb) with an ack-class
     port (ack/gnt/grant), when *structural* evidence holds on the graph; candidates are
     ranked by (name-stem similarity, number of evidence registers) and matched greedily
     one-to-one, so prefixes are ignored when they disagree (wb2axip skidbuffer);
  2. STREAM: a valid without a structural ready, confirmed when it gates (input) or is driven
     by (output) a register;
  3. data members of 1-2: ports whose value path reaches a register gated by the pair
     (input side) or that are driven from such a register (output side); a port matching
     several interfaces goes to the most name-similar one, then the one with more evidence;
  4. FIFO: 1-bit input gating the write of a node with depth + read side (rd gating the read
     pointer / read register, rdata from the memory) + full/empty status outputs;
  5. MEMORY_BUS: input with an ADDR edge into a node with depth (or into a read of it);
  6. SERIAL: 1-bit port whose value path reaches a shift register (self DATA edge, no +/-)
     written under a counter (CONTROL), or a bit-select indexed (ADDR) by a counter;
  7. leftover handshake-hinted ports -> SIMPLE, confirmed=false, with `demoted_reason`.
Name hints only pick the slot (which port class, wr vs rd, full vs empty, addr/we role);
structure decides whether a template is confirmed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from rtl2d_l1.frontend.graph import DesignGraph, EdgeType

_HERE = Path(__file__).resolve().parent


def _gm():
    import importlib.util
    import sys

    name = "e9_graph"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, _HERE / "e9_graph.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


gm = _gm()

CLASS_RE = {
    "valid": re.compile(r"valid|vld|(^|_)v(_|$)", re.I),
    "ready": re.compile(r"ready|rdy", re.I),
    "req": re.compile(r"(^|_)req|req$|stb|strobe", re.I),
    "ack": re.compile(r"ack|gnt|grant", re.I),
}
MATE = {"valid": "ready", "req": "ack"}
STATUS_RE = re.compile(
    r"status|(^|_)stat(_|$)|busy|done|err|overflow|underflow|irq|intr|full|empty|stall|"
    r"(^|_)(count|cnt|level|depth|fill)(_|$)",
    re.I,
)
WR_RE = re.compile(r"(^|_)(wr|we|wen|push|write|in)(_|$)|wr_?en", re.I)
RD_RE = re.compile(r"(^|_)(rd|re|ren|pop|read|out)(_|$)|rd_?en", re.I)
ADDR_RE = re.compile(r"addr|adr", re.I)
WE_RE = re.compile(r"(^|_)(we|wen|wr_?en|write_?en)(_|$)", re.I)
EN_RE = re.compile(r"(^|_)(cyc|en|enable|ena|cs|ce|sel|strb|wstrb|be)(_|$)", re.I)
STRB_RE = re.compile(r"(^|_)(strb|wstrb|be|byteen|byte_en)(_|$)", re.I)


def port_class(name: str) -> str | None:
    for c in ("valid", "ready", "req", "ack"):
        if CLASS_RE[c].search(name):
            return c
    return None


def stem_tokens(name: str, cls: str | None) -> list[str]:
    toks = [t for t in name.lower().split("_") if t]
    if cls:
        toks = [CLASS_RE[cls].sub("", t) for t in toks]
    return [t for t in toks if t]


def name_sim(a: list[str], b: list[str]) -> float:
    """Common leading tokens; +0.5 when the next token of `a` starts with the next one of `b`
    (`s_axil_wdata` vs stem `s_axil_w` beats stem `s_axil_aw`)."""
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            return n + (0.5 if x.startswith(y) else 0.0)
        n += 1
    return float(n)


@dataclass
class Iface:
    name: str
    protocol: str
    direction: str
    members: list[tuple[str, str]] = field(default_factory=list)  # (node key, role)
    confirmed: bool = True
    evidence: list[str] = field(default_factory=list)
    demoted_reason: str | None = None
    fwd: str | None = None  # valid/req key
    bwd: str | None = None  # ready/ack key


class Matcher:
    """Runs the template steps for the top instance of one DesignGraph."""

    def __init__(
        self, G: DesignGraph, top: str, skip: frozenset[str], cr_ports: set[str], hops: int = 4
    ):
        self.G, self.top, self.skip, self.hops = G, top, skip, hops
        self.ports = sorted(
            (k for k, n in G.nodes.items() if n.inst == top and n.port_dir in ("in", "out")),
            key=lambda k: (G.nodes[k].line, G.nodes[k].offset, k),
        )
        self.cr_ports = cr_ports
        self.claimed: dict[str, str] = {}
        self.ifaces: list[Iface] = []
        self.notes: list[str] = []
        self._walk: dict[tuple, dict] = {}

    # ------------------------------------------------------------------ walks
    def fwd(self, k: str, types=gm.FLOW) -> dict:
        key = (k, True, types)
        if key not in self._walk:
            self._walk[key] = gm.walk_regs(self.G, k, forward=True, types=types, skip=self.skip,
                                           max_hops=self.hops)
        return self._walk[key]

    def back(self, k: str, types=gm.FLOW) -> dict:
        key = (k, False, types)
        if key not in self._walk:
            self._walk[key] = gm.walk_regs(self.G, k, forward=False, types=types, skip=self.skip,
                                           max_hops=self.hops)
        return self._walk[key]

    def gates(self, k: str) -> dict:
        return gm.gated(self.fwd(k))

    def n(self, k: str):
        return self.G.nodes[k]

    def free(self, dir_: str | None = None, width1: bool = False) -> list[str]:
        out = []
        for k in self.ports:
            n = self.n(k)
            if k in self.claimed or k in self.cr_ports:
                continue
            if dir_ and n.port_dir != dir_:
                continue
            if width1 and n.width != 1:
                continue
            out.append(k)
        return out

    def claim(self, iface: Iface, k: str, role: str) -> None:
        self.claimed[k] = iface.name
        iface.members.append((k, role))

    def _unique(self, name: str) -> str:
        used = {i.name for i in self.ifaces}
        base, i = name or "if", 2
        while name in used or not name:
            name = f"{base}_{i}"
            i += 1
        return name

    def p(self, path) -> str:
        return gm.fmt_path(self.G, path)

    # ------------------------------------------------------------ step 1: pairs
    def gaters(self, x: str) -> dict:
        key = (x, "gaters")
        if key not in self._walk:
            self._walk[key] = gm.gaters(self.G, x, self.top, skip=self.skip, max_hops=self.hops)
        return self._walk[key]

    def pair_evidence(self, f: str, b: str) -> tuple[set[str], list[str]]:
        """Registers X tying a forward port f (valid/req) to a backward port b (ready/ack).

        f input:  f reaches X (gating it or as its value) and b gates X or is driven by X;
        f output: b reaches X and X drives f (or f, read back inside, also reaches X)."""
        G = self.G
        fn, bn = self.n(f), self.n(b)
        regs: set[str] = set()
        ev: list[str] = []
        if fn.port_dir == "in":
            fr, bg, bd = self.fwd(f), self.gates(b), self.back(b)
            for x in sorted(set(fr) & set(bg)):
                regs.add(x)
                ev.append(f"{fn.name} and {bn.name} both act on {gm.rel(G, x)}: "
                          f"[{self.p(fr[x])}] [{self.p(bg[x])}]")
            for x in sorted(set(fr) & set(bd)):
                regs.add(x)
                ev.append(f"{fn.name} reaches {gm.rel(G, x)} which drives {bn.name}: "
                          f"[{self.p(fr[x])}] [{self.p(bd[x])}]")
        else:
            br, fd, fr = self.fwd(b), self.back(f), self.fwd(f)
            for x in sorted(set(br) & set(fd)):
                regs.add(x)
                ev.append(f"{bn.name} reaches {gm.rel(G, x)} which drives {fn.name}: "
                          f"[{self.p(br[x])}] [{self.p(fd[x]) or gm.rel(G, x)}]")
            for x in sorted((set(br) & set(fr)) - regs):
                regs.add(x)
                ev.append(f"{fn.name} and {bn.name} both act on {gm.rel(G, x)}: "
                          f"[{self.p(fr[x])}] [{self.p(br[x])}]")
        return regs, ev

    def pairs(self) -> None:
        cands = []
        for fcls, bcls in MATE.items():
            fs = [k for k in self.free() if port_class(self.n(k).name) == fcls]
            bs = [k for k in self.free() if port_class(self.n(k).name) == bcls]
            for f in fs:
                for b in bs:
                    if self.n(f).port_dir == self.n(b).port_dir:
                        continue
                    regs, ev = self.pair_evidence(f, b)
                    if not regs:
                        continue
                    sim = name_sim(stem_tokens(self.n(f).name, fcls),
                                   stem_tokens(self.n(b).name, bcls))
                    cands.append((-sim, -len(regs), f, b, fcls, ev))
        chosen = []
        for _nsim, _nr, f, b, fcls, ev in sorted(cands, key=lambda c: c[:4]):
            if f in self.claimed or b in self.claimed or any(f in c or b in c for c in chosen):
                continue
            chosen.append((f, b, fcls, ev))
        names = self._pair_names(chosen)
        for (f, b, fcls, ev), name in zip(chosen, names, strict=True):
            proto = "VALID_READY" if fcls == "valid" else "REQ_ACK"
            it = Iface(self._unique(name), proto, self.n(f).port_dir, fwd=f, bwd=b,
                       evidence=list(ev[:4]))
            if len(ev) > 4:
                it.evidence.append(f"... {len(ev) - 4} more evidence registers")
            self.ifaces.append(it)
            self.claim(it, f, "valid" if fcls == "valid" else "req")
            self.claim(it, b, "ready" if fcls == "valid" else "ack")

    def _pair_names(self, chosen) -> list[str]:
        """Common name stem of valid and ready (`s_axil_aw`). A trailing fragment left by
        stripping the hint (`t` of `tvalid`) is dropped only when every pair of the design
        leaves the same fragment (AXI-Stream `t`), so AXI channel letters stay."""
        full, frags = [], []
        for f, b, fcls, _ev in chosen:
            fn = self.n(f).name
            raw = [t for t in fn.lower().split("_") if t]
            fst = stem_tokens(fn, fcls)
            common = int(name_sim(fst, stem_tokens(self.n(b).name, MATE[fcls])))
            toks = fst[:common] or fst or [fn.lower()]
            full.append(toks)
            last_raw = raw[len(toks) - 1] if len(raw) >= len(toks) else ""
            frags.append(toks[-1] if len(toks) > 1 and CLASS_RE[fcls].search(last_raw)
                         else None)
        drop = len(set(frags)) == 1 and frags[0] is not None
        return ["_".join(t[:-1] if drop else t) for t in full]

    # ----------------------------------------------------------- step 2: streams
    def streams(self) -> None:
        for f in self.free():
            fn = self.n(f)
            if port_class(fn.name) != "valid":
                continue
            regs = self.fwd(f) if fn.port_dir == "in" else self.back(f)
            if not regs:
                continue
            x = sorted(regs)[0]
            verb = "reaches" if fn.port_dir == "in" else "is driven by"
            stem = "_".join(stem_tokens(fn.name, "valid")) or fn.name
            if stem != fn.name and stem in {self.n(p).name for p in self.ports}:
                # `gnt_valid_o` -> stem `gnt_o` would read as another port's interface
                self.notes.append(f"STREAM {fn.name}: stem '{stem}' is another port's name; "
                                  "interface named after the valid port instead")
                stem = fn.name
            it = Iface(self._unique(stem), "STREAM", fn.port_dir, fwd=f,
                       evidence=[f"{fn.name} {verb} {gm.rel(self.G, x)}: "
                                 f"[{self.p(regs[x]) or gm.rel(self.G, x)}]",
                                 "no ready-class port of the opposite direction gates the "
                                 "registers around this valid"])
            self.ifaces.append(it)
            self.claim(it, f, "valid")

    # -------------------------------------------------------------- step 3: data
    def _flow(self, it: Iface) -> tuple[set[str], set[str], set[str]]:
        """(handshake ports, flow registers, registers driving the handshake ports)."""
        hp = {it.fwd} | ({it.bwd} if it.bwd else set())
        drive: set[str] = set()
        flow: set[str] = set()
        for k in hp:
            drive |= set(self.back(k))
            flow |= set(self.back(k)) | set(self.fwd(k))
        return hp, flow, drive

    def _tier(self, x: str, hp: set[str], flow: set[str], sib: set[str]) -> int | None:
        """1: x is gated by a handshake port; 2: by a flow register; 3: shares a gating
        register with the registers that drive the handshake (same condition); else None.
        (Tier 4, set by the caller: x itself drives valid/ready.)
        Tier 1 also holds when an *input* handshake port gates x on a forward walk: that walk
        passes through output ports, so `in_ready = !v_q || out_ready; if (in_valid &&
        in_ready) d_q <= in_data` ties d_q to out_ready (the backward gaters walk stops at the
        top port in_ready)."""
        g = set(self.gaters(x))
        if g & hp or any(x in self.gates(h) for h in sorted(hp) if self.n(h).port_dir == "in"):
            return 1
        if g & flow:
            return 2
        if g & sib:
            return 3
        return None

    def _slots(self, it: Iface) -> list[tuple[str, str]]:
        """(port direction, side) data slots: side fwd travels with valid/req, bwd with
        ready/ack (REQ_ACK read data)."""
        other = "out" if it.direction == "in" else "in"
        slots = [(it.direction, "fwd")]
        if it.protocol == "REQ_ACK":
            slots.append((other, "bwd"))
        return slots

    def _role(self, it: Iface, k: str, side: str) -> str:
        name = self.n(k).name
        if ADDR_RE.search(name):
            return "addr"
        if WE_RE.search(name):
            return "we"
        if it.protocol == "REQ_ACK":
            return "wdata" if side == "fwd" else "rdata"
        return "data"

    def data(self) -> None:
        hs = [i for i in self.ifaces if i.protocol in ("VALID_READY", "REQ_ACK", "STREAM")]
        offers: dict[str, list] = {}
        for idx, it in enumerate(hs):
            hp, flow, drive = self._flow(it)
            sib = {g for d in drive for g in self.gaters(d)
                   if self.n(g).is_state and g not in hp}
            ftoks = stem_tokens(self.n(it.fwd).name, port_class(self.n(it.fwd).name))
            for dir_, side in self._slots(it):
                for k in self.free(dir_):
                    n = self.n(k)
                    if port_class(n.name) or STATUS_RE.search(n.name):
                        continue
                    paths = gm.data_only(self.fwd(k) if dir_ == "in" else self.back(k))
                    best = None
                    for x in sorted(paths):
                        # a register that drives valid/ready is flow-control state; it counts
                        # only as the weakest tier (4), e.g. `mem_we = (state_q == WB)`
                        t = 4 if x in drive else self._tier(x, hp, flow, sib)
                        if t is not None and (best is None or t < best[0]):
                            best = (t, x)
                    if best is None:
                        continue
                    sim = name_sim(stem_tokens(n.name, None), ftoks)
                    offers.setdefault(k, []).append((-sim, best[0], idx, side, best[1], paths))
        self._enables(hs)
        for k in sorted(offers, key=lambda x: (self.n(x).line, x)):
            if k in self.claimed:
                continue
            _ns, tier, idx, side, x, paths = sorted(offers[k], key=lambda o: o[:3])[0]
            it = hs[idx]
            self.claim(it, k, self._role(it, k, side))
            how = "reaches" if self.n(k).port_dir == "in" else "is driven by"
            gate = {1: "gated by a handshake port", 2: "gated by a handshake flow register",
                    3: "gated like the handshake registers",
                    4: "a register that also drives the handshake"}[tier]
            src = f"{how} {gm.rel(self.G, x)}" if paths[x] else "is itself a register"
            it.evidence.append(f"data {self.n(k).name} {src}, {gate}"
                               + (f": [{self.p(paths[x])}]" if paths[x] else ""))
            if len(offers[k]) > 1:
                others = sorted({hs[o[2]].name for o in offers[k]} - {it.name})
                it.evidence.append(f"{self.n(k).name} also matched {others}; chosen by "
                                   "name-stem similarity, then evidence tier")

    def _enables(self, hs: list[Iface]) -> None:
        """Inputs on the forward side that gate a register the forward handshake port also
        gates, named like a write enable / cycle / select / strobe -> role we|enable. 1-bit
        only, except byte strobes (strb/be), which may be wider (AXI wstrb)."""
        for k in self.free("in"):
            n = self.n(k)
            if port_class(n.name) or not (WE_RE.search(n.name) or EN_RE.search(n.name)):
                continue
            if n.width != 1 and not STRB_RE.search(n.name):
                continue
            best = None
            for idx, it in enumerate(hs):
                if it.direction != "in":
                    continue
                common = sorted(set(self.gates(k)) & set(self.gates(it.fwd)))
                if not common:
                    continue
                ftoks = stem_tokens(self.n(it.fwd).name, port_class(self.n(it.fwd).name))
                key = (-name_sim(stem_tokens(n.name, None), ftoks), -len(common), idx)
                if best is None or key < best[0]:
                    best = (key, it, common[0])
            if best:
                _key, it, x = best
                self.claim(it, k, "we" if WE_RE.search(n.name) else "enable")
                it.evidence.append(f"{n.name} gates {gm.rel(self.G, x)} together with "
                                   f"{self.n(it.fwd).name} (enable-like name picks the slot)")

    # -------------------------------------------------------------- step 4: FIFO
    def _mems(self) -> list[str]:
        G = self.G
        ms = [k for k, n in G.nodes.items() if n.depth is not None and n.is_state]
        return sorted(ms, key=lambda k: (G.nodes[k].inst != self.top, G.nodes[k].line, k))

    def _read_regs(self, m: str) -> tuple[set[str], set[str]]:
        """(registers addressing reads of m, registers holding data read from m)."""
        G = self.G
        ptr, dat = set(), set()
        for t, _et in G.succs(m, {EdgeType.DATA}):
            if t == m:
                continue
            if self.n(t).is_state:
                dat.add(t)
            else:
                dat |= set(gm.data_only(self.fwd(t)))
            for s, _et in G.preds(t, {EdgeType.ADDR}):
                ptr |= {s} if self.n(s).is_state else set(self.back(s))
        return ptr, dat

    def fifo(self) -> None:
        for m in self._mems():
            mn = self.n(m)
            ext = sorted(k for k in self.ports if m in self._addr_targets(k))
            if ext:
                self.notes.append(f"{mn.rel}: addressed by port(s) "
                                  f"{[self.n(k).name for k in ext]}; not a FIFO (MEMORY_BUS "
                                  "template instead)")
                continue
            ptr, dat = self._read_regs(m)
            rd_side = ptr | dat
            wr = [k for k in self.free("in", True) if m in self.gates(k)]
            rd = [k for k in self.free("in", True) if set(self.gates(k)) & rd_side]
            rdata = [k for k in self.free("out")
                     if set(gm.data_only(self.back(k))) & ({m} | dat)]
            # a port gating both sides (`w_wr = i_wr && (!full || i_rd)`) is a weaker
            # candidate for the other side; names only break the remaining ties
            wr.sort(key=lambda k: (k in rd, not WR_RE.search(self.n(k).name), self.n(k).line))
            if not wr:
                self._storage_behind_handshake(m, rd_side)
                continue
            rd = [k for k in rd if k != wr[0]]
            rd.sort(key=lambda k: (k in wr, not RD_RE.search(self.n(k).name), self.n(k).line))
            if not (rd or rdata):
                continue
            it = Iface(self._unique("fifo" if not any(i.protocol == "FIFO" for i in self.ifaces)
                                    else f"fifo_{mn.name}"), "FIFO", "in")
            self.ifaces.append(it)
            w = wr[0]
            self.claim(it, w, "wr")
            it.evidence.append(f"{self.n(w).name} gates write of {mn.rel} (depth {mn.depth}): "
                               f"[{self.p(self.gates(w)[m])}]")
            for k in [k for k in self.free("in") if self._writes_value(k, m)]:
                self.claim(it, k, "wdata")
            if rd:
                r = rd[0]
                x = sorted(set(self.gates(r)) & rd_side)[0]
                self.claim(it, r, "rd")
                it.evidence.append(f"{self.n(r).name} gates read side {gm.rel(self.G, x)}: "
                                   f"[{self.p(self.gates(r)[x])}]")
            for k in rdata:
                if k not in self.claimed:
                    self.claim(it, k, "rdata")
            self._status(it, m, rd_side)
            roles = {r for _k, r in it.members}
            it.confirmed = {"wr", "rd"} <= roles and bool(roles & {"full", "empty"})
            if not it.confirmed:
                missing = sorted({"wr", "rd", "full|empty"} - roles - (
                    {"full|empty"} if roles & {"full", "empty"} else set()))
                it.evidence.append(f"incomplete FIFO template, missing {missing}")
            for extra in wr[1:] + rd[1:]:
                self.notes.append(f"FIFO {it.name}: {self.n(extra).name} also gates "
                                  f"{mn.rel}; left for later templates")

    def _storage_behind_handshake(self, m: str, rd_side: set[str]) -> None:
        """A memory written/read under already-formed handshakes (sync_fifo): record it on
        those interfaces instead of forming a FIFO from ports that are already claimed."""
        mn = self.n(m)
        for it in self.ifaces:
            if it.protocol not in ("VALID_READY", "REQ_ACK", "STREAM"):
                continue
            hp = [k for k in (it.fwd, it.bwd) if k]
            if any(m in self.gates(k) for k in hp):
                side = "written"
            elif any(set(self.gates(k)) & rd_side for k in hp):
                side = "read"
            else:
                continue
            it.evidence.append(f"memory {mn.rel} (depth {mn.depth}, line {mn.line}) is {side} "
                               f"under this handshake; kept as {it.protocol} (the FIFO template "
                               "needs unclaimed wr/rd enable ports)")

    def _writes_value(self, k: str, m: str) -> bool:
        """k's value is written into m (last edge DATA, no CONTROL/ADDR on the way)."""
        p = self.fwd(k).get(m)
        return bool(p) and all(e[2] in ("DATA", "PORT") for e in p)

    def _status(self, it: Iface, m: str, rd_side: set[str]) -> None:
        for k in self.free("out", True):
            n = self.n(k)
            g = set(self.gates(k))
            drv = set(self.back(k))
            role, why = None, ""
            if m in g:
                role, why = "full", "gates the write"
            elif g & rd_side:
                role, why = "empty", "gates the read side"
            elif drv and re.search(r"full", n.name, re.I):
                role, why = "full", "name hint, driven by a register"
            elif drv and re.search(r"empty", n.name, re.I):
                role, why = "empty", "name hint, driven by a register"
            if role and role not in {r for _k, r in it.members}:
                self.claim(it, k, role)
                it.evidence.append(f"{n.name} = {role}: {why}")

    # -------------------------------------------------------- step 5: MEMORY_BUS
    def _addr_targets(self, a: str) -> dict[str, str]:
        """{mem key: via} for ADDR edges from a (through comb nodes) into a mem or a read."""
        G, out = self.G, {}
        frontier, seen = [a], {a}
        for _hop in range(3):
            nxt = []
            for k in frontier:
                for t, et in sorted(G.succs(k, set(gm.DATAISH))):
                    if t in seen or t in self.skip:
                        continue
                    seen.add(t)
                    if et == EdgeType.ADDR:
                        via = G.g.get_edge_data(k, t)[EdgeType.ADDR.value]["via"]
                        if self.n(t).depth is not None:
                            out.setdefault(t, via)
                        for s, _e in G.preds(t, {EdgeType.DATA}):
                            if self.n(s).depth is not None:
                                out.setdefault(s, via)
                    if not self.n(t).is_state:
                        nxt.append(t)
            frontier = nxt
        return out

    def memory_bus(self) -> None:
        cands = sorted(self.free("in"), key=lambda k: (not ADDR_RE.search(self.n(k).name),
                                                       self.n(k).line))
        for a in cands:
            if a in self.claimed:
                continue
            tg = self._addr_targets(a)
            if not tg:
                continue
            m = sorted(tg)[0]
            mn = self.n(m)
            it = Iface(self._unique(f"mem_{mn.name}"), "MEMORY_BUS", "in")
            self.ifaces.append(it)
            self.claim(it, a, "addr")
            it.evidence.append(f"{self.n(a).name} addresses {mn.rel} (depth {mn.depth}) "
                               f"at {tg[m]}")
            for k in self.free("in"):
                if m in self._addr_targets(k):
                    self.claim(it, k, "addr")
            we = [k for k in self.free("in", True) if m in self.gates(k)]
            if we:
                we.sort(key=lambda k: (not WE_RE.search(self.n(k).name), self.n(k).line))
                self.claim(it, we[0], "we")
                it.evidence.append(f"{self.n(we[0]).name} gates write of {mn.rel}")
            for k in self.free("in"):
                if self._writes_value(k, m):
                    self.claim(it, k, "wdata")
            _ptr, dat = self._read_regs(m)
            for k in self.free("out"):
                if set(gm.data_only(self.back(k))) & ({m} | dat):
                    self.claim(it, k, "rdata")
            roles = {r for _k, r in it.members}
            it.confirmed = bool(roles & {"we", "rdata"})
            if not it.confirmed:
                it.evidence.append("address only: no write enable and no read data port")

    # ------------------------------------------------------------ step 6: SERIAL
    VALUE = frozenset({EdgeType.DATA, EdgeType.PORT})

    def _value_neighbors(self, x: str, forward: bool) -> list[str]:
        """Registers one register hop beyond register x along DATA/PORT edges only."""
        if forward:
            return sorted(r for r in self.fwd(x, self.VALUE) if r != x)
        out: set[str] = set()
        for s, _et in self.G.preds(x, set(self.VALUE)):
            if s == x or s in self.skip:
                continue
            out |= {s} if self.n(s).is_state else set(self.back(s, self.VALUE))
        return sorted(out - {x})

    def _is_shift(self, y: str) -> bool:
        """Multi-bit register loaded from itself without +/- (`{b, q[7:1]}`), not a memory."""
        yn = self.n(y)
        return (yn.is_state and yn.width >= 2 and yn.depth is None and y not in yn.arith_srcs
                and self.G.g.has_edge(y, y, EdgeType.DATA.value))

    def _indexing_counters(self, nodes: set[str]) -> dict[str, str]:
        """{counter: via} for counters with an ADDR edge (directly or through combinational
        nodes) into one of `nodes` (a bit-select `q[idx]`)."""
        out: dict[str, str] = {}
        for t in sorted(nodes):
            for s, _et in sorted(self.G.preds(t, {EdgeType.ADDR})):
                via = self.G.g.get_edge_data(s, t)[EdgeType.ADDR.value]["via"]
                srcs = [s] if self.n(s).is_state else sorted(self.back(s))
                for c in srcs:
                    if gm.is_counter(self.G, c):
                        out.setdefault(c, via)
        return out

    def _serial_evidence(self, k: str, paths: dict) -> str | None:
        """Directed serial evidence for 1-bit port k, or None:
        (a) a shift register on the port's value path (or one register hop beyond it) whose
            write is gated (CONTROL) by a counter, or
        (b) a counter addressing (ADDR, bit-select) a multi-bit register / net on that path."""
        fwd = self.n(k).port_dir == "in"
        cone = {k} | set(paths) | {x for p in paths.values() for e in p for x in e[:2]}
        near = set(paths) | {y for x in paths for y in self._value_neighbors(x, fwd)}
        wide = [x for x in sorted(near) if self.n(x).width >= 2 and self.n(x).depth is None
                and not gm.is_counter(self.G, x)]
        idx = self._indexing_counters(cone)
        if idx and wide:
            c = sorted(idx)[0]
            return (f"bit-select of {gm.rel(self.G, wide[0])} indexed by counter "
                    f"{self.n(c).rel} (line {self.n(c).line}) at {idx[c]}")
        for x in sorted(paths):
            if not all(e[2] in ("DATA", "PORT") for e in paths[x]):
                continue
            for y in [x, *self._value_neighbors(x, fwd)]:
                cs = [c for c in sorted(self.gaters(y)) if c != y and gm.is_counter(self.G, c)]
                if not (self._is_shift(y) and cs):
                    continue
                c = cs[0]
                hop = "" if y == x else f" one register hop beyond {gm.rel(self.G, x)}"
                return (f"shift register {gm.rel(self.G, y)} (line {self.n(y).line}){hop}, "
                        f"write gated by counter {self.n(c).rel} (line {self.n(c).line}): "
                        f"[{self.p(self.gaters(y)[c])}]")
        return None

    def serial(self) -> None:
        for k in self.free(width1=True):
            n = self.n(k)
            if port_class(n.name) or STATUS_RE.search(n.name):
                continue
            paths = gm.data_only(self.fwd(k) if n.port_dir == "in" else self.back(k))
            if not paths:
                continue
            why = self._serial_evidence(k, paths)
            if not why:
                continue
            x = sorted(paths)[0]
            it = Iface(self._unique(n.name), "SERIAL", n.port_dir)
            self.ifaces.append(it)
            self.claim(it, k, "serial")
            it.evidence.append(f"1-bit data through {gm.rel(self.G, x)} "
                               f"[{self.p(paths[x]) or gm.rel(self.G, x)}]; {why}")

    # ------------------------------------------------------------ step 7: demote
    def demote(self) -> None:
        for k in self.free():
            n = self.n(k)
            cls = port_class(n.name)
            if not cls:
                continue
            if cls in MATE:
                mate = MATE[cls]
                why = (f"{cls}-class {n.port_dir}put: no {mate}-class port of the opposite "
                       "direction acts on a register tied to it")
                if cls == "valid":
                    why += "; it neither reaches nor is driven by a register (no STREAM)"
            else:
                why = (f"{cls}-class {n.port_dir}put: no unclaimed "
                       f"{'valid' if cls == 'ready' else 'req'}-class port matched it "
                       "structurally")
            if not self.G.preds(k, set(gm.FLOW)) and not self.G.succs(k, set(gm.FLOW)):
                why += " (the port has no connection in this elaboration: unused or disabled " \
                       "by a parameter)"
            it = Iface(self._unique(n.name), "SIMPLE", n.port_dir, confirmed=False,
                       demoted_reason=why)
            self.ifaces.append(it)
            self.claim(it, k, cls if cls in ("valid", "ready", "req", "ack") else "data")

    def run(self) -> list[Iface]:
        self.pairs()
        self.streams()
        self.data()
        self.fifo()
        self.memory_bus()
        self.serial()
        self.demote()
        return self.ifaces
