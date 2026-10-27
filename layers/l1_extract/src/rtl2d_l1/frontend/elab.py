"""Parse + elaborate RTL with slang (pyslang). No synthesis is performed.

The Driver object owns the SourceManager, so it is kept alive inside `Design`.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pyslang
from pyslang import ast, driver

SLANG_VERSION = getattr(pyslang, "__version__", "unknown")


class ElaborationError(RuntimeError):
    pass


@dataclass
class Design:
    name: str
    compilation: ast.Compilation
    tops: list[ast.InstanceSymbol]
    files: list[Path]
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _driver: object = None  # keeps the SourceManager alive
    path_map: dict[str, str] = field(default_factory=dict)  # staged path -> original path

    @property
    def sm(self) -> pyslang.SourceManager:
        return self.compilation.sourceManager

    def line_of(self, sym_or_loc) -> int:
        loc = sym_or_loc if isinstance(sym_or_loc, pyslang.SourceLocation) else sym_or_loc.location
        try:
            return int(self.sm.getLineNumber(loc))
        except Exception:
            return 0

    def file_of(self, sym_or_loc) -> str:
        loc = sym_or_loc if isinstance(sym_or_loc, pyslang.SourceLocation) else sym_or_loc.location
        try:
            return self.original(str(Path(str(self.sm.getFullPath(loc.buffer))).resolve()))
        except Exception:
            try:
                return self.original(str(self.sm.getFileName(loc)))
            except Exception:
                return ""

    def original(self, path: str) -> str:
        return self.path_map.get(os.path.normcase(str(Path(path).resolve())), path)

    def source_hash(self) -> str:
        h = hashlib.sha256()
        for f in sorted(self.files):
            h.update(f.read_bytes())
        return "sha256:" + h.hexdigest()[:16]


def _q(p: str | os.PathLike) -> str:
    return shlex.quote(str(p).replace(os.sep, "/"))


_HDR_EXT = {".svh", ".vh", ".h", ".inc", ".sv", ".v", ".svi", ".vinc"}


def parse_filelist(fl: Path) -> tuple[list[Path], list[Path], list[str]]:
    """Minimal -f parser: files, +incdir+ / -I, +define+ / -D, // and # comments, nested -f."""
    files, incs, defs = [], [], []
    base = fl.parent
    toks: list[str] = []
    for line in fl.read_text(encoding="utf-8", errors="replace").splitlines():
        line = re.sub(r"(//|#).*$", "", line).strip()
        if line:
            toks += shlex.split(line, posix=True)
    it = iter(toks)
    for tok in it:
        tok = os.path.expandvars(tok)
        if tok.startswith("+incdir+"):
            incs += [base / x for x in tok[len("+incdir+") :].split("+") if x]
        elif tok.startswith("+define+"):
            defs += [x for x in tok[len("+define+") :].split("+") if x]
        elif tok in ("-I", "--include-directory"):
            incs.append(base / os.path.expandvars(next(it)))
        elif tok.startswith("-I"):
            incs.append(base / tok[2:])
        elif tok == "-D":
            defs.append(next(it))
        elif tok.startswith("-D"):
            defs.append(tok[2:])
        elif tok in ("-f", "-F"):
            f2, i2, d2 = parse_filelist(base / os.path.expandvars(next(it)))
            files += f2
            incs += i2
            defs += d2
        elif tok.startswith("-") or tok.startswith("+"):
            continue  # simulator-specific option
        else:
            files.append(base / tok)
    return files, incs, defs


def _stage_ascii(
    files: list[Path], incs: list[Path]
) -> tuple[list[Path], list[Path], dict[str, str]]:
    """slang (Windows build) cannot open non-ASCII paths: mirror sources + headers into an
    ASCII temp dir, preserving their relative layout, and return a staged->original map."""
    srcs = [f.resolve() for f in files]
    dirs = {f.parent for f in srcs} | {d.resolve() for d in incs}
    root = Path(os.path.commonpath([str(d) for d in dirs] + [str(f) for f in srcs]))
    if root.is_file():
        root = root.parent
    # keep two parent levels so relative includes like `include "../rtl/config.vh"` still resolve
    for _ in range(2):
        if root.parent != root and str(root.parent) != root.anchor:
            root = root.parent
    key = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:10]
    stage = Path(tempfile.gettempdir()) / "rtl2d_l1_stage" / key
    pmap: dict[str, str] = {}

    def put(p: Path) -> Path:
        dst = stage / p.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if (
            not dst.exists()
            or dst.stat().st_mtime < p.stat().st_mtime
            or dst.stat().st_size != p.stat().st_size
        ):
            shutil.copy2(p, dst)
        pmap[os.path.normcase(str(dst.resolve()))] = str(p)
        return dst

    for d in (
        dirs | {f.parent.parent for f in srcs} | {f.parent.parent / f.parent.name for f in srcs}
    ):
        if not d.is_dir():
            continue
        for h in d.iterdir():
            if h.is_file() and h.suffix.lower() in _HDR_EXT:
                put(h)
    staged = [put(f) for f in srcs]
    staged_incs = [stage / d.resolve().relative_to(root) for d in incs]
    for d in staged_incs:
        d.mkdir(parents=True, exist_ok=True)
    if not str(stage).isascii():
        raise ElaborationError(f"temp dir {stage} is not ASCII; set TMP to an ASCII path")
    return staged, staged_incs, pmap


def elaborate(
    files: list[str | os.PathLike] | None = None,
    *,
    filelist: str | os.PathLike | None = None,
    include_dirs: list[str] | None = None,
    defines: list[str] | None = None,
    top: str | list[str] | None = None,
    name: str | None = None,
    extra_args: list[str] | None = None,
    strict: bool = False,
) -> Design:
    """Elaborate a design. `files` and/or `filelist` (-f) give the sources."""
    files = [Path(f) for f in (files or [])]
    incs = [Path(d) for d in (include_dirs or [])]
    defines = list(defines or [])
    if filelist:
        f2, i2, d2 = parse_filelist(Path(filelist))
        files += f2
        incs += i2
        defines += d2
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise ElaborationError(f"missing source files: {missing[:5]}")
    path_map: dict[str, str] = {}
    if not all(str(p.resolve()).isascii() for p in files + incs):
        files, incs, path_map = _stage_ascii(files, incs)
    args = ["slang"]
    args += [_q(f.resolve()) for f in files]
    for d in incs:
        args += ["-I", _q(d.resolve())]
    for d in defines:
        args += ["-D", shlex.quote(d)]
    tops = [top] if isinstance(top, str) else list(top or [])
    for t in tops:
        args += ["--top", shlex.quote(t)]
    args += ["--disable-instance-caching", "--ignore-unknown-modules", "--allow-use-before-declare"]
    # mixed `timescale / no-timescale files are an error in slang; timing is irrelevant here
    args += ["--timescale=1ns/1ps"]
    args += extra_args or []

    drv = driver.Driver()
    drv.addStandardArgs()
    if not drv.parseCommandLine(" ".join(args), driver.CommandLineOptions()):
        raise ElaborationError(f"bad slang command line: {' '.join(args)}")
    if not drv.processOptions():
        raise ElaborationError("slang processOptions failed")
    if not drv.parseAllSources():
        raise ElaborationError("slang failed to load/parse sources")
    comp = drv.createCompilation()
    root = comp.getRoot()

    errors, warnings = [], []
    sm = comp.sourceManager
    for dg in comp.getAllDiagnostics():
        try:
            line = sm.getLineNumber(dg.location)
            fname = Path(str(sm.getFileName(dg.location))).name
            where = f"{fname}:{line}"
        except Exception:
            where = "?"
        msg = f"{where}: {dg.code}"
        (errors if dg.isError() else warnings).append(msg)
    if strict and errors:
        raise ElaborationError("; ".join(errors[:10]))

    uniq = sorted({Path(path_map.get(os.path.normcase(str(p.resolve())), str(p))) for p in files})

    top_insts = list(root.topInstances)
    if not top_insts:
        raise ElaborationError("no top-level instance found (use --top)")
    return Design(
        name=name or top_insts[0].name,
        compilation=comp,
        tops=top_insts,
        files=uniq,
        errors=errors,
        warnings=warnings,
        _driver=drv,
        path_map=path_map,
    )
