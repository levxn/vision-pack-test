#!/usr/bin/env python3
"""Shared helpers for the loader-audit suite (sdk-consumer imports them too).

- Which files in $ROCM_PATH belong to vision-pack: the dist tarball listing when
  VP_DIST_TARBALL is set, otherwise the ownership patterns below (the staging
  layout that build.yml/package.yml put into the tarball). The manifest has no
  file list, so it only drives the inventory checks.
- Shipped x86-64 ELF objects and their stable test names (SONAME-based, so a
  version bump does not rename the test).
- Result records through build_tools/results/emit.py.

CLI:
    vp_owned.py write <out.json>      enumerate owned entries and ELF objects
    vp_owned.py fatbin <elf>          print the gfx targets in .hip_fatbin
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import mmap
import os
import re
import struct
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROCM = os.environ.get("ROCM_PATH", "")
VP_OUT = os.environ.get("VP_OUT", "")
VP_WORK = os.environ.get("VP_WORK", os.path.join(VP_OUT, "work") if VP_OUT else "")
TIERS = ["quick", "standard", "comprehensive", "full"]

VISION_LIBS = ("mivisionx", "rocal", "roccv", "rocpydecode", "rocpyjpegdecode")
OWNED_DIRS = (
    "include/mivisionx", "include/rocal", "include/roccv",
    "lib/amd", "lib/cmake/roccv", "lib/pyRocJpegDecode", "lib/pyRocVideoDecode",
    "lib/rocm_sysdeps/lib/cmake/SndFile", "lib/rocm_sysdeps/lib/cmake/libjpeg-turbo",
    "share/mivisionx", "share/rocal", "share/roccv", "share/rocpydecode", "share/rocpyjpegdecode",
    "share/vision-pack",
)
OWNED_GLOBS = (
    "bin/runvx",
    "lib/libopenvx.so*", "lib/libvxu.so*", "lib/libvx_rpp.so*", "lib/librocal.so*", "lib/libroccv.so*",
    "lib/rocal_pybind*.so", "lib/rocpycv*.so", "lib/rocpycv.pyi", "lib/rocpydecode*.so", "lib/rocpyjpegdecode*.so",
    "lib/cmake/FindMIVisionX.cmake", "lib/cmake/Findrocal.cmake",
    "lib/rocm_sysdeps/lib/*-rocm-vision.so*",
)
# share/doc/<lib> and share/doc/<lib>-<variant> (e.g. -asan) for each vision library.
OWNED_DOC_RE = re.compile(r"^share/doc/(%s)(-[^/]+)?(/|$)" % "|".join(VISION_LIBS))

BASE_LIB_RE = re.compile(
    r"^(linux-vdso|ld-linux-x86-64|libc|libm|libdl|libpthread|librt|libstdc\+\+|libgcc_s|libmvec|libutil|libresolv)\.so")
CI_PARITY_SUBDIRS = ("lib", "lib/llvm/lib", "lib/rocm_sysdeps/lib")


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------

def _emit():
    sys.path.insert(0, os.path.join(os.environ["VP_REPO"], "build_tools", "results"))
    import emit  # noqa: PLC0415
    return emit


class Recorder:
    """Writes result records; keeps a per-status tally for the harness log."""

    def __init__(self):
        self.emit = _emit()
        self.path = os.environ["VP_RESULTS"]
        self.suite = os.environ["VP_SUITE"]
        self.counts: dict[str, int] = {}

    def __call__(self, test_id: str, status: str, message: str = "", *, log: str = "", duration: float = 0.0,
                 backend: str = "", repro: str = "") -> None:
        if log and VP_OUT and log.startswith(VP_OUT + "/"):
            log = log[len(VP_OUT) + 1:]
        self.emit.append_record(self.path, self.suite, test_id, status, message=message, log=log,
                                duration_s=duration, backend=backend, repro=repro)
        self.counts[status] = self.counts.get(status, 0) + 1
        print(f"[{status:7}] {test_id} {message[:200]}", flush=True)


def tier_ge(tier: str) -> bool:
    cur = os.environ.get("VP_TIER", "comprehensive")
    ci = TIERS.index(cur) if cur in TIERS else 2
    return ci >= TIERS.index(tier)


def work_dir(name: str) -> Path:
    p = Path(VP_WORK) / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_path(name: str) -> str:
    p = Path(VP_OUT) / "logs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


def customer_env(**extra) -> dict:
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    env.update(extra)
    return env


def parity_env(**extra) -> dict:
    env = customer_env(**extra)
    env["LD_LIBRARY_PATH"] = ":".join(f"{ROCM}/{d}" for d in CI_PARITY_SUBDIRS)
    return env


def crashed(rc: int) -> bool:
    """Timeout (124 from run()) or killed by a signal (negative returncode)."""
    return rc == 124 or rc < 0


def run(cmd, *, env=None, timeout=120, cwd=None, stdin=subprocess.DEVNULL) -> tuple[int, str, float]:
    """Run a command, merging stdout/stderr. rc 124 means timeout."""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, env=env, cwd=cwd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout)
        out = p.stdout.decode(errors="replace")
        rc = p.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") + f"\n### timeout after {timeout}s"
        rc = 124
    except FileNotFoundError as e:
        out, rc = str(e), 127
    return rc, out, time.time() - t0


# ---------------------------------------------------------------------------
# ownership
# ---------------------------------------------------------------------------

def _pattern_owned(rel: str) -> bool:
    if any(rel == d or rel.startswith(d + "/") for d in OWNED_DIRS):
        return True
    if OWNED_DOC_RE.match(rel):
        return True
    return any(fnmatch.fnmatchcase(rel, g) for g in OWNED_GLOBS)


def _kind(p: str) -> str:
    if os.path.islink(p):
        return "symlink"
    if os.path.isdir(p):
        return "dir"
    return "file" if os.path.isfile(p) else "other"


def owned_from_patterns(rocm: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for top in ("bin", "include", "lib", "share"):
        base = os.path.join(rocm, top)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            rel_root = os.path.relpath(root, rocm)
            # prune whole subtrees that can hold no owned entry (e.g. lib/llvm)
            keep = []
            for d in dirs:
                rel = f"{rel_root}/{d}"
                full = os.path.join(root, d)
                if _pattern_owned(rel):
                    out[rel] = _kind(full)
                    if not os.path.islink(full):
                        keep.append(d)
                elif any(o.startswith(rel + "/") for o in OWNED_DIRS) or rel in ("share/doc", "lib/rocm_sysdeps",
                                                                                   "lib/rocm_sysdeps/lib",
                                                                                   "lib/cmake"):
                    keep.append(d)
            dirs[:] = keep
            for f in files:
                rel = f"{rel_root}/{f}"
                if _pattern_owned(rel):
                    out[rel] = _kind(os.path.join(root, f))
    return out


def owned_from_tarball(tarball: str) -> dict[str, str]:
    out: dict[str, str] = {}
    with tarfile.open(tarball, "r:*") as t:
        for ti in t:
            rel = ti.name[2:] if ti.name.startswith("./") else ti.name
            rel = rel.rstrip("/")
            if rel in ("", "."):
                continue
            out[rel] = "symlink" if ti.issym() else "dir" if ti.isdir() else "file" if ti.isfile() else "other"
    return out


# ---------------------------------------------------------------------------
# ELF
# ---------------------------------------------------------------------------

def elf_machine(path: str) -> int | None:
    try:
        with open(path, "rb") as f:
            h = f.read(20)
    except OSError:
        return None
    if len(h) < 20 or h[:4] != b"\x7fELF":
        return None
    return struct.unpack_from("<H", h, 18)[0]


def dynamic(path: str) -> dict:
    rc, out, _ = run(["readelf", "-dW", path], timeout=60)
    info = {"needed": [], "soname": "", "runpath": None, "rpath": None, "flags": "", "flags_1": ""}
    for line in out.splitlines():
        m = re.search(r"\((\w+)\)\s+(.*)$", line)
        if not m:
            continue
        tag, val = m.groups()
        br = re.search(r"\[(.*)\]", val)
        if tag == "NEEDED" and br:
            info["needed"].append(br.group(1))
        elif tag == "SONAME" and br:
            info["soname"] = br.group(1)
        elif tag == "RUNPATH" and br:
            info["runpath"] = br.group(1)
        elif tag == "RPATH" and br:
            info["rpath"] = br.group(1)
        elif tag == "FLAGS":
            info["flags"] = val
        elif tag == "FLAGS_1":
            info["flags_1"] = val
    return info


def elf_kind(rel: str, dyn: dict) -> str:
    if rel.startswith("bin/"):
        return "exe"
    if ".cpython-" in os.path.basename(rel) or not dyn["soname"]:
        return "pyext" if ".cpython-" in rel else "exe"
    return "lib"


def test_name(rel: str, soname: str) -> str:
    return f"{os.path.dirname(rel)}/{soname}" if soname else rel


def sections(path: str) -> dict[str, tuple[int, int]]:
    """{name: (offset, size)} from the section header table."""
    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            if mm[:4] != b"\x7fELF" or mm[4] != 2:
                return {}
            e_shoff = struct.unpack_from("<Q", mm, 0x28)[0]
            e_shentsize, e_shnum, e_shstrndx = struct.unpack_from("<HHH", mm, 0x3A)
            hdrs = []
            for i in range(e_shnum):
                name, _typ, _flags, _addr, off, size = struct.unpack_from("<IIQQQQ", mm, e_shoff + i * e_shentsize)
                hdrs.append((name, off, size))
            stroff = hdrs[e_shstrndx][1]
            out = {}
            for name, off, size in hdrs:
                end = mm.find(b"\0", stroff + name)
                out[mm[stroff + name:end].decode(errors="replace")] = (off, size)
            return out
        finally:
            mm.close()


def fatbin_info(path: str) -> dict:
    """gfx targets bundled in .hip_fatbin, parsed in memory (no extraction)."""
    secs = sections(path)
    if ".hip_fatbin" not in secs:
        return {"arches": [], "section": False, "sha256": ""}
    off, size = secs[".hip_fatbin"]
    magic, cmagic = b"__CLANG_OFFLOAD_BUNDLE__", b"CCOB"
    arches: set[str] = set()
    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            data = mm[off:off + size]
        finally:
            mm.close()
    pos = 0
    while True:
        i = data.find(magic, pos)
        if i < 0:
            break
        p = i + len(magic)
        (n,) = struct.unpack_from("<Q", data, p)
        p += 8
        for _ in range(n):
            _e_off, e_size, id_len = struct.unpack_from("<QQQ", data, p)
            p += 24
            ident = data[p:p + id_len].decode(errors="replace")
            p += id_len
            m = re.search(r"gfx[0-9a-f]+", ident)
            if m and e_size > 0:
                arches.add(m.group(0))
        pos = i + len(magic)
    if data.count(cmagic):
        arches.update(m.group(0).decode() for m in re.finditer(rb"gfx[0-9a-f]{3,5}", data))
    return {"arches": sorted(arches), "section": True, "sha256": hashlib.sha256(data).hexdigest(), "bytes": size}


def owned_elfs(rocm: str, entries: dict[str, str]) -> list[dict]:
    out = []
    for rel, kind in sorted(entries.items()):
        if kind != "file":
            continue
        p = os.path.join(rocm, rel)
        if os.path.islink(p) or not os.path.isfile(p) or elf_machine(p) != 62:
            continue
        dyn = dynamic(p)
        out.append({"rel": rel, "path": p, "soname": dyn["soname"], "kind": elf_kind(rel, dyn),
                    "name": test_name(rel, dyn["soname"]), "dyn": dyn})
    return out


def load_owned() -> dict:
    with open(os.path.join(VP_WORK, "owned.json"), encoding="utf-8") as f:
        return json.load(f)


def load_manifest() -> dict:
    try:
        with open(os.environ.get("VP_MANIFEST", ""), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "fatbin":
        print(" ".join(fatbin_info(argv[1])["arches"]))
        return 0
    if len(argv) >= 2 and argv[0] == "write":
        tarball = os.environ.get("VP_DIST_TARBALL", "")
        if tarball and os.path.isfile(tarball):
            entries, source = owned_from_tarball(tarball), f"tarball:{os.path.basename(tarball)}"
        else:
            entries, source = owned_from_patterns(ROCM), "patterns"
        elfs = owned_elfs(ROCM, entries)
        Path(argv[1]).write_text(json.dumps({"source": source, "entries": entries, "elfs": elfs}, indent=1),
                                 encoding="utf-8")
        print(f"owned entries: {len(entries)} (source {source}); ELF objects: {len(elfs)}")
        for e in elfs:
            print(f"  {e['kind']:5} {e['name']}")
        return 0 if elfs else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
