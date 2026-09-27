#!/usr/bin/env python3
"""Standalone-tarball scenario: the vision-pack payload on its own, without the
ROCm SDK. With VP_DIST_TARBALL the dist tarball is extracted into a scratch
prefix; otherwise the vision-pack-owned ELF objects and their SONAME symlinks
are copied out of $ROCM_PATH with the same layout. Every ELF object is then
run through `ldd` (no LD_LIBRARY_PATH).

  standalone.ldd::<obj>  every NOTFOUND is an expected SDK library (a glob in
                         expected_notfound.txt that the SDK part of $ROCM_PATH
                         provides), vision-pack's own dependencies resolve inside
                         the scratch prefix, and nothing else escapes to the host.
The tarball is expected to need the ROCm prefix; unexpected NOTFOUNDs fail.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shutil
import tarfile

from sdkutil import HERE, ROCM, Recorder, customer_env, log_path, run, work_dir
from vp_owned import BASE_LIB_RE, CI_PARITY_SUBDIRS, owned_elfs, owned_from_patterns


def expected_globs() -> list[str]:
    with open(os.path.join(HERE, "expected_notfound.txt"), encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def sdk_provides(soname: str, owned: set[str]) -> bool:
    for d in CI_PARITY_SUBDIRS:
        rel = f"{d}/{soname}"
        if os.path.exists(os.path.join(ROCM, rel)) and rel not in owned:
            return True
    return False


def stage(prefix: str, log) -> tuple[str, set[str]]:
    shutil.rmtree(prefix, ignore_errors=True)
    os.makedirs(prefix)
    tarball = os.environ.get("VP_DIST_TARBALL", "")
    if tarball and os.path.isfile(tarball):
        with tarfile.open(tarball, "r:*") as t:
            names = t.getnames()
            t.extractall(prefix, filter="data")
        owned = {(m[2:] if m.startswith("./") else m).rstrip("/") for m in names}
        return f"extracted {os.path.basename(tarball)}", owned
    entries = owned_from_patterns(ROCM)
    elf_rels = {e["rel"] for e in owned_elfs(ROCM, entries)}
    copied = 0
    for rel, kind in sorted(entries.items()):
        src, dst = os.path.join(ROCM, rel), os.path.join(prefix, rel)
        if kind == "file" and rel in elf_rels:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        elif kind == "symlink" and os.path.realpath(src)[len(os.path.realpath(ROCM)) + 1:] in elf_rels:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.symlink(os.readlink(src), dst)
    log.write(f"copied {copied} ELF objects (+ SONAME symlinks) into {prefix}\n")
    return f"emulated: {copied} vision-pack ELF objects copied from the prefix (no VP_DIST_TARBALL)", set(entries)


def main() -> int:
    rec = Recorder()
    prefix = str(work_dir("standalone") / "prefix")
    log_file = log_path("standalone-ldd.log")
    globs = expected_globs()
    with open(log_file, "w", encoding="utf-8") as log:
        how, owned = stage(prefix, log)
        log.write(how + "\n")
        entries = {}
        for root, _dirs, files in os.walk(prefix):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), prefix)
                entries[rel] = "symlink" if os.path.islink(os.path.join(root, f)) else "file"
        elfs = owned_elfs(prefix, entries)
        if not elfs:
            rec("standalone.ldd::stage", "error", f"no ELF objects in the scratch prefix ({how})", log=log_file)
            return 0
        for e in elfs:
            rc, out, _ = run(["ldd", e["path"]], env=customer_env(), timeout=180)
            log.write(f"===== {e['name']}\n{out}\n")
            unexpected, expected, escapes = [], [], []
            for line in out.splitlines():
                line = line.strip()
                m = re.match(r"^(\S+) => not found", line)
                if m:
                    so = m.group(1)
                    ok = any(fnmatch.fnmatchcase(so, g) for g in globs) and sdk_provides(so, owned)
                    (expected if ok else unexpected).append(so)
                    continue
                m = re.match(r"^(\S+) => (\S+) \(0x", line)
                if m and not m.group(2).startswith(prefix + "/") and not BASE_LIB_RE.match(m.group(1)):
                    so = m.group(1)
                    if any(fnmatch.fnmatchcase(so, g) for g in globs):
                        expected.append(f"{so}(host)")
                    else:
                        escapes.append(f"{so}=>{m.group(2)}")
            expected, unexpected = sorted(set(expected)), sorted(set(unexpected))
            if unexpected or escapes or (rc != 0 and not expected and "not found" not in out):
                rec(f"standalone.ldd::{e['name']}", "fail",
                    f"unexpected NOTFOUND: {' '.join(unexpected) or '-'}; host escapes: {' '.join(escapes) or '-'}; "
                    f"expected SDK NOTFOUND: {' '.join(expected) or '-'} [{how}]", log=log_file)
            else:
                rec(f"standalone.ldd::{e['name']}", "pass",
                    f"only SDK libraries missing: {' '.join(expected) or 'none'} [{how}]", log=log_file)
    shutil.rmtree(os.path.dirname(prefix), ignore_errors=True)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
