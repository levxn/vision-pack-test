#!/usr/bin/env python3
"""Static checks on vision-pack release packages, shared by the packaging scripts.

Every subcommand appends result records to ``--results`` through
build_tools/results/emit.py (suite ``--suite``, default ``packaging``)::

    pkgcheck.py upstream-log --log F --rc N          # validate_packages.sh output -> deb::<pkg>
    pkgcheck.py deb    --debs DIR --work DIR          # extra DEB checks (licenses, N1/N2 refs,
                                                       # empty dirs, build paths -- issue #55)
    pkgcheck.py rpm    --rpms DIR [--debs DIR] --work DIR
    pkgcheck.py tarball --tarball F --root DIR [--debs DIR] [--release-json F] [--vp-src DIR]
    pkgcheck.py depends --pkg-dir DIR --format deb|rpm --index F --group G [--stubs-out F]

``depends`` checks the external dependencies of a package set against a
repository index (APT ``Packages`` or RPM ``primary.xml``) and needs no root,
so the install-smoke scripts use it both for planning and for their records.

Runs on Python 3.9 (Rocky Linux 9 system python) and newer.
"""
from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("VP_REPO", HERE.parent.parent))
sys.path.insert(0, str(REPO / "build_tools" / "results"))
import emit  # noqa: E402

# ---------------------------------------------------------------------------
# The vision-pack package model (mirrors vision-pack packaging/CMakeLists.txt
# and build_tools/validate_packages.sh).
# ---------------------------------------------------------------------------
METAS = {
    "amdrocm-vision": ["amdrocm-mivisionx", "amdrocm-rocal", "amdrocm-roccv", "amdrocm-pydecode"],
    "amdrocm-vision-sdk": ["amdrocm-vision", "amdrocm-mivisionx-devel", "amdrocm-rocal-devel",
                           "amdrocm-roccv-devel"],
    "amdrocm-vision-tests": ["amdrocm-vision-sdk", "amdrocm-mivisionx-test", "amdrocm-rocal-test",
                             "amdrocm-roccv-test", "amdrocm-pydecode-test"],
}
# Internal relations every package must declare (runtime <-> devel <-> test).
RELATIONS = {
    "amdrocm-mivisionx": [],
    "amdrocm-mivisionx-devel": ["amdrocm-mivisionx"],
    "amdrocm-mivisionx-test": ["amdrocm-mivisionx"],
    "amdrocm-rocal": ["amdrocm-mivisionx", "amdrocm-vision-sysdeps", "amdrocm-vision-pythonpath"],
    "amdrocm-rocal-devel": ["amdrocm-rocal", "amdrocm-mivisionx-devel"],
    "amdrocm-rocal-test": ["amdrocm-rocal"],
    "amdrocm-roccv": ["amdrocm-vision-pythonpath"],
    "amdrocm-roccv-devel": ["amdrocm-roccv"],
    "amdrocm-roccv-test": ["amdrocm-roccv"],
    "amdrocm-pydecode": ["amdrocm-vision-pythonpath"],
    "amdrocm-pydecode-test": ["amdrocm-pydecode"],
    "amdrocm-vision-sysdeps": [],
    "amdrocm-vision-pythonpath": [],
    **METAS,
}
EXPECTED_PACKAGES = sorted(RELATIONS)
# -test packages whose shipped tests are CMake projects and so need headers (N2).
TEST_NEEDS_DEVEL = {
    "amdrocm-mivisionx-test": "amdrocm-mivisionx-devel",
    "amdrocm-rocal-test": "amdrocm-rocal-devel",
    "amdrocm-roccv-test": "amdrocm-roccv-devel",
}
PTH_PATH = "/usr/lib/python3/dist-packages/amdrocm-vision.pth"
PTH_CONTENT = "/opt/rocm/lib"

# Third-party code each package redistributes (H4). "own" is the library's own license.
LICENSES_REQUIRED = {
    "amdrocm-mivisionx": ["own"],
    "amdrocm-rocal": ["own", "rapidjson", "pybind11", "dlpack"],
    "amdrocm-roccv": ["own", "pybind11", "dlpack"],
    "amdrocm-pydecode": ["own", "pybind11", "dlpack"],
    "amdrocm-vision-sysdeps": ["libjpeg-turbo", "libsndfile", "lmdb", "protobuf"],
}
LICENSE_TOKENS = {
    "libjpeg-turbo": r"libjpeg-turbo|turbojpeg|libjpeg",
    "libsndfile": r"sndfile",
    "lmdb": r"lmdb|openldap",
    "protobuf": r"protobuf",
    "rapidjson": r"rapidjson",
    "pybind11": r"pybind11",
    "dlpack": r"dlpack",
}
TARBALL_LICENSES = ["libjpeg-turbo", "libsndfile", "lmdb", "protobuf", "rapidjson", "pybind11", "dlpack"]
LICENSE_FILE_RE = re.compile(r"(?i)(licen[cs]e|copying|notice|copyright)[^/]*$")
STOCK_SONAME_RE = re.compile(r"^lib(jpeg|turbojpeg|sndfile|protobuf|protobuf-lite|lmdb)\.so")
OS_SONAME_RE = re.compile(r"^(libc|libm|libdl|libpthread|librt|libgcc_s|libstdc\+\+|ld-linux-x86-64)\.so")
ROCM_SONAME_RE = re.compile(r"^(libamdhip64|librpp|libomp|librocdecode|librocjpeg|libhipfile|libhsa-runtime64|"
                            r"libamd_comgr|librocm_sysdeps_[a-z0-9_]+)\.so")
BUILD_PATH_RE = re.compile(rb"/__w/|/home/runner/|/opt/rocm-nightly|/github/workspace")
# Files CPack puts in DEBs under a different doc directory than the staged tree.
TEXT_SUFFIXES = {".py", ".cmake", ".txt", ".sh", ".cpp", ".c", ".h", ".hpp", ".gdf", ".json", ".pc", ".pth",
                 ".md", ".in", ".cfg", ".yaml", ".yml", ".pyi"}


class Recorder:
    def __init__(self, results: str, suite: str, group: str, log: str = ""):
        self.results, self.suite, self.group, self.log = results, suite, group, log
        self.counts: dict[str, int] = defaultdict(int)

    def __call__(self, name: str, status: str, message: str = "", log: str = "") -> None:
        emit.append_record(self.results, self.suite, f"{self.group}::{name}", status,
                           message=message, log=log or self.log)
        self.counts[status] += 1
        print(f"  {status.upper():7s} {self.suite}::{self.group}::{name}" + (f"  -- {message[:160]}" if message
                                                                              and status != "pass" else ""))


class NullRecorder:
    def __call__(self, *_args, **_kw) -> None:
        return None


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def short_list(items, n: int = 12) -> str:
    items = list(items)
    more = f" (+{len(items) - n} more)" if len(items) > n else ""
    return ", ".join(str(i) for i in items[:n]) + more


# ---------------------------------------------------------------------------
# Version comparison (Debian policy 5.6.12 and rpmvercmp), no external tools.
# ---------------------------------------------------------------------------
def _deb_order(c: str) -> int:
    if c == "~":
        return -1
    if c.isdigit():
        return 0
    if c.isalpha():
        return ord(c)
    return ord(c) + 256


def _deb_cmp_part(a: str, b: str) -> int:
    ia = ib = 0
    while ia < len(a) or ib < len(b):
        first_diff = 0
        while (ia < len(a) and not a[ia].isdigit()) or (ib < len(b) and not b[ib].isdigit()):
            ac = _deb_order(a[ia]) if ia < len(a) else 0
            bc = _deb_order(b[ib]) if ib < len(b) else 0
            if ac != bc:
                return ac - bc
            ia += 1
            ib += 1
        while ia < len(a) and a[ia] == "0":
            ia += 1
        while ib < len(b) and b[ib] == "0":
            ib += 1
        while ia < len(a) and a[ia].isdigit() and ib < len(b) and b[ib].isdigit():
            if not first_diff:
                first_diff = ord(a[ia]) - ord(b[ib])
            ia += 1
            ib += 1
        if ia < len(a) and a[ia].isdigit():
            return 1
        if ib < len(b) and b[ib].isdigit():
            return -1
        if first_diff:
            return first_diff
    return 0


def deb_vercmp(a: str, b: str) -> int:
    def split(v: str) -> tuple[int, str, str]:
        epoch = 0
        if ":" in v:
            e, v = v.split(":", 1)
            epoch = int(e or 0)
        rev = "0"
        if "-" in v:
            v, rev = v.rsplit("-", 1)
        return epoch, v, rev

    ea, ua, ra = split(a)
    eb, ub, rb = split(b)
    if ea != eb:
        return ea - eb
    return _deb_cmp_part(ua, ub) or _deb_cmp_part(ra, rb)


def _rpm_segcmp(a: str, b: str) -> int:
    ia = ib = 0
    while ia < len(a) or ib < len(b):
        while ia < len(a) and not a[ia].isalnum() and a[ia] not in "~^":
            ia += 1
        while ib < len(b) and not b[ib].isalnum() and b[ib] not in "~^":
            ib += 1
        ca = a[ia] if ia < len(a) else ""
        cb = b[ib] if ib < len(b) else ""
        if ca == "~" or cb == "~":
            if ca != "~":
                return 1
            if cb != "~":
                return -1
            ia += 1
            ib += 1
            continue
        if ca == "^" or cb == "^":
            if not ca:
                return -1
            if not cb:
                return 1
            if ca != "^":
                return 1
            if cb != "^":
                return -1
            ia += 1
            ib += 1
            continue
        if not ca or not cb:
            break
        num = ca.isdigit()
        ja, jb = ia, ib
        pred = str.isdigit if num else str.isalpha
        while ja < len(a) and pred(a[ja]):
            ja += 1
        while jb < len(b) and pred(b[jb]):
            jb += 1
        sa, sb = a[ia:ja], b[ib:jb]
        if not sb:
            return 1 if num else -1
        if num:
            sa, sb = sa.lstrip("0"), sb.lstrip("0")
            if len(sa) != len(sb):
                return 1 if len(sa) > len(sb) else -1
        if sa != sb:
            return 1 if sa > sb else -1
        ia, ib = ja, jb
    ra, rb = a[ia:], b[ib:]
    if not ra and not rb:
        return 0
    return 1 if ra else -1


def rpm_vercmp(a: str, b: str) -> int:
    """Compare [epoch:]version[-release]; a missing release on either side is ignored."""
    def split(v: str) -> tuple[int, str, str | None]:
        epoch = 0
        if ":" in v:
            e, v = v.split(":", 1)
            epoch = int(e or 0)
        rel = None
        if "-" in v:
            v, rel = v.rsplit("-", 1)
        return epoch, v, rel

    ea, va, ra = split(a)
    eb, vb, rb = split(b)
    if ea != eb:
        return 1 if ea > eb else -1
    c = _rpm_segcmp(va, vb)
    if c or ra is None or rb is None:
        return c
    return _rpm_segcmp(ra, rb)


def satisfies(have: str, op: str, want: str, fmt: str) -> bool:
    c = (deb_vercmp if fmt == "deb" else rpm_vercmp)(have, want)
    return {"": True, ">=": c >= 0, "<=": c <= 0, ">>": c > 0, ">": c > 0, "<<": c < 0, "<": c < 0,
            "=": c == 0}.get(op, False)


# ---------------------------------------------------------------------------
# Package readers
# ---------------------------------------------------------------------------
class Entry:
    __slots__ = ("path", "kind", "mode", "size", "target", "sha256")

    def __init__(self, path: str, kind: str, mode: int, size: int = 0, target: str = "", sha256: str = ""):
        self.path, self.kind, self.mode, self.size, self.target, self.sha256 = path, kind, mode, size, target, sha256


class Pkg:
    def __init__(self, file: Path, fmt: str):
        self.file, self.fmt = file, fmt
        self.name = self.version = self.release = self.arch = ""
        self.fields: dict[str, str] = {}
        self.entries: list[Entry] = []
        self.texts: dict[str, bytes] = {}
        self.requires: list[tuple[str, str, str, str]] = []  # name, deptype, op, version
        self.provides: list[tuple[str, str, str]] = []
        self.prefixes: list[str] = []
        self.scripts: dict[str, tuple[str, str]] = {}

    @property
    def files(self) -> list[Entry]:
        return [e for e in self.entries if e.kind != "d"]

    def depends_names(self) -> list[str]:
        if self.fmt == "rpm":
            # Manual (explicit Requires:) entries, same filter as requires.relations --
            # excludes auto soname/rpmlib requires, which aren't package names.
            return [n for n, t, _, _ in self.requires if t == "manual" or (t == "" and not n.startswith("rpmlib("))]
        return [n for n, _, _ in parse_deb_depends(self.fields.get("Depends", ""))]


def parse_control(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    key = None
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and key:
            fields[key] += "\n" + line.strip()
        elif ":" in line:
            key, val = line.split(":", 1)
            key = key.strip()
            fields[key] = val.strip()
    return fields


def parse_deb_depends(value: str) -> list[tuple[str, str, str]]:
    """First alternative of each clause as (name, op, version)."""
    out = []
    for clause in filter(None, (c.strip() for c in value.split(","))):
        alt = clause.split("|")[0].strip()
        m = re.match(r"^([A-Za-z0-9.+_-]+)(?::\S+)?\s*(?:\(\s*([<>=]+)\s*([^)\s]+)\s*\))?", alt)
        if m:
            out.append((m.group(1), m.group(2) or "", m.group(3) or ""))
    return out


def read_deb(path: Path, hash_files: bool = False, want_text=None) -> Pkg:
    pkg = Pkg(path, "deb")
    r = run(["dpkg-deb", "-f", str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"dpkg-deb -f {path.name}: {r.stderr.strip()}")
    pkg.fields = parse_control(r.stdout)
    pkg.name = pkg.fields.get("Package", "")
    pkg.version = pkg.fields.get("Version", "")
    pkg.arch = pkg.fields.get("Architecture", "")
    proc = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(path)], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|*") as tf:
            for m in tf:
                p = "/" + m.name.lstrip("./") if m.name not in (".", "./") else "/"
                if p == "/":
                    continue
                p = p.rstrip("/")
                kind = "d" if m.isdir() else "l" if m.issym() else "f" if m.isfile() else "h" if m.islnk() else "o"
                e = Entry(p, kind, m.mode, m.size, m.linkname)
                if m.isfile() and (hash_files or (want_text and want_text(p, m.size))):
                    data = tf.extractfile(m).read()
                    if hash_files:
                        e.sha256 = hashlib.sha256(data).hexdigest()
                    if want_text and want_text(p, m.size):
                        pkg.texts[p] = data
                pkg.entries.append(e)
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"dpkg-deb --fsys-tarfile {path.name} failed ({proc.returncode})")
    return pkg


RPM_SCRIPT_TAGS = ["PRETRANS", "PREIN", "POSTIN", "PREUN", "POSTUN", "POSTTRANS"]


def read_rpm(path: Path) -> Pkg:
    pkg = Pkg(path, "rpm")

    def q(fmt: str) -> str:
        r = run(["rpm", "-qp", "--nosignature", "--nodigest", "--qf", fmt, str(path)])
        if r.returncode != 0:
            raise RuntimeError(f"rpm -qp {path.name}: {r.stderr.strip()}")
        return r.stdout

    hdr = q("%{NAME}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\t%{LICENSE}\t%{FILEDIGESTALGO}\n").split("\t")
    pkg.name, pkg.version, pkg.release, pkg.arch = hdr[0], hdr[1], hdr[2], hdr[3]
    pkg.fields = {"License": hdr[4], "DigestAlgo": hdr[5].strip()}
    pkg.prefixes = [p for p in q("[%{PREFIXES}\n]").splitlines() if p and p != "(none)"]
    for line in q("[%{FILENAMES}\t%{FILEMODES}\t%{FILESIZES}\t%{FILELINKTOS}\t%{FILEDIGESTS}\n]").splitlines():
        parts = line.split("\t")
        if len(parts) < 5 or not parts[0]:
            continue
        mode = int(parts[1])
        kind = "d" if stat.S_ISDIR(mode) else "l" if stat.S_ISLNK(mode) else "f" if stat.S_ISREG(mode) else "o"
        pkg.entries.append(Entry(parts[0], kind, stat.S_IMODE(mode), int(parts[2] or 0), parts[3],
                                 parts[4] if pkg.fields["DigestAlgo"] == "8" else ""))
    for line in q("[%{REQUIRENAME}\t%{REQUIREFLAGS:deptype}\t%{REQUIREFLAGS:depflags}\t%{REQUIREVERSION}\n]"
                  ).splitlines():
        n, t, op, v = (line.split("\t") + ["", "", ""])[:4]
        pkg.requires.append((n, t, op.strip(), v))
    for line in q("[%{PROVIDENAME}\t%{PROVIDEFLAGS:depflags}\t%{PROVIDEVERSION}\n]").splitlines():
        n, op, v = (line.split("\t") + ["", ""])[:3]
        pkg.provides.append((n, op.strip(), v))
    for tag in RPM_SCRIPT_TAGS:
        body = q(f"%{{{tag}}}")
        prog = q(f"%{{{tag}PROG}}")
        if body.strip() and body.strip() != "(none)":
            pkg.scripts[tag] = (prog.strip(), body)
    trig = q("[%{TRIGGERNAME}\n]").strip()
    if trig and trig != "(none)":
        pkg.scripts["TRIGGERS"] = ("", trig)
    return pkg


def load_dir(d: Path, fmt: str, **kw) -> dict[str, Pkg]:
    pkgs: dict[str, Pkg] = {}
    for f in sorted(d.glob(f"*.{fmt}")):
        p = read_deb(f, **kw) if fmt == "deb" else read_rpm(f)
        pkgs[p.name] = p
    return pkgs


def is_meta(name: str) -> bool:
    return name in METAS


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------
def license_findings(paths: list[str], needs: list[str]) -> dict[str, list[str]]:
    lic = [p for p in paths if LICENSE_FILE_RE.search(p)]
    found: dict[str, list[str]] = {}
    for comp in needs:
        if comp == "own":
            hits = [p for p in lic if "/share/doc/" in p and "third" not in p.lower()
                    and not any(re.search(t, p, re.I) for t in LICENSE_TOKENS.values())]
        else:
            hits = [p for p in lic if re.search(LICENSE_TOKENS[comp], p, re.I)]
        found[comp] = hits
    return found


def record_licenses(rec: Recorder, prefix: str, paths: list[str], needs: list[str]) -> None:
    for comp, hits in license_findings(paths, needs).items():
        if hits:
            rec(f"{prefix}license.{comp}", "pass", short_list(hits, 3))
        else:
            what = "the package's own license" if comp == "own" else f"the {comp} license"
            rec(f"{prefix}license.{comp}", "fail", f"no license text for {what} in the payload (H4)")


SAMPLE_REF_RES = [
    (re.compile(r"/share/([A-Za-z0-9_+-]+)/samples/([A-Za-z0-9_./+-]+)"), "abs"),
    (re.compile(r"parents\[(\d)\]\s*/\s*[\"'](samples/[A-Za-z0-9_./+-]+)[\"']"), "parents"),
    (re.compile(r"\.\./samples/([A-Za-z0-9_./+-]+)"), "dotdot"),
]


def sample_refs(pkg: Pkg, prefix: str = "/opt/rocm") -> dict[str, set[str]]:
    """Map referenced path (absolute) -> set of referencing files."""
    refs: dict[str, set[str]] = defaultdict(set)
    for path, data in pkg.texts.items():
        text = data.decode("utf-8", "replace")
        for rx, kind in SAMPLE_REF_RES:
            for m in rx.finditer(text):
                if kind == "abs":
                    target = f"{prefix}/share/{m.group(1)}/samples/{m.group(2)}"
                elif kind == "parents":
                    base = PurePosixPath(path).parents[int(m.group(1))]
                    target = str(base / m.group(2))
                else:
                    target = str(PurePosixPath(path).parent.parent / "samples" / m.group(1))
                target = target.rstrip(".,;:)")
                if "*" in target or "{" in target or target.endswith("/"):
                    continue
                refs[os.path.normpath(target)].add(path)
    return refs


def closure(pkgs: dict[str, Pkg], root: str) -> set[str]:
    seen, todo = set(), [root]
    while todo:
        n = todo.pop()
        if n in seen or n not in pkgs:
            continue
        seen.add(n)
        todo.extend(pkgs[n].depends_names())
    return seen


# ---------------------------------------------------------------------------
# upstream-log: parse build_tools/validate_packages.sh output
# ---------------------------------------------------------------------------
def cmd_upstream_log(a) -> int:
    rec = Recorder(a.results, a.suite, "deb", a.log_rel)
    text = Path(a.log).read_text(encoding="utf-8", errors="replace")
    blocks: dict[str, list[str]] = {}
    verdict: dict[str, str] = {}
    cur = None
    cross: list[str] = []
    summary: list[str] = []
    in_summary = False
    for line in text.splitlines():
        m = re.match(r"^### (\S+)\s+\((.+)\)$", line)
        if m:
            cur = m.group(1)
            blocks[cur] = []
            continue
        if line.startswith("### cross-package checks"):
            cur = "__cross__"
            continue
        if line.startswith("Package validation summary"):
            in_summary, cur = True, None
            continue
        if in_summary:
            summary.append(line)
            continue
        m = re.match(r"^\s+=> (\S+): (PASS|FAIL)$", line)
        if m:
            verdict[m.group(1)] = m.group(2)
            continue
        if cur == "__cross__":
            cross.append(line.strip())
        elif cur and "ERROR" in line:
            blocks[cur].append(line.strip())
    n_debs = len(list(Path(a.debs).glob("*.deb"))) if a.debs else len(blocks)
    for pkg in sorted(blocks):
        v = verdict.get(pkg)
        if v == "PASS":
            rec(pkg, "pass")
        elif v == "FAIL":
            rec(pkg, "fail", "; ".join(blocks[pkg]) or "upstream validator reported FAIL")
        else:
            rec(pkg, "error", "no verdict in validator output: " + "; ".join(blocks[pkg])[:500])
    cross_err = [c for c in cross if "ERROR" in c]
    if cross or cross_err:
        rec("cross-package", "fail" if cross_err else "pass", "; ".join(cross_err or cross))
    else:
        rec("cross-package", "error", "validator printed no cross-package section")
    table = "\n".join(summary).strip("\n")
    if a.rc == 0 and len(blocks) == n_debs and "All packages passed." in table:
        rec("summary", "pass", table)
    elif not table:
        rec("summary", "error", f"validator exited {a.rc} without a summary (see log)")
    else:
        extra = f" (parsed {len(blocks)} packages, {n_debs} DEB files)" if len(blocks) != n_debs else ""
        rec("summary", "fail", f"validator exited {a.rc}{extra}\n{table}")
    if a.summary_md:
        Path(a.summary_md).write_text(table + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# deb: extra static checks
# ---------------------------------------------------------------------------
def want_text(path: str, size: int) -> bool:
    return size < 2_000_000 and ("/test" in path or "/tests/" in path) and (
        PurePosixPath(path).suffix in TEXT_SUFFIXES or path.endswith("CMakeLists.txt"))


def cmd_deb(a) -> int:
    rec = Recorder(a.results, a.suite, "deb")
    pkgs = load_dir(Path(a.debs), "deb", want_text=want_text)
    names = set(pkgs)
    missing = sorted(set(EXPECTED_PACKAGES) - names)
    extra = sorted(names - set(EXPECTED_PACKAGES))
    n_files = len(list(Path(a.debs).glob("*.deb")))
    msg = f"{n_files} DEB files, {len(names)} packages"
    if missing or extra or n_files != len(EXPECTED_PACKAGES):
        rec("set::packages", "fail", f"{msg}; missing: {short_list(missing)}; unexpected: {short_list(extra)}")
    else:
        rec("set::packages", "pass", msg)
    versions = {p.version.split("-")[0] for p in pkgs.values()}
    rec("set::version", "pass" if len(versions) == 1 else "fail", "upstream versions: " + short_list(sorted(versions)))
    all_paths: set[str] = set()
    for p in pkgs.values():
        all_paths.update(e.path for e in p.files)
    # empty directories and build-machine paths (issue #55: amdrocm-roccv shipped
    # an empty lib/amd/rocal/plugin/, so `import amd.rocal.plugin` wrongly
    # succeeded; confirmed on DEBs specifically, so this must not be RPM-only
    # the way it used to be -- see L-build-paths/N8 for the RPM/tarball side).
    for name in sorted(pkgs):
        p = pkgs[name]
        g = f"{name}::"
        ed = empty_dirs(p.entries)
        rec(g + "payload.empty-dirs", "fail" if ed else "pass",
            ("owns directories with no payload of its own (CPack FILES_MATCHING copies the whole tree): "
             + short_list(ed)) if ed else "")
        if not p.files or is_meta(name):
            continue
        dest = Path(a.work) / name
        rc, err = extract_deb(p.file, dest)
        if rc != 0:
            rec(g + "payload.build-paths", "error", f"dpkg-deb -x failed: {err[:300]}")
            continue
        hits = []
        for e in p.files:
            fp = dest / e.path.lstrip("/")
            if e.kind != "f" or not fp.is_file():
                continue
            if is_elf(fp):
                dyn = elf_dynamic(fp)
                for rp in dyn.get("RUNPATH", []) + dyn.get("RPATH", []):
                    if bad_runpath_tokens(rp):
                        hits.append(f"{e.path} RUNPATH [{rp}]")
            elif e.size < 4_000_000 and file_has(fp, BUILD_PATH_RE):
                hits.append(e.path)
        rec(g + "payload.build-paths", "fail" if hits else "pass",
            ("build-machine paths in RUNPATHs or text files: " + short_list(hits, 6)) if hits else "")
    for name, needs in LICENSES_REQUIRED.items():
        if name in pkgs:
            record_licenses(rec, f"{name}::", [e.path for e in pkgs[name].files], needs)
    for test, devel in TEST_NEEDS_DEVEL.items():
        if test not in pkgs:
            rec(f"{test}::depends.devel", "blocked", f"{test} not in the package set")
            continue
        deps = pkgs[test].depends_names()
        if devel in deps:
            rec(f"{test}::depends.devel", "pass", f"Depends: {pkgs[test].fields.get('Depends', '')}")
        else:
            rec(f"{test}::depends.devel", "fail",
                f"the shipped tests are CMake projects that need {devel} headers, but Depends is only "
                f"'{pkgs[test].fields.get('Depends', '')}' (N2)")
    for test in sorted(n for n in pkgs if n.endswith("-test")):
        refs = sample_refs(pkgs[test])
        cl = closure(pkgs, test)
        cl_paths: set[str] = set()
        for n in cl:
            cl_paths.update(e.path for e in pkgs[n].files)
        not_cl = {t: f for t, f in refs.items() if t not in cl_paths}
        nowhere = {t: f for t, f in refs.items() if t not in all_paths}
        if not refs:
            rec(f"{test}::refs.closure", "pass", "no samples/ references in the shipped tests")
            rec(f"{test}::refs.any-package", "pass", "no samples/ references in the shipped tests")
            continue

        def describe(d: dict[str, set[str]]) -> str:
            return "; ".join(f"{t} (used by {short_list(sorted(f), 2)})" for t, f in sorted(d.items()))

        if not_cl:
            owners = defaultdict(list)
            for t in not_cl:
                for n, p in pkgs.items():
                    if any(e.path == t for e in p.files):
                        owners[t].append(n)
            where = "; ".join(f"{t} -> {','.join(o)}" for t, o in owners.items())
            rec(f"{test}::refs.closure", "fail",
                f"files the tests read are outside {test} and its declared Depends ({short_list(sorted(cl))}): "
                f"{describe(not_cl)}" + (f"; shipped by: {where}" if where else ""))
        else:
            rec(f"{test}::refs.closure", "pass", f"{len(refs)} referenced file(s) inside the Depends closure")
        if nowhere:
            rec(f"{test}::refs.any-package", "fail", f"referenced files ship in no package: {describe(nowhere)}")
        else:
            rec(f"{test}::refs.any-package", "pass", f"{len(refs)} referenced file(s) all shipped")
    counts = ", ".join(f"{n}={len(p.files)}" for n, p in sorted(pkgs.items()))
    print(f"file counts (non-directory entries): {counts}")
    return 0


# ---------------------------------------------------------------------------
# ELF helpers
# ---------------------------------------------------------------------------
def is_elf(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def elf_dynamic(p: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    r = run(["readelf", "-d", "-W", str(p)])
    for line in r.stdout.splitlines():
        m = re.search(r"\((NEEDED|SONAME|RUNPATH|RPATH)\)\s+[^\[]*\[(.*)\]", line)
        if m:
            out[m.group(1)].append(m.group(2))
    return out


def elf_has_build_id(p: Path) -> bool:
    return "Build ID" in run(["readelf", "-n", "-W", str(p)]).stdout


def bad_runpath_tokens(rp: str) -> list[str]:
    return [t or "<empty>" for t in rp.split(":") if not t.startswith("$ORIGIN")]


def file_has(p: Path, rx: re.Pattern) -> bool:
    try:
        with open(p, "rb") as f:
            tail = b""
            while True:
                chunk = f.read(1 << 22)
                if not chunk:
                    return False
                if rx.search(tail + chunk):
                    return True
                tail = chunk[-64:]
    except OSError:
        return False


def alias_names(entries: dict[str, Entry]) -> dict[str, str]:
    """real path -> shortest symlink name in the same directory pointing to it (stable test IDs)."""
    best: dict[str, str] = {}
    for path, e in entries.items():
        if e.kind != "l":
            continue
        real = resolve_link(entries, path)
        if real and (real not in best or len(path) < len(best[real])):
            best[real] = path
    return best


def resolve_link(entries: dict[str, Entry], path: str, limit: int = 40) -> str | None:
    cur = path
    for _ in range(limit):
        e = entries.get(cur)
        if e is None:
            return None
        if e.kind != "l":
            return cur
        if e.target.startswith("/"):
            return None
        cur = os.path.normpath(str(PurePosixPath(cur).parent / e.target))
        if cur.startswith("..") or cur.startswith("/"):
            return None
    return None


def extract_deb(f: Path, dest: Path) -> tuple[int, str]:
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["dpkg-deb", "-x", str(f), str(dest)], capture_output=True, text=True)
    return r.returncode, r.stderr.strip()


# ---------------------------------------------------------------------------
# rpm
# ---------------------------------------------------------------------------
def extract_rpm(f: Path, dest: Path) -> tuple[int, str]:
    dest.mkdir(parents=True, exist_ok=True)
    p1 = subprocess.Popen(["rpm2cpio", str(f)], stdout=subprocess.PIPE)
    p2 = subprocess.run(["cpio", "-idm", "--quiet", "--no-absolute-filenames"], stdin=p1.stdout, cwd=dest,
                        capture_output=True, text=True)
    if p1.stdout:
        p1.stdout.close()
    p1.wait()
    return p1.returncode or p2.returncode, p2.stderr.strip()


def cpio_count(f: Path) -> int:
    p1 = subprocess.Popen(["rpm2cpio", str(f)], stdout=subprocess.PIPE)
    p2 = subprocess.run(["cpio", "-it", "--quiet"], stdin=p1.stdout, capture_output=True, text=True)
    if p1.stdout:
        p1.stdout.close()
    p1.wait()
    return len([x for x in p2.stdout.splitlines() if x.strip()]) if p1.returncode == 0 and p2.returncode == 0 else -1


def empty_dirs(entries: list[Entry]) -> list[str]:
    files = [e.path for e in entries if e.kind != "d"]
    out = []
    for d in (e.path for e in entries if e.kind == "d"):
        pre = d.rstrip("/") + "/"
        if not any(f.startswith(pre) for f in files):
            out.append(d)
    # Report only the deepest empty directories.
    return sorted(d for d in out if not any(o != d and o.startswith(d + "/") for o in out))


def cmd_rpm(a) -> int:
    rec = Recorder(a.results, a.suite, "rpm")
    rdir, work = Path(a.rpms), Path(a.work)
    try:
        pkgs = load_dir(rdir, "rpm")
    except (RuntimeError, OSError) as e:
        rec("set::read", "error", str(e))
        return 0
    debs: dict[str, Pkg] = {}
    if a.debs and Path(a.debs).is_dir():
        try:
            debs = load_dir(Path(a.debs), "deb")
        except (RuntimeError, OSError) as e:
            print(f"warning: cannot read DEBs for comparison: {e}", file=sys.stderr)
    names = set(pkgs)
    missing, extra = sorted(set(EXPECTED_PACKAGES) - names), sorted(names - set(EXPECTED_PACKAGES))
    n_files = len(list(rdir.glob("*.rpm")))
    msg = f"{n_files} RPM files, {len(names)} packages"
    rec("set::packages", "fail" if (missing or extra or n_files != len(EXPECTED_PACKAGES)) else "pass",
        msg + (f"; missing: {short_list(missing)}; unexpected: {short_list(extra)}" if missing or extra else ""))
    vers = {p.version for p in pkgs.values()}
    rels = {p.release for p in pkgs.values()}
    rec("set::version", "pass" if len(vers) == 1 and len(rels) == 1 else "fail",
        f"versions {short_list(sorted(vers))}; releases {short_list(sorted(rels))}")
    set_provides: set[str] = set()
    all_paths: set[str] = set()
    for p in pkgs.values():
        set_provides.update(n for n, _, _ in p.provides)
        all_paths.update(e.path for e in p.files)
    counts = {}
    for name in sorted(pkgs):
        p = pkgs[name]
        g = f"{name}::"
        counts[name] = len(p.files)
        # header
        problems = []
        if name not in RELATIONS:
            problems.append("unexpected package name")
        if not re.match(r"^\d", p.version):
            problems.append(f"version {p.version!r} does not start with a digit")
        if p.arch not in ("x86_64", "noarch"):
            problems.append(f"arch {p.arch}")
        if not p.fields.get("License") or p.fields["License"] == "(none)":
            problems.append("no License tag")
        if (name, "=", f"{p.version}-{p.release}") not in p.provides:
            problems.append("does not provide its own name = V-R")
        if name in debs:
            dv = debs[name].version
            if not dv.startswith(p.version):
                problems.append(f"version {p.version}-{p.release} differs from DEB {dv}")
        rec(g + "header", "fail" if problems else "pass",
            "; ".join(problems) or f"{p.version}-{p.release} {p.arch} License={p.fields.get('License')}")
        # payload prefix
        files = p.files
        if is_meta(name):
            stray = [e.path for e in files if not e.path.startswith("/usr/share/doc/")]
        else:
            stray = [e.path for e in files if not e.path.startswith("/opt/rocm/")
                     and not (name == "amdrocm-vision-pythonpath" and e.path == PTH_PATH)]
        if not files:
            rec(g + "payload.prefix", "fail", "package ships no files")
        else:
            rec(g + "payload.prefix", "fail" if stray else "pass",
                ("paths outside the expected prefix: " + short_list(stray)) if stray
                else f"{len(files)} files under {'/usr/share/doc' if is_meta(name) else '/opt/rocm'}")
        if p.prefixes:
            outside = [e.path for e in p.entries
                       if not any(e.path == x or e.path.startswith(x.rstrip('/') + '/') for x in p.prefixes)]
            rec(g + "payload.relocatable", "fail" if outside else "pass",
                (f"Prefixes: {' '.join(p.prefixes)} but these paths are outside it, so rpm --prefix/--relocate "
                 f"fails: {short_list(outside)}") if outside else f"all paths under Prefixes {' '.join(p.prefixes)}")
        # cpio payload integrity
        nc = cpio_count(p.file)
        if nc < 0:
            rec(g + "payload.cpio", "error", "rpm2cpio | cpio -t failed")
        elif nc != len(p.entries):
            rec(g + "payload.cpio", "fail", f"cpio archive has {nc} entries, header lists {len(p.entries)}")
        else:
            rec(g + "payload.cpio", "pass", f"{nc} entries")
        # empty directories owned without content
        ed = empty_dirs(p.entries)
        rec(g + "payload.empty-dirs", "fail" if ed else "pass",
            ("owns directories with no payload of its own (CPack FILES_MATCHING copies the whole tree): "
             + short_list(ed)) if ed else "")
        # matches DEB
        if name in debs and not is_meta(name):
            rp = {(e.path, e.kind) for e in files}
            dp = {(e.path, e.kind) for e in debs[name].files}
            only_r, only_d = sorted(x[0] for x in rp - dp), sorted(x[0] for x in dp - rp)
            modes = sorted(e.path for e in files
                           for d in debs[name].files if d.path == e.path and d.kind == e.kind == "f"
                           and (d.mode & 0o777) != (e.mode & 0o777))
            detail = f"{len(files)} files (DEB {len(debs[name].files)})"
            if only_r or only_d:
                rec(g + "payload.matches-deb", "fail",
                    f"{detail}; only in RPM: {short_list(only_r)}; only in DEB: {short_list(only_d)}")
            else:
                rec(g + "payload.matches-deb", "pass",
                    detail + (f"; mode differs: {short_list(modes)}" if modes else ""))
        elif is_meta(name) and name in debs:
            rec(g + "payload.matches-deb", "pass",
                f"meta: RPM {len(files)} doc file(s), DEB {len(debs[name].files)} (equivs docs)")
        elif not debs:
            rec(g + "payload.matches-deb", "blocked", "no DEBs given (--debs)")
        else:
            rec(g + "payload.matches-deb", "fail", "no DEB with the same package name")
        # .so modes: RPM convention (rpmlint shared-library-not-executable) is 0755
        so644 = [e.path for e in files if e.kind == "f" and re.search(r"\.so(\.\d+)*$", e.path)
                 and not e.mode & 0o111]
        rec(g + "so-mode", "fail" if so644 else "pass",
            ("shared libraries without the exec bit (rpmlint shared-library-not-executable; RPM's debuginfo and "
             "strip passes skip them): " + short_list(so644)) if so644 else "")
        # requires: relations
        man = [(n, op, v) for n, t, op, v in p.requires if t == "manual" or (t == "" and not n.startswith("rpmlib("))]
        man_names = {n for n, _, _ in man}
        want = RELATIONS.get(name, [])
        miss = [w for w in want if w not in man_names]
        badver = [f"{n} {op} {v}" for n, op, v in man if n in want and not (op == ">=" and v == p.version)]
        rec(g + "requires.relations", "fail" if miss or badver else "pass",
            (f"missing: {short_list(miss)}" if miss else "") + (f"; unexpected constraint: {short_list(badver)}"
                                                                if badver else "")
            or ("requires " + short_list(want) if want else "no internal requirements expected"))
        # requires mirror DEB Depends
        if name in debs:
            dd = {(n, op.replace(">>", ">").replace("<<", "<"), v)
                  for n, op, v in parse_deb_depends(debs[name].fields.get("Depends", ""))}
            rr = {(n, op, v) for n, op, v in man if n not in ("python3",) or name != "amdrocm-vision-pythonpath"}
            dnames, rnames = {x[0] for x in dd}, {x[0] for x in rr}
            diffs = []
            if dnames - rnames:
                diffs.append("only in DEB Depends: " + short_list(sorted(dnames - rnames)))
            if rnames - dnames:
                diffs.append("only in RPM Requires: " + short_list(sorted(rnames - dnames)))
            dv, rv = {x[0]: x[1:] for x in dd}, {x[0]: x[1:] for x in rr}
            for n in sorted(dnames & rnames):
                (dop, dver), (rop, rver) = dv[n], rv[n]
                if dop != rop or dver.split("-")[0] != rver.split("-")[0]:
                    diffs.append(f"{n}: DEB {dop} {dver} vs RPM {rop} {rver}")
            rec(g + "requires.mirror-deb", "fail" if diffs else "pass",
                "; ".join(diffs) or f"{len(rr)} requirement(s) mirror the DEB Depends")
        # requires closure: every auto soname requirement must be satisfiable
        unsat = []
        for n, _t, _op, _v in p.requires:
            if n.startswith("rpmlib(") or n.startswith("/") or ".so" not in n:
                continue
            base = n.split("(")[0]
            if n in set_provides:
                continue
            if "-rocm-vision" not in base and (OS_SONAME_RE.match(base) or ROCM_SONAME_RE.match(base)):
                continue
            unsat.append(n)
        rec(g + "requires.closure", "fail" if unsat else "pass",
            ("automatic requirements no package provides (dnf: 'nothing provides ...'): " + short_list(unsat, 8))
            if unsat else "")
        # provides isolation
        stock = [n for n, _, _ in p.provides if STOCK_SONAME_RE.match(n)]
        rec(g + "provides.isolation", "fail" if stock else "pass",
            ("provides stock-named capabilities (the bundled libraries' version definitions still carry the "
             "upstream SONAME, M1): " + short_list(stock)) if stock else "")
        # scriptlets
        issues, notes = [], []
        for tag, (prog, body) in p.scripts.items():
            notes.append(f"{tag}({prog or 'trigger'})")
            if prog and prog not in ("/bin/sh", "/bin/bash", "<lua>"):
                issues.append(f"{tag} uses interpreter {prog}")
            if BUILD_PATH_RE.search(body.encode()):
                issues.append(f"{tag} references a build-machine path")
            if re.search(r"\brm\s+-[a-z]*r[a-z]*f?\s+/(\s|$)|\bcurl\b|\bwget\b", body):
                issues.append(f"{tag} runs a destructive or network command")
        post = p.scripts.get("POSTIN", ("", ""))[1]
        undo = p.scripts.get("PREUN", ("", ""))[1] + p.scripts.get("POSTUN", ("", ""))[1]
        if re.search(r"write_text\(|>\s*\S*\.pth|\btee\b", post) and not re.search(r"unlink|\brm\b|remove", undo):
            issues.append("%post writes a file that is not in %files and no %preun/%postun removes it "
                          "(left behind after rpm -e)")
        rec(g + "scriptlets", "fail" if issues else "pass",
            "; ".join(issues) or (("scriptlets: " + ", ".join(notes)) if notes else "no scriptlets"))
        # payload scan (extract once)
        if files and not is_meta(name):
            dest = work / name
            rc, err = extract_rpm(p.file, dest)
            if rc != 0:
                rec(g + "payload.build-paths", "error", f"rpm2cpio|cpio failed: {err[:300]}")
            else:
                hits = []
                for e in files:
                    fp = dest / e.path.lstrip("/")
                    if e.kind != "f" or not fp.is_file():
                        continue
                    if is_elf(fp):
                        dyn = elf_dynamic(fp)
                        for rp in dyn.get("RUNPATH", []) + dyn.get("RPATH", []):
                            bad = bad_runpath_tokens(rp)
                            if bad:
                                hits.append(f"{e.path} RUNPATH [{rp}]")
                    elif e.size < 4_000_000 and file_has(fp, BUILD_PATH_RE):
                        hits.append(e.path)
                rec(g + "payload.build-paths", "fail" if hits else "pass",
                    ("build-machine paths in RUNPATHs or text files: " + short_list(hits, 6)) if hits else "")
                if name == "amdrocm-vision-pythonpath":
                    pth = dest / PTH_PATH.lstrip("/")
                    content = pth.read_text(errors="replace").strip() if pth.is_file() else None
                    rec(g + "pth.content", "pass" if content == PTH_CONTENT else "fail",
                        f"{PTH_PATH}: {content!r}" if content is not None else f"{PTH_PATH} not in payload")
                # -test packages: every samples/ path their shipped tests
                # reference must live inside the package's own Depends
                # closure (N1/N2 on the DEB side; RPMs share the install
                # rules, so the same defect class can occur here too).
                if name.endswith("-test"):
                    for e in files:
                        fp = dest / e.path.lstrip("/")
                        if e.kind == "f" and want_text(e.path, e.size) and fp.is_file():
                            p.texts[e.path] = fp.read_bytes()
                    refs = sample_refs(p)
                    if not refs:
                        rec(g + "refs.closure", "pass", "no samples/ references in the shipped tests")
                        rec(g + "refs.any-package", "pass", "no samples/ references in the shipped tests")
                    else:
                        cl = closure(pkgs, name)
                        cl_paths: set[str] = set()
                        for n in cl:
                            cl_paths.update(e2.path for e2 in pkgs[n].files)
                        not_cl = {t: f for t, f in refs.items() if t not in cl_paths}
                        nowhere = {t: f for t, f in refs.items() if t not in all_paths}
                        describe = lambda d: "; ".join(  # noqa: E731
                            f"{t} (used by {short_list(sorted(f), 2)})" for t, f in sorted(d.items()))
                        if not_cl:
                            owners = defaultdict(list)
                            for t in not_cl:
                                for n2, p2 in pkgs.items():
                                    if any(e2.path == t for e2 in p2.files):
                                        owners[t].append(n2)
                            where = "; ".join(f"{t} -> {','.join(o)}" for t, o in owners.items())
                            rec(g + "refs.closure", "fail",
                                f"files the tests read are outside {name} and its declared Requires "
                                f"({short_list(sorted(cl))}): {describe(not_cl)}" + (f"; shipped by: {where}"
                                                                                     if where else ""))
                        else:
                            rec(g + "refs.closure", "pass", f"{len(refs)} referenced file(s) inside the Requires closure")
                        if nowhere:
                            rec(g + "refs.any-package", "fail", f"referenced files ship in no package: {describe(nowhere)}")
                        else:
                            rec(g + "refs.any-package", "pass", f"{len(refs)} referenced file(s) all shipped")
            if name == "amdrocm-vision-pythonpath":
                rec(g + "pth.site-dir", "fail",
                    f"ships the Debian-only {PTH_PATH} (no EL interpreter reads it) and relies on an untracked "
                    "%post copy into python3's site-packages; on EL9 python3 is 3.9, while the vision modules are "
                    "cp312-only, so python3.12 never gets the path")
        if name in LICENSES_REQUIRED:
            record_licenses(rec, g, [e.path for e in files], LICENSES_REQUIRED[name])
    print("file counts (non-directory entries): " + ", ".join(f"{n}={c}" for n, c in sorted(counts.items())))
    return 0


# ---------------------------------------------------------------------------
# tarball
# ---------------------------------------------------------------------------
def sysdeps_patterns(vp_src: Path | None) -> list[str]:
    default = ["libturbojpeg-rocm-vision.so*", "libjpeg-rocm-vision.so*", "libprotobuf-rocm-vision.so*",
               "libprotobuf-lite-rocm-vision.so*", "liblmdb-rocm-vision.so*", "libsndfile-rocm-vision.so*"]
    if not vp_src:
        return default
    cm = vp_src / "packaging" / "CMakeLists.txt"
    if not cm.is_file():
        return default
    text = cm.read_text(errors="replace")
    m = re.search(r"install\(DIRECTORY[^)]*rocm_sysdeps/lib/\"[^)]*COMPONENT\s+rocm-sysdeps-vision[^)]*\)", text, re.S)
    pats = re.findall(r'PATTERN\s+"([^"]+)"', m.group(0)) if m else []
    return pats or default


def cmd_tarball(a) -> int:
    rec = Recorder(a.results, a.suite, "tarball")
    tb, root = Path(a.tarball), Path(a.root)
    entries: dict[str, Entry] = {}
    unsafe = []
    try:
        with tarfile.open(tb, "r:*") as tf:
            for m in tf:
                name = m.name
                if name.startswith("/") or ".." in PurePosixPath(name).parts:
                    unsafe.append(name)
                    continue
                rel = os.path.normpath(name)
                if rel == ".":
                    continue
                kind = "d" if m.isdir() else "l" if m.issym() else "f" if m.isfile() else "h" if m.islnk() else "o"
                entries[rel] = Entry(rel, kind, m.mode, m.size, m.linkname)
    except (tarfile.TarError, OSError) as e:
        rec("extract", "error", f"cannot read {tb.name}: {e}")
        return 0
    others = [p for p, e in entries.items() if e.kind in ("h", "o")]
    counts = {k: sum(1 for e in entries.values() if e.kind == k) for k in "fdl"}
    rec("safe-paths", "fail" if unsafe or others else "pass",
        (f"absolute or ../ members: {short_list(unsafe)}; " if unsafe else "")
        + (f"hardlinks/devices: {short_list(others)}; " if others else "")
        + f"{len(entries)} entries: {counts['f']} files, {counts['d']} dirs, {counts['l']} symlinks")
    if unsafe:
        return 0
    root.mkdir(parents=True, exist_ok=True)
    r = run(["tar", "-xzf", str(tb), "-C", str(root), "--no-same-owner"])
    if r.returncode != 0:
        rec("extract", "error", f"tar -x failed: {r.stderr.strip()[:500]}")
        return 0
    manifest_rel = "share/vision-pack/vision-pack-manifest.json"
    manifest = None
    try:
        manifest = json.loads((root / manifest_rel).read_text())
    except (OSError, ValueError) as e:
        rec("manifest.schema", "fail", f"{manifest_rel}: {e}")
    fn = re.match(r"^vision-pack-dist-linux-multiarch-(.+)\.tar\.gz$", tb.name)
    if not fn:
        rec("name", "fail", f"unexpected file name {tb.name}")
    elif manifest is not None:
        rec("name", "pass" if fn.group(1) == manifest.get("version") else "fail",
            f"file version {fn.group(1)}, manifest version {manifest.get('version')}")
    top = sorted({p.split("/")[0] for p in entries})
    extra_top = [t for t in top if t not in ("bin", "include", "lib", "share")]
    rec("layout", "fail" if extra_top else "pass",
        f"top-level: {' '.join(top)}" + (f"; unexpected: {' '.join(extra_top)}" if extra_top else ""))
    # symlinks
    broken = []
    for p, e in entries.items():
        if e.kind == "l":
            if e.target.startswith("/"):
                broken.append(f"{p} -> {e.target} (absolute)")
            elif resolve_link(entries, p) is None:
                broken.append(f"{p} -> {e.target}")
    rec("symlinks", "fail" if broken else "pass",
        ("dangling or escaping links: " + short_list(broken)) if broken else f"{counts['l']} links resolve in-tree")
    # soname chains
    stems: dict[str, list[str]] = defaultdict(list)
    for p, e in entries.items():
        m = re.match(r"^(.*/lib[^/]*?)\.so(\.[0-9.]+)?$", p)
        if m and e.kind == "f":
            stems[m.group(1)].append(p)
    flat = {s: v for s, v in stems.items() if len(v) > 1}
    rec("soname-chains", "fail" if flat else "pass",
        ("more than one real file per library: " + short_list(f"{s}: {len(v)}" for s, v in flat.items()))
        if flat else f"{len(stems)} libraries, one real file each")
    # executables
    runvx = entries.get("bin/runvx")
    if runvx is None:
        rec("runvx.exec", "fail", "bin/runvx absent")
    else:
        rec("runvx.exec", "pass" if runvx.mode & 0o111 else "fail", f"mode {runvx.mode:04o}")
    noexec = [p for p, e in entries.items() if p.startswith("bin/") and e.kind == "f" and not e.mode & 0o111]
    rec("bin.exec", "fail" if noexec else "pass", short_list(noexec) if noexec else "")
    # manifest schema
    if manifest is not None:
        errs = []
        if not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("sha", ""))):
            errs.append(f"sha {manifest.get('sha')!r} is not a 40-hex commit")
        if not re.match(r"^\d", str(manifest.get("version", ""))):
            errs.append(f"version {manifest.get('version')!r}")
        if not isinstance(manifest.get("rocm_sdk"), str) or not manifest.get("rocm_sdk"):
            errs.append("rocm_sdk missing or empty")
        gt = manifest.get("gpu_targets")
        if not isinstance(gt, dict) or not gt:
            errs.append("gpu_targets missing or empty")
        else:
            for lib, targets in gt.items():
                if not isinstance(targets, list) or not targets or not all(
                        isinstance(t, str) and re.fullmatch(r"gfx[0-9a-f]+", t) for t in targets):
                    errs.append(f"gpu_targets.{lib} is not a non-empty list of gfx names")
                if not any(p.startswith(f"lib/{lib}.so") for p in entries):
                    errs.append(f"gpu_targets names {lib}, which is not in lib/")
        subs = manifest.get("submodules")
        if not isinstance(subs, list) or not subs:
            errs.append("submodules missing or empty")
        else:
            for s in subs:
                if not isinstance(s, dict) or not s.get("path") or not s.get("url") or not re.fullmatch(
                        r"[0-9a-f]{40}", str(s.get("commit", ""))):
                    errs.append(f"bad submodule entry {s!r}"[:200])
            paths = {s.get("path") for s in subs if isinstance(s, dict)}
            for lib in ("mivisionx", "rocal", "roccv", "rocpydecode"):
                if lib not in paths:
                    errs.append(f"submodule {lib} missing")
        rec("manifest.schema", "fail" if errs else "pass",
            "; ".join(errs) or f"version {manifest['version']}, sha {manifest['sha'][:12]}, rocm_sdk "
            f"{manifest['rocm_sdk']}, {len(gt)} gpu_targets libs, {len(subs)} submodules")
        expected, source = "", ""
        if a.release_json and Path(a.release_json).is_file():
            expected = json.loads(Path(a.release_json).read_text()).get("target_commitish", "")
            source = "release target_commitish"
        elif a.expected_sha:
            expected, source = a.expected_sha, "--expected-sha"
        if expected:
            rec("manifest.sha", "pass" if expected == manifest.get("sha") else "fail",
                f"manifest {manifest.get('sha')} vs {source} {expected}")
        else:
            rec("manifest.sha", "skip", "no release JSON or expected sha given")
    # ELF objects
    aliases = alias_names(entries)
    no_build_id, ci_paths, so644 = [], [], []
    for p, e in sorted(entries.items()):
        fp = root / p
        if e.kind != "f" or not is_elf(fp):
            continue
        name = aliases.get(p, p)
        dyn = elf_dynamic(fp)
        rps = dyn.get("RUNPATH", []) + dyn.get("RPATH", [])
        if p.startswith(("bin/", "lib/")):
            bad = [t for rp in rps for t in bad_runpath_tokens(rp)]
            if bad:
                rec(f"runpath::{name}", "fail", f"non-relocatable RUNPATH entries: {' '.join(bad)} "
                                                f"(RUNPATH [{':'.join(rps)}])")
            else:
                rec(f"runpath::{name}", "pass", f"[{':'.join(rps)}]" if rps else "no RUNPATH")
        if not elf_has_build_id(fp):
            no_build_id.append(name)
        if file_has(fp, re.compile(rb"/__w/")):
            ci_paths.append(name)
        if re.search(r"\.so(\.\d+)*$", p) and not e.mode & 0o111:
            so644.append(name)
    rec("elf.build-id", "fail" if no_build_id else "pass",
        ("ELF objects without a GNU build-id: " + short_list(no_build_id, 20)) if no_build_id else "")
    rec("elf.ci-paths", "fail" if ci_paths else "pass",
        ("CI checkout paths (/__w/...) embedded in: " + short_list(ci_paths, 20)) if ci_paths else "")
    rec("so-mode", "fail" if so644 else "pass",
        ("shared libraries shipped 0644 while the other libraries (and TheRock's sysdeps) are 0755: "
         + short_list(so644, 20)) if so644 else "")
    ed = empty_dirs(list(entries.values()))
    rec("empty-dirs", "fail" if ed else "pass", ("empty directories: " + short_list(ed)) if ed else "")
    asan = sorted(p for p, e in entries.items() if e.kind == "d" and re.fullmatch(r"share/doc/[^/]+-asan", p))
    rec("asan-doc-dirs", "fail" if asan else "pass",
        ("ASan doc folders in a Release build with no ASan libraries: " + short_list(asan)) if asan else "")
    pcs = [p for p in entries if p.endswith(".pc")]
    rec("pkgconfig", "pass" if pcs else "fail",
        short_list(pcs) if pcs else "no pkg-config (.pc) files for libopenvx, librocal or libroccv")
    sysdir = "lib/rocm_sysdeps/lib"
    bases = [PurePosixPath(p).name for p in entries if p.startswith(sysdir + "/")]
    needed_all: set[str] = set()
    for p, e in entries.items():
        if e.kind == "f" and p.startswith("lib/") and is_elf(root / p):
            needed_all.update(elf_dynamic(root / p).get("NEEDED", []))
    for pat in sysdeps_patterns(Path(a.vp_src) if a.vp_src else None):
        stem = pat.split(".so")[0]
        hits = [b for b in bases if fnmatch.fnmatch(b, pat)]
        users = [n for n in needed_all if n.startswith(stem + ".so")]
        if hits:
            rec(f"sysdeps::{stem}", "pass", short_list(hits, 4))
        else:
            rec(f"sysdeps::{stem}", "fail",
                f"packaging/CMakeLists.txt installs {pat} but the tree has none"
                + ("" if users else " (nothing NEEDs it; confirm the drop is intended and update the packaging)"))
    all_files = [p for p, e in entries.items() if e.kind == "f"]
    for comp, hits in license_findings(["/" + p for p in all_files], TARBALL_LICENSES).items():
        rec(f"license.{comp}", "pass" if hits else "fail",
            short_list(hits, 3) if hits else f"no {comp} license text anywhere in the tarball (H4)")
    docs = [p for p in all_files if re.match(r"^(README|INSTALL)[^/]*$", p, re.I)
            or p.startswith("share/doc/vision-pack/")]
    rec("docs.install", "pass" if docs else "fail",
        short_list(docs) if docs else "no install/usage documentation (share/doc/vision-pack/ or a top-level README): "
        "nothing says where to extract it, PYTHONPATH, Python 3.12-only modules or numpy (M3)")
    # DEB payload union must be a subset of the tarball
    if a.debs and Path(a.debs).is_dir():
        sha_cache: dict[str, str] = {}

        def tsha(rel: str) -> str:
            if rel not in sha_cache:
                h = hashlib.sha256()
                with open(root / rel, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 22), b""):
                        h.update(chunk)
                sha_cache[rel] = h.hexdigest()
            return sha_cache[rel]

        by_sha: dict[tuple[int, str], list[str]] | None = None
        missing, differ, relocated, exempt = [], [], [], []
        total = 0
        try:
            debs = load_dir(Path(a.debs), "deb", hash_files=True)
        except (RuntimeError, OSError) as e:
            rec("deb-subset", "error", str(e))
            debs = {}
        for name, pkg in sorted(debs.items()):
            if is_meta(name):
                continue
            for e in pkg.files:
                if not e.path.startswith("/opt/rocm/"):
                    exempt.append(e.path)
                    continue
                total += 1
                rel = e.path[len("/opt/rocm/"):]
                t = entries.get(rel)
                if t is None:
                    if e.kind == "f":
                        if by_sha is None:
                            by_sha = defaultdict(list)
                            for tp, te in entries.items():
                                if te.kind == "f":
                                    by_sha[(te.size, "")].append(tp)
                        cands = [c for c in by_sha.get((e.size, ""), []) if tsha(c) == e.sha256]
                        if cands:
                            relocated.append(f"{rel} -> {cands[0]}")
                            continue
                    missing.append(f"{rel} ({name})")
                elif t.kind != e.kind:
                    differ.append(f"{rel}: DEB {e.kind}, tarball {t.kind}")
                elif e.kind == "l" and t.target != e.target:
                    differ.append(f"{rel}: link {e.target} vs {t.target}")
                elif e.kind == "f" and tsha(rel) != e.sha256:
                    differ.append(f"{rel}: content differs ({name})")
        if debs:
            deb_rels = {e.path[len("/opt/rocm/"):] for n, p in debs.items() for e in p.files
                        if e.path.startswith("/opt/rocm/")}
            tar_only = sorted(p for p in all_files if p not in deb_rels)
            tops = sorted({"/".join(p.split("/")[:3]) for p in tar_only})
            info = (f"{total} DEB payload entries checked; exempt (outside /opt/rocm): {short_list(sorted(set(exempt)))}"
                    + (f"; same content at another path: {short_list(relocated, 4)}" if relocated else "")
                    + f"; {len(tar_only)} tarball files are in no DEB, under: {short_list(tops, 10)}")
            if missing or differ:
                rec("deb-subset", "fail", f"missing from tarball: {short_list(missing)}; differ: {short_list(differ)}; "
                    + info)
            else:
                rec("deb-subset", "pass", info)
    else:
        rec("deb-subset", "skip", "no --debs given")
    print(f"tarball: {len(entries)} entries ({counts['f']} files, {counts['d']} dirs, {counts['l']} symlinks)")
    return 0


# ---------------------------------------------------------------------------
# depends: external dependencies vs a repository index
# ---------------------------------------------------------------------------
def repo_index(fmt: str, path: Path) -> dict[str, list[str]]:
    """capability -> list of versions ('' = unversioned provide)."""
    idx: dict[str, list[str]] = defaultdict(list)
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if fmt == "deb":
        for stanza in raw.decode("utf-8", "replace").split("\n\n"):
            f = parse_control(stanza)
            if not f.get("Package"):
                continue
            idx[f["Package"]].append(f.get("Version", ""))
            for n, op, v in parse_deb_depends(f.get("Provides", "")):
                idx[n].append(v if op == "=" else "")
    else:
        ns = {"c": "http://linux.duke.edu/metadata/common", "r": "http://linux.duke.edu/metadata/rpm"}
        root = ET.fromstring(raw)
        for p in root.findall("c:package", ns):
            name = p.findtext("c:name", default="", namespaces=ns)
            v = p.find("c:version", ns)
            evr = f"{v.get('epoch', '0')}:{v.get('ver')}-{v.get('rel')}" if v is not None else ""
            idx[name].append(evr)
            for e in p.findall("c:format/r:provides/r:entry", ns):
                pv = ""
                if e.get("ver"):
                    pv = f"{e.get('epoch', '0')}:{e.get('ver')}" + (f"-{e.get('rel')}" if e.get("rel") else "")
                idx[e.get("name", "")].append(pv)
    return idx


RPM_FLAG_OP = {"GE": ">=", "LE": "<=", "EQ": "=", "GT": ">", "LT": "<"}


def cmd_depends(a) -> int:
    rec = NullRecorder() if a.no_records else Recorder(a.results, a.suite, a.group)
    d = Path(a.pkg_dir)
    local: set[str] = set()
    wants: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for f in sorted(d.glob(f"*.{a.format}")):
        if a.format == "deb":
            fields = parse_control(run(["dpkg-deb", "-f", str(f)]).stdout)
            local.add(fields.get("Package", ""))
            local.update(n for n, _, _ in parse_deb_depends(fields.get("Provides", "")))
            for n, op, v in parse_deb_depends(fields.get("Depends", "")) + parse_deb_depends(
                    fields.get("Pre-Depends", "")):
                wants[n].append((op, v, fields.get("Package", "")))
        else:
            p = read_rpm(f)
            local.add(p.name)
            local.update(n for n, _, _ in p.provides)
            for n, t, op, v in p.requires:
                if n.startswith(("rpmlib(", "/", "rtld(")):
                    continue
                base = n.split("(")[0]
                if ".so" in n and OS_SONAME_RE.match(base):
                    continue
                if n in ("python3",) or t.startswith("post") or t == "interp":
                    continue
                wants[n].append((op, v, p.name))
    ext = {n: c for n, c in wants.items() if n not in local}
    try:
        idx = repo_index(a.format, Path(a.index)) if a.index else {}
    except (OSError, ValueError, ET.ParseError) as e:
        rec("depends::index", "error", f"cannot parse repository index: {e}")
        idx = {}
    stubs = []
    caps = sorted(n for n in ext if ".so" in n or "(" in n)
    if caps:
        unsat_caps = [c for c in caps if not idx.get(c)]
        internal = [c for c in unsat_caps if "-rocm-vision" in c]
        if not a.index:
            rec("depends::capabilities", "blocked", f"{len(caps)} soname capabilities; no repository index")
        elif unsat_caps:
            rec("depends::capabilities", "fail",
                f"{len(unsat_caps)}/{len(caps)} automatic capabilities have no provider: {short_list(unsat_caps, 8)}"
                + ("; the -rocm-vision ones must come from the vision set itself, which does not provide them "
                   "(see rpm::<pkg>::requires.closure)" if internal else ""))
        else:
            rec("depends::capabilities", "pass", f"{len(caps)} soname capabilities provided by the repository")
    for n in sorted(ext):
        if n in caps:
            continue
        cons = sorted({(op, v) for op, v, _ in ext[n]})
        users = sorted({u for _, _, u in ext[n]})
        want_s = ", ".join(f"{op} {v}" if op else "any" for op, v in cons)
        stub_ver = next((v for op, v in cons if op in (">=", "=")), "") or "0"
        if not a.index:
            rec(f"depends::{n}", "blocked", f"needs {want_s} (required by {short_list(users, 4)}); no repository index")
            stubs.append((n, stub_ver))
            continue
        have = idx.get(n, [])
        if not have:
            rec(f"depends::{n}", "fail", f"not in the repository (needs {want_s}; required by {short_list(users, 4)})")
            stubs.append((n, stub_ver))
            continue
        ok = [h for h in have if all(not op or (h and satisfies(h, op, v, a.format)) for op, v in cons)]
        if ok:
            rec(f"depends::{n}", "pass", f"{want_s} satisfied by {short_list(sorted(set(ok)), 3)}")
        else:
            rec(f"depends::{n}", "fail",
                f"repository has {short_list(sorted(set(h or 'unversioned' for h in have)), 3)}, which does not "
                f"satisfy {want_s} (required by {short_list(users, 4)})"
                + ("; a '~' pre-release version sorts below the release it precedes" if any("~" in h for h in have)
                   else ""))
            stubs.append((n, stub_ver))
    if a.stubs_out:
        Path(a.stubs_out).write_text("".join(f"{n}\t{v}\n" for n, v in stubs), encoding="utf-8")
    print(f"external dependencies: {len(ext)}; unresolvable: {len(stubs)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=os.environ.get("VP_RESULTS", ""))
    ap.add_argument("--suite", default=os.environ.get("VP_SUITE", "packaging"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("upstream-log")
    p.add_argument("--log", required=True)
    p.add_argument("--log-rel", default="")
    p.add_argument("--rc", type=int, required=True)
    p.add_argument("--debs", default="")
    p.add_argument("--summary-md", default="")
    p = sub.add_parser("deb")
    p.add_argument("--debs", required=True)
    p.add_argument("--work", required=True)
    p = sub.add_parser("rpm")
    p.add_argument("--rpms", required=True)
    p.add_argument("--debs", default="")
    p.add_argument("--work", required=True)
    p = sub.add_parser("tarball")
    p.add_argument("--tarball", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--debs", default="")
    p.add_argument("--release-json", default="")
    p.add_argument("--expected-sha", default="")
    p.add_argument("--vp-src", default="")
    p = sub.add_parser("depends")
    p.add_argument("--pkg-dir", required=True)
    p.add_argument("--format", choices=("deb", "rpm"), required=True)
    p.add_argument("--index", default="")
    p.add_argument("--group", required=True)
    p.add_argument("--stubs-out", default="")
    p.add_argument("--no-records", action="store_true", help="only write --stubs-out")
    a = ap.parse_args(argv)
    if not a.results:
        ap.error("--results (or VP_RESULTS) is required")
    return {"upstream-log": cmd_upstream_log, "deb": cmd_deb, "rpm": cmd_rpm, "tarball": cmd_tarball,
            "depends": cmd_depends}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
