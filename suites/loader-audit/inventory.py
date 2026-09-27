#!/usr/bin/env python3
"""Inventory of the installed vision-pack payload against its manifest.

  inventory::manifest-schema             version, 40-hex sha, rocm_sdk, submodules, gpu_targets
  inventory::gpu-target-lib.<base>       every gpu_targets library is installed
  inventory::runtime-dep.<name>          every "runtime" third-party submodule ships its
                                         isolated *-rocm-vision library
  inventory::vision-library.<name>       every "vision library" submodule ships its artifacts
  inventory::protobuf-lite               libprotobuf-lite-rocm-vision is shipped (0.1.0 had it)
  inventory::pkg-config-files            the payload ships pkg-config files
  inventory::tarball-vs-prefix           (VP_DIST_TARBALL) every tarball entry is identical in
                                         the prefix: type, mode, size, link target, sha256
  inventory::no-stale-files              (VP_DIST_TARBALL) nothing in vision-owned dirs that the
                                         tarball does not ship
"""
from __future__ import annotations

import glob
import hashlib
import os
import re
import stat
import tarfile

from vp_owned import OWNED_DIRS, ROCM, Recorder, load_manifest, load_owned, log_path, tier_ge

RUNTIME_LIBS = {
    "libjpeg-turbo": ["libjpeg-rocm-vision", "libturbojpeg-rocm-vision"],
    "libsndfile": ["libsndfile-rocm-vision"],
    "lmdb": ["liblmdb-rocm-vision"],
    "protobuf": ["libprotobuf-rocm-vision"],
}
VISION_ARTIFACTS = {
    "mivisionx": ["lib/libopenvx.so", "lib/libvxu.so", "lib/libvx_rpp.so", "bin/runvx", "include/mivisionx/VX/vx.h",
                  "lib/cmake/FindMIVisionX.cmake"],
    "rocal": ["lib/librocal.so", "lib/rocal_pybind*.so", "lib/amd/rocal/__init__.py", "include/rocal/rocal_api.h",
              "lib/cmake/Findrocal.cmake"],
    "roccv": ["lib/libroccv.so", "lib/rocpycv*.so", "include/roccv", "lib/cmake/roccv/roccvConfig.cmake"],
    "rocpydecode": ["lib/rocpydecode*.so", "lib/rocpyjpegdecode*.so", "lib/pyRocVideoDecode/__init__.py",
                    "lib/pyRocJpegDecode/__init__.py"],
}


def exists(pattern: str) -> bool:
    return bool(glob.glob(os.path.join(ROCM, pattern)))


def sha(fobj) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: fobj.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def compare_tarball(tarball: str) -> tuple[int, list[str], set[str]]:
    match, problems, names = 0, [], set()
    with tarfile.open(tarball, "r:*") as t:
        for ti in t:
            rel = (ti.name[2:] if ti.name.startswith("./") else ti.name).rstrip("/")
            if rel in ("", "."):
                continue
            names.add(rel)
            p = os.path.join(ROCM, rel)
            try:
                st = os.lstat(p)
            except FileNotFoundError:
                problems.append(f"missing {rel}")
                continue
            if ti.issym():
                if not stat.S_ISLNK(st.st_mode) or os.readlink(p) != ti.linkname:
                    problems.append(f"symlink differs {rel}")
                    continue
            elif ti.isdir():
                if not stat.S_ISDIR(st.st_mode):
                    problems.append(f"not a dir {rel}")
                    continue
            elif ti.isfile():
                if not stat.S_ISREG(st.st_mode):
                    problems.append(f"not a regular file {rel}")
                    continue
                if (st.st_mode & 0o7777) != (ti.mode & 0o7777):
                    problems.append(f"mode {oct(ti.mode & 0o7777)} vs {oct(st.st_mode & 0o7777)} {rel}")
                    continue
                if st.st_size != ti.size:
                    problems.append(f"size differs {rel}")
                    continue
                with open(p, "rb") as f:
                    if sha(t.extractfile(ti)) != sha(f):
                        problems.append(f"content differs {rel}")
                        continue
            match += 1
    return match, problems, names


def main() -> int:
    rec = Recorder()
    owned = load_owned()
    entries = owned["entries"]
    m = load_manifest()
    log_file = log_path("inventory.log")

    schema = []
    if not isinstance(m.get("version"), str) or not m.get("version"):
        schema.append("version")
    if not re.fullmatch(r"[0-9a-f]{40}", str(m.get("sha", ""))):
        schema.append("sha")
    if not isinstance(m.get("rocm_sdk"), str):
        schema.append("rocm_sdk")
    if not isinstance(m.get("submodules"), list) or not all("path" in s and "commit" in s for s in m["submodules"]):
        schema.append("submodules")
    if not isinstance(m.get("gpu_targets"), dict) or not m.get("gpu_targets"):
        schema.append("gpu_targets")
    rec("inventory::manifest-schema", "fail" if schema else "pass",
        f"missing/invalid: {', '.join(schema)}" if schema else f"version {m.get('version')}", log=log_file)

    for base in sorted((m.get("gpu_targets") or {})):
        ok = f"lib/{base}.so" in entries and exists(f"lib/{base}.so")
        rec(f"inventory::gpu-target-lib.{base}", "pass" if ok else "fail",
            f"lib/{base}.so {'installed' if ok else 'missing'}", log=log_file)

    for sub in m.get("submodules") or []:
        name = os.path.basename(sub.get("path", ""))
        role = sub.get("role", "")
        if role.startswith("runtime"):
            libs = RUNTIME_LIBS.get(name, [f"lib{name}-rocm-vision"])
            missing = [lb for lb in libs if not exists(f"lib/rocm_sysdeps/lib/{lb}.so*")]
            rec(f"inventory::runtime-dep.{name}", "fail" if missing else "pass",
                f"missing: {' '.join(missing)}" if missing else f"{' '.join(libs)} present ({sub.get('describes', '')})",
                log=log_file)
        elif role == "vision library":
            arts = VISION_ARTIFACTS.get(name)
            if arts is None:
                rec(f"inventory::vision-library.{name}", "fail", "manifest lists an unknown vision library; "
                    "add its artifacts to inventory.py", log=log_file)
                continue
            missing = [a for a in arts if not exists(a)]
            rec(f"inventory::vision-library.{name}", "fail" if missing else "pass",
                f"missing: {' '.join(missing)}" if missing else f"{len(arts)} artifacts present", log=log_file)

    lite = exists("lib/rocm_sysdeps/lib/libprotobuf-lite-rocm-vision.so*")
    rec("inventory::protobuf-lite", "pass" if lite else "fail",
        "libprotobuf-lite-rocm-vision shipped" if lite else
        "libprotobuf-lite-rocm-vision no longer shipped (0.1.0 had it; nothing NEEDs it: confirm intended)",
        log=log_file)

    pc_re = re.compile(r"(openvx|vxu|vx_rpp|mivisionx|rocal|roccv|rocpy|rocm-vision)", re.I)
    pcs = sorted({os.path.relpath(p, ROCM)
                  for d in ("lib/pkgconfig", "share/pkgconfig", "lib/rocm_sysdeps/lib/pkgconfig")
                  for p in glob.glob(os.path.join(ROCM, d, "*.pc")) if pc_re.search(os.path.basename(p))}
                 | {r for r in entries if r.endswith(".pc")})
    rec("inventory::pkg-config-files", "pass" if pcs else "fail",
        f"{len(pcs)} .pc file(s)" if pcs else "no pkg-config (.pc) files for any vision library", log=log_file)

    if not tier_ge("standard"):
        return 0
    tarball = os.environ.get("VP_DIST_TARBALL", "")
    if not tarball or not os.path.isfile(tarball):
        why = "VP_DIST_TARBALL not provided (the launcher does not pass the dist tarball yet)"
        rec("inventory::tarball-vs-prefix", "blocked", why)
        rec("inventory::no-stale-files", "blocked", why)
        return 0
    match, problems, names = compare_tarball(tarball)
    with open(log_file, "a", encoding="utf-8") as log:
        log.write("\n".join(problems) + "\n")
    rec("inventory::tarball-vs-prefix", "fail" if problems else "pass",
        f"{match}/{len(names)} identical; {len(problems)} problem(s): {'; '.join(problems[:10])}", log=log_file)
    stale = []
    for d in OWNED_DIRS:
        top = os.path.join(ROCM, d)
        for root, dirs, files in os.walk(top):
            for n in dirs + files:
                rel = os.path.relpath(os.path.join(root, n), ROCM)
                if rel not in names:
                    stale.append(rel)
    rec("inventory::no-stale-files", "fail" if stale else "pass",
        f"{len(stale)} entries not in the tarball: {' '.join(stale[:10])}" if stale else
        "no stale entries in vision-owned directories", log=log_file)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
