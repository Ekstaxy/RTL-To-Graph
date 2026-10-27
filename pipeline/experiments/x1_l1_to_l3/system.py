"""System-view renderer: the block diagram papers draw for a whole SoC / accelerator.

Grammar (RULES.md S1-S8): every unit is a rectangle with a bold name; teacher groups with
several members become titled containers; one arrow per block pair (per interface at the
boundary) labelled with the interface name or the signal count; arrays drawn once "xN"; a
layered grid left to right; back edges along the bottom; clock and reset omitted.

Input: the bridge's diagram / hints / meta. Wiring helpers the bridge made (join, fields,
adapt blocks) are collapsed back into direct edges: at this level they are not units.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper import _colour, _med, _simplify  # noqa: E402

PAD, TITLE, GAP_MIN, TRACK, ROW_GAP = 14, 18, 44, 8, 22
# teacher group kinds that sit on the target side of a bus (memories, peripherals, adapters)
TARGET_KINDS = {
    "MEMORY",
    "BUFFER",
    "INTERFACE_ADAPTER",
    "SERIALIZER",
    "REGISTER_BANK",
    "COUNTER_TIMER",
}
FONT_W = 6.4  # px per character at 11 px


class Unit:
    def __init__(self, uid: str, label: str, kind: str = "box"):
        self.id, self.label, self.kind = uid, label, kind
        self.members: list[Unit] = []  # container children
        self.parent: Unit | None = None
        self.x = self.y = 0.0
        self.w, self.h = 0.0, 0.0
        self.col = 0
        self.ports: dict[str, tuple[str, float]] = {}  # edge key -> (side, offset)
        self.count = 1
        self.role = "initiator"  # bus-centred layout: initiator (below the bar) or target
        self.gkind = ""  # teacher group kind, when the unit comes from a group
        self.ctrl_bar = False


class Edge:
    def __init__(self, a: str, b: str):
        self.a, self.b = a, b  # unit ids (leaf boxes)
        self.names: list[str] = []
        self.width = 0
        self.n = 0
        self.ctrl = True
        self.back = False
        self.both = False
        self.itf = None  # interface name when one end is the boundary

    @property
    def key(self):
        return f"{self.a}--{self.b}"

    def label(self):
        if self.itf:
            return self.itf
        if self.n == 1:
            return self.names[0]
        return f"{self.n} sig"


class Scene:
    def __init__(self, diagram: dict, meta: dict):
        self.meta = meta
        kinds = meta["kinds"]
        self.wiring = {b["id"] for b in diagram["blocks"] if kinds.get(b["id"]) == "split"}
        self.owner = {p["id"]: p["owner_block_id"] for p in diagram["ports"]}
        self.pname = {p["id"]: p["id"].rsplit(".", 1)[-1] for p in diagram["ports"]}
        self.itf_of = {pid: i["name"] for i in meta.get("interfaces", []) for pid in i["ports"]}
        self.itf_proto = {i["name"]: i["protocol"] for i in meta.get("interfaces", [])}
        # resolve wiring: source port -> list of (final target port, net)
        out_of = defaultdict(list)  # wiring block -> nets it drives
        for n in diagram["nets"]:
            ob = self.owner[n["source"]]
            if ob in self.wiring:
                out_of[ob].append(n)
        self.edges_raw = []  # (src port, dst port, net)
        for n in diagram["nets"]:
            if n["class"] in ("clock", "reset") or self.owner[n["source"]] in self.wiring:
                continue
            for t in self._resolve(n, out_of):
                self.edges_raw.append((n["source"], t, n))
        self.units: dict[str, Unit] = {}
        self.build_units(diagram, meta)
        self.build_edges()

    def _resolve(self, n, out_of, depth=0):
        out = []
        for t in n["targets"]:
            ob = self.owner[t]
            if ob in self.wiring and depth < 6:
                for n2 in out_of.get(ob, []):
                    out += self._resolve(n2, out_of, depth + 1)
            else:
                out.append(t)
        return out

    # ------------------------------------------------------------------ units (S1, S2, S7)
    def build_units(self, diagram, meta):
        labels = meta["labels"]
        blocks = [b["id"] for b in diagram["blocks"] if b["id"] not in self.wiring]
        self.leaf_of: dict[str, str] = {}  # block id -> leaf unit id
        used = set()
        for g in meta.get("teacher_groups", []):
            members = [
                b for b in [*g["instances"], g.get("logic")] if b in blocks and b not in used
            ]
            if not members:
                continue
            name = g["name"]
            inst = [b for b in members if not b.startswith("b.g.")]
            role = "target" if g["kind"] in TARGET_KINDS else "initiator"
            if len(inst) <= 1:  # one instance (+ its glue) or glue only: one box named by the group
                u = Unit("u." + g["name"], name)
                u.role = role
                u.gkind = g["kind"]
                u.count = max(meta.get("count", {}).get(b, 1) for b in members)
                self.units[u.id] = u
                for b in members:
                    self.leaf_of[b] = u.id
            else:  # several instances: a titled container
                c = Unit("u." + g["name"], name, "container")
                c.role = role
                self.units[c.id] = c
                for b in inst:
                    u = Unit("u." + b, labels.get(b, b), "box")
                    u.count = meta.get("count", {}).get(b, 1)
                    u.parent = c
                    c.members.append(u)
                    self.units[u.id] = u
                    self.leaf_of[b] = u.id
                for b in members:
                    if b.startswith("b.g."):
                        self.leaf_of[b] = c.members[0].id  # glue joins the first member
            used |= set(members)
        for b in blocks:
            if b in used:
                continue
            u = Unit("u." + b, labels.get(b, b))
            u.count = meta.get("count", {}).get(b, 1)
            u.role = "target" if meta["kinds"].get(b) in ("memory", "register") else "initiator"
            self.units[u.id] = u
            self.leaf_of[b] = u.id
        self.boundary = Unit("u.__boundary__", "")

    # ------------------------------------------------------------------ edges (S3, S4)
    def build_edges(self):
        agg: dict[tuple, Edge] = {}
        for s, t, n in self.edges_raw:
            sb, tb = self.owner[s], self.owner[t]
            sa = self.leaf_of.get(sb) if sb else f"in:{self.itf_of.get(s, self.pname[s])}"
            ta = self.leaf_of.get(tb) if tb else f"out:{self.itf_of.get(t, self.pname[t])}"
            if sa is None or ta is None or sa == ta:
                continue
            e = agg.setdefault((sa, ta), Edge(sa, ta))
            e.names.append(self.pname[s] if sb else self.pname[t])
            e.width += n["width"]
            e.n += 1
            e.ctrl &= n["class"] == "control"
            if sb is None:
                e.itf = self.itf_of.get(s)
            elif tb is None:
                e.itf = self.itf_of.get(t)
        for e in agg.values():
            e.names = sorted(set(e.names))
        # merge opposite directions into one two-headed edge when both are bundles
        self.edges: list[Edge] = []
        done = set()
        for (a, b), e in agg.items():
            if (a, b) in done:
                continue
            r = agg.get((b, a))
            if (
                r is not None
                and e.n >= 2
                and r.n >= 2
                and not (a.startswith(("in:", "out:")) or b.startswith(("in:", "out:")))
            ):
                e.both, e.n, e.width = True, e.n + r.n, e.width + r.width
                e.names = sorted(set(e.names) | set(r.names))
                done.add((b, a))
            done.add((a, b))
            self.edges.append(e)
        # boundary pseudo-units: one per interface, placed left (inputs) or right (outputs)
        for e in self.edges:
            for end in (e.a, e.b):
                if end.startswith(("in:", "out:")) and end not in self.units:
                    u = Unit(end, end.split(":", 1)[1], "boundary")
                    self.units[end] = u

    # ------------------------------------------------------------------ layout (S5)
    def layout(self):
        top = [u for u in self.units.values() if u.parent is None]
        uid_top = {u.id: u for u in top}

        def top_of(uid):
            u = self.units[uid]
            return u.parent.id if u.parent else uid

        # size leaves
        for u in self.units.values():
            if u.kind == "container":
                continue
            lab = u.label + (f" ×{u.count}" if u.count > 1 else "")
            u.label_txt = lab
            deg = sum(1 for e in self.edges if u.id in (e.a, e.b))
            u.w = max(96, len(lab) * FONT_W + 2 * PAD) if u.kind != "boundary" else 8
            u.h = max(44, 16 * max(2, math.ceil(deg / 2)) + 12) if u.kind != "boundary" else 8
        # layer top-level units by longest path over forward edges
        adj = defaultdict(set)
        for e in self.edges:
            a, b = top_of(e.a), top_of(e.b)
            if a != b:
                adj[a].add(b)
        self.hub = self._find_hub(top)
        order = self._layers(uid_top, adj)
        for u in top:
            u.col = order[u.id]
        if self.hub is None:
            self._layout_level(top, order)
        for c in top:
            if c.kind == "container":
                adj_in = defaultdict(set)
                for e in self.edges:
                    if self.units[e.a].parent is c and self.units[e.b].parent is c:
                        adj_in[e.a].add(e.b)
                ids = {m.id: m for m in c.members}
                ordr = self._layers(ids, adj_in)
                for m in c.members:
                    m.col = ordr[m.id]
                self._layout_level(c.members, ordr, inner=True)
                dx = PAD - min(m.x for m in c.members)
                dy = PAD + TITLE - min(m.y for m in c.members)
                for m in c.members:
                    m.x += dx
                    m.y += dy
                w = max(m.x + m.w for m in c.members) + PAD
                h = max(m.y + m.h for m in c.members) + PAD
                c.w, c.h = max(w, len(c.label) * FONT_W + 2 * PAD), h
        # second pass of top level with real container sizes
        if self.hub is None:
            self._layout_level(top, order)
        else:
            self._layout_bus(top)
        for c in top:
            if c.kind == "container":
                for m in c.members:
                    m.x += c.x
                    m.y += c.y
        dy = 40.0 - min(u.y for u in self.units.values())
        lw = max([len(u.label) for u in self.units.values() if u.id.startswith("in:")], default=0)
        dx = max(0.0, lw * FONT_W + 20 - min(u.x for u in self.units.values()))
        for u in self.units.values():
            u.y += dy
            u.x += dx
        self.width = max(u.x + u.w for u in self.units.values()) + 60
        self.height = max(u.y + u.h for u in self.units.values()) + 60

    def _find_hub(self, top):
        """S9: a crossbar / interconnect / arbiter that most units attach to."""
        units = [u for u in top if u.kind != "boundary"]
        by = {t.id: t for t in top}
        best = None
        if getattr(self, "force_layered", False):
            return None
        for u in units:
            nb = {
                self._up(self._other(e, u.id), {t.id: t for t in top})
                for e in self.edges
                if u.id in (e.a, e.b)
            }
            nb = {n for n in nb if n != u.id and not n.startswith(("in:", "out:"))}
            deg = len(nb)
            named = any(
                k in u.label.lower()
                for k in ("xbar", "crossbar", "interconnect", "bus", "decode", "demux", "switch")
            )
            if not (named and deg >= 3 and deg >= 0.5 * (len(units) - 1)):
                continue
            into = {self._up(e.a, by) for e in self.edges if self._up(e.b, by) == u.id}
            outof = {self._up(e.b, by) for e in self.edges if self._up(e.a, by) == u.id}
            skip = {u.id}
            into = {x for x in into if x not in skip and not x.startswith(("in:", "out:"))}
            outof = {x for x in outof if x not in skip and not x.startswith(("in:", "out:"))}
            if into and outof:
                if best is None or deg > best[0]:
                    best = (deg, u)
        if best:
            return best[1]
        # S10 (CV32E40P, Ibex): a flat module's controller that talks to most units becomes a
        # bar across the top, every other unit in one row below it
        for u in units:
            nb = {self._up(self._other(e, u.id), by) for e in self.edges if u.id in (e.a, e.b)}
            nb = {n for n in nb if n != u.id and not n.startswith(("in:", "out:"))}
            if u.gkind == "CONTROLLER" and len(units) >= 5 and len(nb) >= 0.6 * (len(units) - 1):
                if best is None or len(nb) > best[0]:
                    best = (len(nb), u)
        if best:
            best[1].ctrl_bar = True
            return best[1]
        return None

    def _layout_bus(self, top):
        """Hub as a wide bar; initiators below, targets above, short vertical arrows."""
        hub = self.hub
        by_id = {u.id: u for u in top}
        rows = {"above": [], "below": []}
        for u in top:
            if u is hub or u.kind == "boundary":
                continue
            on_bus = any(
                hub.id in (self._up(e.a, by_id), self._up(e.b, by_id))
                and u.id in (self._up(e.a, by_id), self._up(e.b, by_id))
                for e in self.edges
            )
            if not on_bus:
                # not on the bus: join the row of the units it talks to most
                nbs = [
                    self._up(self._other(e, u.id), by_id) for e in self.edges if u.id in (e.a, e.b)
                ]
                score = sum(1 for n in nbs if any(v.id == n for v in rows["above"])) - sum(
                    1 for n in nbs if any(v.id == n for v in rows["below"])
                )
                rows["above" if score > 0 else "below"].append(u)
            elif hub.ctrl_bar:
                rows["below"].append(u)
            else:
                rows["above" if u.role == "target" else "below"].append(u)
        for key in rows:
            rows[key].sort(key=lambda u: u.label.lower())
        x0 = 40.0
        widths = {
            k: sum(u.w for u in r) + ROW_GAP * 2 * max(0, len(r) - 1) for k, r in rows.items()
        }
        span = max(widths.values(), default=200.0)
        bar_h = 34.0
        top_h = max([u.h for u in rows["above"]], default=0.0)
        y_bar = 40.0 + top_h + 56.0
        for key, r in rows.items():
            x = x0 + (span - widths[key]) / 2
            for u in r:
                u.x = x
                u.y = (y_bar - 56.0 - u.h) if key == "above" else (y_bar + bar_h + 56.0)
                x += u.w + ROW_GAP * 2
        hub.x, hub.w, hub.y, hub.h = x0, max(span, hub.w), y_bar, bar_h
        hub.label_txt = hub.label + (f" ×{hub.count}" if hub.count > 1 else "")
        # boundary stubs: inputs left, outputs right, at the height of what they connect to
        for u in top:
            if u.kind != "boundary":
                continue
            ys = [
                by_id[self._up(self._other(e, u.id), by_id)].y + 20
                for e in self.edges
                if u.id in (e.a, e.b)
            ]
            u.y = _med(ys) if ys else y_bar
            u.x = x0 - 60 if u.id.startswith("in:") else x0 + span + 60
        for side in ("in:", "out:"):
            us = sorted([u for u in top if u.id.startswith(side)], key=lambda u: u.y)
            lo = 0.0
            for u in us:
                u.y = max(u.y, lo)
                lo = u.y + 18
        self.rows = rows

    def _layers(self, ids: dict, adj) -> dict:
        # drop a small weighted feedback set (Eades-Lin-Smyth), then longest path from sources
        w = defaultdict(int)
        for e in self.edges:
            a, b = self._up(e.a, ids), self._up(e.b, ids)
            if a != b and a in ids and b in ids:
                w[(a, b)] += e.n
        left = set(ids)
        heads, tails = [], []
        while left:
            sinks = [u for u in left if all((u, v) not in w for v in left)]
            if sinks:
                u = sorted(sinks)[0]
                left.discard(u)
                tails.append(u)
                continue
            srcs = [u for u in left if all((v, u) not in w for v in left)]
            if srcs:
                u = sorted(srcs, key=lambda i: (not i.startswith("in:"), i))[0]
            else:
                u = max(
                    sorted(left),
                    key=lambda u: sum(w[(u, v)] for v in left) - sum(w[(v, u)] for v in left),
                )
            left.discard(u)
            heads.append(u)
        seq = heads + tails[::-1]
        pos = {u: i for i, u in enumerate(seq)}
        back = {(a, b) for (a, b) in w if pos[a] > pos[b]}
        self.back_edges = getattr(self, "back_edges", set()) | back
        layer = {}

        def depth(u, path=()):
            if u in layer:
                return layer[u]
            preds = [a for a in ids if u in adj.get(a, ()) and (a, u) not in back and a not in path]
            layer[u] = 1 + max((depth(a, path + (u,)) for a in preds), default=-1)
            return layer[u]

        for u in ids:
            depth(u)
        outs = [u for u in ids if u.startswith("out:")]
        ins = [u for u in ids if u.startswith("in:")]
        mid = [u for u in ids if u not in outs and u not in ins]
        if mid:
            last = max(layer[u] for u in mid)
            for u in outs:
                layer[u] = last + 1
            for u in ins:
                layer[u] = 0
            for u in mid:
                layer[u] = max(1 if ins else 0, layer[u])
        return layer

    def _layout_level(self, units: list[Unit], order: dict, inner: bool = False):
        cols = defaultdict(list)
        for u in units:
            cols[order[u.id]].append(u)
        by_id = {u.id: u for u in units}
        x = PAD if inner else 40.0
        ncol = max(cols) + 1 if cols else 0
        # barycenter ordering, a few sweeps
        pos = {u.id: i for c in cols.values() for i, u in enumerate(c)}
        for _ in range(4):
            for c in range(ncol):

                def bc(u):
                    ns = [self._other(e, u.id) for e in self.edges if u.id in (e.a, e.b)]
                    ns = [self._up(n, by_id) for n in ns]
                    vals = [pos[n] for n in ns if n in pos and n != u.id]
                    return _med(vals) if vals else pos[u.id]

                cols[c].sort(key=lambda u: (bc(u), u.id))
                for i, u in enumerate(cols[c]):
                    pos[u.id] = i
        self.colx = {}
        for c in range(ncol):
            self.colx[c] = x
            y = PAD + TITLE if inner else 40.0
            for u in cols[c]:
                u.x, u.y = x, y
                y += u.h + ROW_GAP
            x += max(u.w for u in cols[c]) + (GAP_MIN if inner else GAP_MIN + 40)
        # vertical alignment: pull each unit toward the median of its neighbours, keep order
        for _ in range(6):
            for c in range(ncol):
                want = {}
                for u in cols[c]:
                    ys = []
                    for e in self.edges:
                        if u.id not in (e.a, e.b):
                            continue
                        o = self._up(self._other(e, u.id), by_id)
                        if o in by_id and o != u.id:
                            ou = by_id[o]
                            ys.append(ou.y + ou.h / 2 - u.h / 2)
                    want[u.id] = _med(ys) if ys else u.y
                lo = PAD + TITLE if inner else 40.0
                for u in cols[c]:
                    u.y = max(want[u.id], lo)
                    lo = u.y + u.h + ROW_GAP

    def _other(self, e: Edge, uid: str) -> str:
        return e.b if e.a == uid else e.a

    def _up(self, uid: str, by_id: dict) -> str:
        u = self.units[uid]
        while u.id not in by_id and u.parent is not None:
            u = u.parent
        return u.id

    # ------------------------------------------------------------------ ports + routing (S6)
    def route(self):
        """Every vertical lives in a gap between columns, never under a box (S6).

        Forward: source R side -> track in the gap left of the target -> target L side.
        Blocked forward (a box in between at that height): up to a top channel first.
        Back: source R side -> gap right of source -> bottom channel -> gap left of target
        -> target L side.  Gaps widen to the tracks they carry."""
        hub = getattr(self, "hub", None)
        self.hub_edges, self.margin_edges = set(), {}
        ends = defaultdict(list)  # unit id -> [(edge, side)]
        k = kl = 0
        for e in self.edges:
            ua, ub = self.units[e.a], self.units[e.b]
            e.back = ub.x + ub.w / 2 < ua.x + ua.w / 2
            boundary = ua.kind == "boundary" or ub.kind == "boundary"
            if hub is not None and hub.id in (e.a, e.b) and not boundary:
                self.hub_edges.add(e.key)
                other = ub if e.a == hub.id else ua
                below = other.y > hub.y
                other.ports[e.key] = ("T" if below else "B", other.w / 2)
                hub.ports[e.key] = ("B" if below else "T", other.x + other.w / 2 - hub.x)
                continue
            if hub is not None:
                ca, cb = ua.y + ua.h / 2, ub.y + ub.h / 2
                crosses = min(ca, cb) < hub.y + hub.h + 2 and max(ca, cb) > hub.y - 2
                if crosses or (ca < hub.y) != (cb < hub.y):
                    # a gap vertical here would cut the bar: go around through a margin
                    if ua.id.startswith("in:"):
                        self.margin_edges[e.key] = hub.x - 24 - kl * TRACK
                        kl += 1
                        ends[e.a].append((e, "R"))
                        ends[e.b].append((e, "L"))
                    else:
                        self.margin_edges[e.key] = hub.x + hub.w + 24 + k * TRACK
                        k += 1
                        ends[e.a].append((e, "R"))
                        if ub.id.startswith("out:"):
                            ends[e.b].append((e, "L"))
                        else:
                            ends[e.b].append((e, "T" if cb < hub.y else "B"))
                    continue
            ends[e.a].append((e, "R"))
            ends[e.b].append((e, "L"))
        for uid, lst in ends.items():
            u = self.units[uid]
            for side in "LRTB":
                es = [e for e, sd in lst if sd == side]
                es.sort(key=lambda e: self.units[self._other(e, uid)].y)
                for i, e in enumerate(es):
                    if side in "LR":
                        u.ports[e.key] = (side, (u.h - (len(es) - 1) * 16) / 2 + i * 16)
                    else:  # beside the hub arrow at the centre
                        u.ports[e.key] = (side, u.w / 2 + 14 * (i + 1))
        if self.margin_edges:
            right = max(self.margin_edges.values())
            left = min(self.margin_edges.values())
            for u in self.units.values():
                if u.id.startswith("out:"):
                    u.x = max(u.x, right + 20)
                if u.id.startswith("in:"):
                    u.x = min(u.x, left - 20)
            dx = max(0.0, 40 - min(u.x for u in self.units.values()))
            if dx:
                for u in self.units.values():
                    u.x += dx
                self.margin_edges = {k: v + dx for k, v in self.margin_edges.items()}
        if hub is not None:
            boxes = [u for u in self.units.values() if u.kind != "boundary" and u is not hub]
            self.row_top = min([u.y for u in boxes if u.y < hub.y], default=hub.y) - 10
            self.row_bot = (
                max([u.y + u.h for u in boxes if u.y > hub.y], default=hub.y + hub.h) + 10
            )
            self.margin_rank = {k: i for i, k in enumerate(self.margin_edges)}
            need = (len(self.margin_rank) + 1) * TRACK + 20 - self.row_top
            if need > 0:
                for u in self.units.values():
                    u.y += need
                self.row_top += need
                self.row_bot += need
        for _ in range(2):  # assign tracks, widen gaps, assign again on the new geometry
            self._tracks()
            self._widen()
        self._tracks()
        self.top_y = min(u.y for u in self.units.values()) - 16
        need = (1 + max(self.otrack.values(), default=-1)) * TRACK + 24 - self.top_y
        if need > 0:
            for u in self.units.values():
                u.y += need
            self.top_y += need
        self.bot_y = max(u.y + u.h for u in self.units.values()) + 24
        self.width = max(u.x + u.w for u in self.units.values()) + 60
        if self.margin_edges:
            self.width = max(self.width, max(self.margin_edges.values()) + 40)
        self.height = self.bot_y + (1 + max(self.ctrack.values(), default=0)) * TRACK + 40

    def _cols(self):
        """Distinct left edges of boxes / boundary stubs, ascending: gap g sits just left of
        column x = g."""
        return sorted({round(u.x) for u in self.units.values() if u.kind != "container"})

    def _gap_after(self, x: float) -> int:
        cols = self._cols()
        return next((c for c in cols if c > x + 0.5), cols[-1] + 1)

    def _tracks(self):
        gap_iv, chan_iv, top_iv = defaultdict(list), [], []
        boxes = [u for u in self.units.values() if u.kind == "box"]
        self.over = set()
        for e in self.edges:
            if e.key in self.hub_edges or e.key in getattr(self, "margin_edges", {}):
                continue
            (sx, sy), (tx, ty) = self.end_xy(e, e.a), self.end_xy(e, e.b)
            gs, gt = self._gap_after(sx), round(tx)
            if not e.back:
                blocked = any(
                    u.x > sx + 1 and u.x + u.w < tx - 1 and u.y - 3 < sy < u.y + u.h + 3
                    for u in boxes
                    if u.id not in (e.a, e.b)
                )
                if blocked and gs != gt:
                    self.over.add(e.key)
                    top_iv.append((e.key, min(sx, tx), max(sx, tx), "o", [], []))
                    gap_iv[gs].append((e.key, -1e9, sy, "s", [sy], []))
                    gap_iv[gt].append((e.key, -1e9, ty, "t", [], [ty]))
                else:
                    gap_iv[gt].append((e.key, min(sy, ty), max(sy, ty), "t", [sy], [ty]))
            else:
                chan_iv.append((e.key, min(sx, tx), max(sx, tx), "c", [], []))
                gap_iv[gs].append((e.key, sy, 1e9, "s", [sy], []))
                gap_iv[gt].append((e.key, ty, 1e9, "t", [], [ty]))
        self.gtrack = {g: _colour(iv) for g, iv in gap_iv.items()}
        self.ctrack = _colour(chan_iv)
        self.otrack = _colour(top_iv)

    def _widen(self):
        """Shift columns right so each gap holds its tracks: 12 px margin each side."""
        cols = self._cols()
        shift = 0.0
        moves = []
        for g in cols:
            left = max(
                [
                    u.x + u.w
                    for u in self.units.values()
                    if u.kind != "container" and u.x + u.w <= g + 0.5
                ],
                default=0.0,
            )
            k = 1 + max(self.gtrack.get(g, {}).values(), default=-1)
            need = 24 + k * TRACK
            have = g - left
            moves.append((g, max(0.0, need - have)))
        for g, d in moves:
            shift += d
            if d:
                for u in self.units.values():
                    if u.x >= g - 0.5 and u.kind != "container":
                        u.x += d
        for c in self.units.values():
            if c.kind == "container" and c.members:
                c.x = min(m.x for m in c.members) - PAD
                c.w = max(m.x + m.w for m in c.members) + PAD - c.x

    def path(self, e):
        (sx, sy), (tx, ty) = self.end_xy(e, e.a), self.end_xy(e, e.b)
        if e.key in getattr(self, "margin_edges", {}):
            xm = self.margin_edges[e.key]
            side = self.units[e.b].ports[e.key][0]
            if side == "T":  # over the row, down into the target
                cy = self.row_top - (self.margin_rank[e.key] + 1) * TRACK
                return [(sx, sy), (xm, sy), (xm, cy), (tx, cy), (tx, ty)]
            if side == "B":  # under the row, up into the target
                cy = self.row_bot + (self.margin_rank[e.key] + 1) * TRACK
                return [(sx, sy), (xm, sy), (xm, cy), (tx, cy), (tx, ty)]
            return [(sx, sy), (xm, sy), (xm, ty), (tx, ty)]
        if e.key in self.hub_edges:
            # two edges between the same pair sit side by side
            twin = any(o is not e and {o.a, o.b} == {e.a, e.b} for o in self.edges)
            dx = (-6 if e.a == self.hub.id else 6) if twin else 0
            return [(sx + dx, sy), (tx + dx, ty)]
        gs, gt = self._gap_after(sx), round(tx)
        if not e.back and e.key in self.over:
            xs = self.gapx(gs, e.key, "s")
            xt = self.gapx(gt, e.key, "t")
            oy = self.top_y - self.otrack[(e.key, "o")] * TRACK
            return [(sx, sy), (xs, sy), (xs, oy), (xt, oy), (xt, ty), (tx, ty)]
        if not e.back:
            x = self.gapx(gt, e.key, "t")
            return [(sx, sy), (x, sy), (x, ty), (tx, ty)]
        xs = self.gapx(gs, e.key, "s")
        xt = self.gapx(gt, e.key, "t")
        cy = self.bot_y + self.ctrack[(e.key, "c")] * TRACK
        return [(sx, sy), (xs, sy), (xs, cy), (xt, cy), (xt, ty), (tx, ty)]

    def end_xy(self, e, uid: str):
        u = self.units[uid]
        side, off = u.ports[e.key]
        if side == "L":
            return (u.x, u.y + off)
        if side == "R":
            return (u.x + u.w, u.y + off)
        if side == "T":
            return (u.x + off, u.y)
        return (u.x + off, u.y + u.h)

    # ------------------------------------------------------------------ render (S1-S8)
    def svg(self, title: str = "") -> str:
        o = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" '
            f'height="{self.height:.0f}" viewBox="0 0 {self.width:.0f} {self.height:.0f}" '
            'font-family="Helvetica, Arial, sans-serif" font-size="11">',
            '<defs><marker id="ar" viewBox="0 0 8 8" refX="7.5" refY="4" markerWidth="9" '
            'markerHeight="9" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
            '<path d="M0,0 L8,4 L0,8 z" fill="#000"/>'
            '</marker></defs><rect width="100%" height="100%" fill="#fff"/>',
        ]
        for u in self.units.values():
            if u.kind == "container":
                o.append(
                    f'<g data-rtl2d-kind="container" data-rtl2d-id="{u.id}">'
                    f'<rect x="{u.x}" y="{u.y}" width="{u.w:.0f}" height="{u.h:.0f}" rx="4" '
                    'fill="#fff" stroke="#000" stroke-width="1.2"/>'
                    f'<text x="{u.x + 8:.0f}" y="{u.y + 14:.0f}" font-weight="bold">'
                    f"{_esc(u.label)}</text></g>"
                )
        for e in self.edges:
            pts = _simplify(self.path(e))
            d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            sw = 1.0 + min(2.5, math.log2(max(1, e.width)) * 0.35)
            dash = ' stroke-dasharray="4 2.5"' if e.ctrl else ""
            mk = ' marker-end="url(#ar)"' + (' marker-start="url(#ar)"' if e.both else "")
            o.append(
                f'<path data-rtl2d-kind="wire" data-rtl2d-id="{e.key}" d="{d}" fill="none" '
                f'stroke="#000" stroke-width="{sw:.1f}"{dash}{mk}/>'
            )
            # label on the longest horizontal run, above it (below on odd tracks)
            hs = [
                (abs(b[0] - a[0]), a, b)
                for a, b in zip(pts, pts[1:], strict=False)
                if abs(a[1] - b[1]) < 0.01
            ]
            boundary = e.a.startswith(("in:", "out:")) or e.b.startswith(("in:", "out:"))
            if hs and not boundary and e.n == 1 and e.key not in self.hub_edges:
                _, a, b = max(hs, key=lambda h: h[0])
                lx, ly = (a[0] + b[0]) / 2, a[1]
                up = (hash(e.key) & 1) == 0
                o.append(
                    f'<text x="{lx:.0f}" y="{ly - 4 if up else ly + 11:.0f}" font-size="9" '
                    f'text-anchor="middle">{_esc(e.label())}</text>'
                )
        for u in self.units.values():
            if u.kind == "container":
                continue
            if u.kind == "boundary":
                side_in = u.id.startswith("in:")
                tx = u.x - 6 if side_in else u.x + u.w + 6
                anchor = "end" if side_in else "start"
                o.append(
                    f'<text x="{tx:.0f}" y="{u.y + u.h / 2 + 4:.0f}" text-anchor="{anchor}" '
                    f'font-weight="bold">{_esc(u.label)}</text>'
                )
                continue
            stack = (
                f'<rect x="{u.x + 5:.1f}" y="{u.y + 5:.1f}" width="{u.w:.0f}" height="{u.h:.0f}" '
                'fill="#fff" stroke="#000" stroke-width="1.2"/>'
                if u.count > 1
                else ""
            )
            o.append(
                f'<g data-rtl2d-kind="block" data-rtl2d-id="{u.id}" '
                f'data-rtl2d-bbox="{u.x:.1f} {u.y:.1f} {u.w:.1f} {u.h:.1f}">{stack}'
                f'<rect x="{u.x:.1f}" y="{u.y:.1f}" width="{u.w:.0f}" height="{u.h:.0f}" '
                'fill="#fff" stroke="#000" stroke-width="1.6"/>'
                f'<text x="{u.x + u.w / 2:.0f}" y="{u.y + u.h / 2 + 4:.0f}" text-anchor="middle" '
                f'font-weight="bold">{_esc(u.label_txt)}</text></g>'
            )
        if title:
            o.append(
                f'<text x="8" y="{self.height - 8:.0f}" font-size="9" fill="#555">'
                f"{_esc(title)}</text>"
            )
        o.append("</svg>")
        return "\n".join(o)

    def gapx(self, g: int, key: str, tag: str) -> float:
        """Track k of gap g; higher k is further right, as _colour's ordering assumes."""
        tr = self.gtrack[g]
        k = tr[(key, tag)]
        nk = 1 + max(tr.values())
        return g - 12 - (nk - 1 - k) * TRACK


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _draw(diagram, meta, title, layered: bool):
    sc = Scene(diagram, meta)
    sc.force_layered = layered
    sc.layout()
    sc.route()
    return sc, sc.svg(title)


def render(diagram: dict, hints: dict, meta: dict, title: str = "") -> tuple[str, dict]:
    """Layered layout, or the bus-centred one (S9) when it is at least as clean."""
    import svgmetric

    sc, svg = _draw(diagram, meta, title, layered=True)
    try:
        sc_b, svg_b = _draw(diagram, meta, title, layered=False)
    except (KeyError, ValueError):  # the bus layout is an option, never a failure
        sc_b = None
    if sc_b is not None and sc_b.hub is not None:
        ma, mb = svgmetric.metrics(svg), svgmetric.metrics(svg_b)
        if (mb["through"] + mb["overlap"], mb["cross"]) <= (
            ma["through"] + ma["overlap"],
            ma["cross"],
        ):
            sc, svg = sc_b, svg_b
    return svg, {
        "units": len([u for u in sc.units.values() if u.kind != "boundary"]),
        "containers": sum(u.kind == "container" for u in sc.units.values()),
        "edges": len(sc.edges),
    }


def main(stem: str) -> None:
    ld = lambda k: json.loads(Path(f"{stem}.{k}.json").read_text(encoding="utf-8"))  # noqa: E731
    svg, m = render(ld("diagram"), ld("hints"), ld("meta"), title=Path(stem).name + " (system)")
    Path(f"{stem}.system.svg").write_text(svg, encoding="utf-8")
    print(Path(stem).name, m)


if __name__ == "__main__":
    main(sys.argv[1])
