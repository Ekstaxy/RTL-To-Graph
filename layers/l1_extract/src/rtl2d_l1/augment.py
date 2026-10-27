"""Semantics-preserving augmentation with free label transfer (SPEC §8.2).

Entity IDs depend only on declaration order, so renaming identifiers and
stripping comments keep every ID; labels transfer by ID. Each variant is
re-elaborated and checked (same ID count, names mapped as expected).
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from pathlib import Path

from .frontend.entities import EntityTable

_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
SV_KEYWORDS = set(
    """always always_comb always_ff always_latch and assign automatic begin bit buf byte case casex
    casez cmos const default defparam disable do else end endcase endfunction endgenerate endmodule
    endpackage endtask enum for foreach forever function generate genvar if import initial inout
    input int integer localparam logic longint module nand negedge nor not or output package
    parameter posedge priority reg repeat return shortint signed struct task tri typedef union
    unique unsigned void while wire wor xor xnor""".split()
)


# names declared by (local)parameter statements: `localparam int A = 1, B = 2;` /
# `parameter [3:0] S0=0, S1=1;`
_PARAM_STMT = re.compile(r"\b(localparam|parameter)\b([^;]*);")


def _param_names(seg: str, include_parameters: bool) -> list[str]:
    out = []
    for kind, body in _PARAM_STMT.findall(seg):
        if kind == "parameter" and not include_parameters:
            continue
        depth, cur, parts = 0, "", []
        for ch in body:  # split on top-level commas only; stop at the `)` closing a #( ... ) list
            depth += ch in "([{"
            depth -= ch in ")]}"
            if depth < 0:
                break
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for part in parts:
            lhs = part.split("=")[0]
            ids = _ID.findall(re.sub(r"\[[^\]]*\]", " ", lhs))
            if ids:
                out.append(ids[-1])
    return out


@dataclass
class Variant:
    name: str
    path: Path
    mapping: dict[str, str]  # old identifier -> new identifier
    top: str | None = None  # new module name when the module itself was renamed


def transform_text(
    text: str,
    mapping: dict[str, str],
    strip_comments: bool,
    line_range: tuple[int, int] | None = None,
) -> str:
    """Rename identifiers (not after '.', '`' or '$'; not in strings/comments) and optionally drop
    comments. Comments are replaced by spaces/newlines so line numbers are preserved."""
    out: list[str] = []
    i, n, line = 0, len(text), 1
    lo, hi = line_range or (1, 10**9)
    prev_sig = ""  # last non-space char emitted
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append("" if strip_comments else text[i:j])
            i = j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            seg = text[i:j]
            out.append("\n" * seg.count("\n") if strip_comments else seg)
            line += seg.count("\n")
            i = j
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
            prev_sig = '"'
            continue
        if c == "\\":  # escaped identifier: copy verbatim up to whitespace
            j = i
            while j < n and not text[j].isspace():
                j += 1
            out.append(text[i:j])
            i = j
            continue
        m = _ID.match(text, i)
        if m and not (i > 0 and (text[i - 1].isalnum() or text[i - 1] in "_$'")):
            w = m.group(0)
            if (
                lo <= line <= hi
                and w in mapping
                and prev_sig not in (".", "`", "$")
                and w not in SV_KEYWORDS
            ):
                out.append(mapping[w])
            else:
                out.append(w)
            prev_sig = w[-1]
            i = m.end()
            continue
        if c == "\n":
            line += 1
        if not c.isspace():
            prev_sig = c
        out.append(c)
        i += 1
    return "".join(out)


def obfuscated_names(names: list[str], seed: int) -> dict[str, str]:
    rnd = random.Random(seed)
    pool = list(range(len(names)))
    rnd.shuffle(pool)
    return {
        nm: f"n{p}_{hashlib.md5((nm + str(seed)).encode()).hexdigest()[:3]}"
        for nm, p in zip(names, pool, strict=False)
    }


def rename_variant(
    table: EntityTable,
    out_dir: str | Path,
    *,
    include_ports: bool = False,
    strip_comments: bool = True,
    seed: int = 0,
    tag: str | None = None,
) -> Variant:
    """Write a renamed copy of the module's file. Ports are kept unless include_ports
    (ports renamed only makes sense for a standalone/top module)."""
    src = Path(table.file)
    text = src.read_text(encoding="utf-8", errors="replace")
    names = []
    for r in table.rows:
        if r.kind == "inst":
            continue
        if r.kind.startswith("port_") and not include_ports:
            continue
        base = r.name.split(".")[-1]
        if "[" in base or not _ID.fullmatch(base):
            continue
        names.append(base)
        # enum literals and typedef names leak intent (S_IDLE, state_t): rename them too
        names += [v for v in r.enum_values if _ID.fullmatch(v)]
        tdef = r.type_str.split(".")[-1].split("[")[0].strip()
        if r.enum_values and _ID.fullmatch(tdef) and tdef not in SV_KEYWORDS:
            names.append(tdef)
    seg = "\n".join(text.splitlines()[table.line_start - 1 : table.line_end])
    # localparams are internal; parameters may be overridden by a parent, so only for standalone
    # modules
    names += _param_names(seg, include_parameters=include_ports)
    module_new = None
    if include_ports:  # standalone module: its own name leaks intent as well
        names.append(table.module)
    names = [n for n in names if n not in SV_KEYWORDS]
    mapping = obfuscated_names(sorted(set(names)), seed)
    if include_ports:
        module_new = mapping[table.module]
    new = transform_text(text, mapping, strip_comments, (table.line_start, table.line_end))
    tag = tag or f"ren{'P' if include_ports else ''}{'C' if strip_comments else ''}_s{seed}"
    out = Path(out_dir) / tag
    out.mkdir(parents=True, exist_ok=True)
    dst = out / src.name
    dst.write_text(new, encoding="utf-8")
    return Variant(name=tag, path=dst, mapping=mapping, top=module_new)


def transfer_labels(gold: dict, mapping: dict[str, str]) -> dict:
    """Gold/annotation JSON (by id) -> same ids, renamed `name` fields."""

    def ren(nm: str) -> str:
        parts = nm.split(".")
        parts[-1] = mapping.get(parts[-1], parts[-1])
        return ".".join(parts)

    g = dict(gold)
    g["anchors"] = [dict(a, name=ren(a["name"])) for a in gold.get("anchors", [])]
    return g
