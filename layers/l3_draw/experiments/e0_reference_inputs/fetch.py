"""Download reference block diagrams listed in sources.toml.

Images go to runs/e0_reference_inputs/refs/ (not version-controlled: mixed licences).
manifest.json next to this file records where every image came from.

Run: uv run --package rtl2d-l3 python layers/l3_draw/experiments/e0_reference_inputs/fetch.py
     [--all] [--only NAME ...]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile
import tomllib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFS = HERE.parents[3] / "runs" / "e0_reference_inputs" / "refs"
IMAGE_EXT = {".svg", ".png", ".jpg", ".jpeg", ".pdf", ".drawio"}
FIGURE_EXT = IMAGE_EXT | {".eps", ".tikz"}
DEFAULT_KEYWORDS = r"block|diagram|arch|overview|pipeline|datapath|structure|top"
MAX_BYTES = 5_000_000
USER_AGENT = "rtl2d-e0-reference-inputs (research; contact: repo owner)"


def git(*args: str, cwd: Path | None = None) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return res.stdout


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_repo(src: dict, everything: bool) -> list[dict]:
    """Blobless clone, then check out only the image files we want."""
    name = src["name"]
    work = REFS / ".git_cache" / name
    if not work.exists():
        work.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
            "--branch", src["ref"], src["url"], str(work))  # fmt: skip
    commit = git("rev-parse", "HEAD", cwd=work).strip()

    paths = [re.compile(p) for p in src["paths"]]
    keywords = re.compile(src.get("keywords", DEFAULT_KEYWORDS), re.IGNORECASE)
    wanted = []
    # No `ls-tree -l`: asking for sizes makes a blobless clone download every blob one by one.
    for path in git("ls-tree", "-r", "--name-only", "HEAD", cwd=work).splitlines():
        p = Path(path)
        if p.suffix.lower() not in IMAGE_EXT or not any(r.search(path) for r in paths):
            continue
        if everything or keywords.search(p.name):
            wanted.append(path)

    # A sparse checkout fetches all the wanted blobs in one request.
    sparse = work / ".git" / "info" / "sparse-checkout"
    git("config", "core.sparseCheckout", "true", cwd=work)
    git("config", "core.sparseCheckoutCone", "false", cwd=work)
    sparse.parent.mkdir(parents=True, exist_ok=True)
    sparse.write_text("".join(f"/{re.sub(r'([*?\[\]!#\\])', r'\\\1', p)}\n" for p in wanted))
    git("checkout", "--force", "HEAD", cwd=work)

    dest = REFS / name
    if dest.exists():
        shutil.rmtree(dest)
    entries = []
    seen: set[str] = set()
    for path in sorted(wanted):
        if (work / path).is_symlink() or (work / path).stat().st_size > MAX_BYTES:
            continue
        digest = sha256(work / path)
        if digest in seen:  # OpenTitan keeps identical copies under ip_templates/ and ip_autogen/
            continue
        seen.add(digest)
        out = dest / path
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(work / path, out)
        entries.append({
            "file": str(out.relative_to(REFS)),
            "source": f"{src['url']}/blob/{commit}/{path}",
            "commit": commit,
            "license": src["license"],
            "sha256": sha256(out),
        })  # fmt: skip
    return entries


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def fetch_url(src: dict) -> list[dict]:
    suffix = Path(src["url"].split("?")[0]).suffix or ".bin"
    out = REFS / "url" / f"{src['name']}{suffix}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(download(src["url"]))
    return [{
        "file": str(out.relative_to(REFS)),
        "source": src["url"],
        "license": src.get("license", "unknown"),
        "sha256": sha256(out),
    }]  # fmt: skip


def fetch_arxiv(src: dict) -> list[dict]:
    """arXiv serves a paper's LaTeX source as a tarball; keep only the figure files."""
    aid = src["id"]
    dest = REFS / "arxiv" / aid
    if dest.exists():
        shutil.rmtree(dest)
    entries = []
    with tarfile.open(fileobj=io.BytesIO(download(f"https://arxiv.org/e-print/{aid}"))) as tar:
        for member in tar.getmembers():
            if not member.isfile() or Path(member.name).suffix.lower() not in FIGURE_EXT:
                continue
            out = dest / Path(member.name).name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(tar.extractfile(member).read())
            entries.append({
                "file": str(out.relative_to(REFS)),
                "source": f"https://arxiv.org/abs/{aid} ({member.name})",
                "license": src.get("license", "see the paper's arXiv licence"),
                "sha256": sha256(out),
            })  # fmt: skip
    return entries


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="ignore the file-name keyword filter")
    ap.add_argument("--only", nargs="*", help="names (or arXiv ids) to fetch; default: all")
    args = ap.parse_args()

    sources = tomllib.loads((HERE / "sources.toml").read_text())
    manifest_path = HERE / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    jobs = [
        *((s["name"], lambda s=s: fetch_repo(s, args.all)) for s in sources.get("repo", [])),
        *((s["name"], lambda s=s: fetch_url(s)) for s in sources.get("url", [])),
        *((s["id"], lambda s=s: fetch_arxiv(s)) for s in sources.get("arxiv", [])),
    ]
    for name, job in jobs:
        if args.only and name not in args.only:
            continue
        try:
            manifest[name] = job()
            print(f"{name}: {len(manifest[name])} files")
        except Exception as e:  # noqa: BLE001 - one bad source must not stop the rest
            print(f"{name}: FAILED - {e}")

    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"images -> {REFS}\nmanifest -> {manifest_path}")


if __name__ == "__main__":
    main()
