#!/usr/bin/env python3
"""Static audit of the shipped ELF objects.

Always (quick tier and up):
  fatbin.has-gfx::<lib>         the detected VP_GFX has a code object in .hip_fatbin
  fatbin.manifest::<lib>        the code objects match the manifest's gpu_targets
  fatbin.duplicate::<lib>       .hip_fatbin is not a byte copy of another library's
Standard tier and up:
  elf-hardening::<obj>          NX stack, no TEXTREL, no RWX segment, PIE executables
                                (RELRO/BIND_NOW/canary/FORTIFY listed in the message)
  elf-hardening.canary-fortify::<sysdep>  bundled parsers of untrusted input
                                (jpeg/protobuf/lmdb/sndfile) use stack protector + FORTIFY
  elf-hygiene.build-id::<obj>   a GNU build-id note is present
  elf-hygiene.mode::<obj>       shared objects are 0755 like the rest of ROCm
                                (RPM elfdeps skips non-executable files)
  symbols.stdcxx-leak::<obj>    no strong definitions of host libstdc++ symbols exported
  symbols.dup-exports::<lib>    libraries linking libopenvx do not re-export its symbols
  hardcoded-paths.elf::<obj>    no build-machine paths embedded (/__w/..., the manifest's
                                build rocm_path, /home/runner/...)
  hardcoded-paths.text::<kind>  same scan over shipped text files (cmake, python, headers, share)
"""
from __future__ import annotations

import json
import mmap
import os
import re
import stat

from vp_owned import ROCM, Recorder, customer_env, fatbin_info, load_manifest, load_owned, log_path, run, tier_ge


def nm_dyn(path: str) -> list[tuple[str, str]]:
    rc, out, _ = run(["nm", "-D", path], timeout=300)
    syms = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms.append((parts[1], parts[2].split("@")[0]))
        elif len(parts) == 2:
            syms.append((parts[0], parts[1].split("@")[0]))
    return syms


def strong_defs(syms) -> set[str]:
    return {n for t, n in syms if t in ("T", "D", "B", "R", "G", "S", "i")}


def all_defs(syms) -> set[str]:
    return {n for t, n in syms if t != "U" and t not in ("w", "v")}


def host_libstdcxx(elfs) -> str:
    for e in elfs:
        if "libstdc++.so.6" in e["dyn"]["needed"]:
            rc, out, _ = run(["ldd", e["path"]], env=customer_env(), timeout=120)
            m = re.search(r"libstdc\+\+\.so\.6 => (\S+)", out)
            if m:
                return m.group(1)
    return ""


def build_patterns(manifest: dict) -> list[bytes]:
    pats = [rb"/__w/[\x21-\x7e]+", rb"/home/runner/[\x21-\x7e]+", rb"/github/workspace[\x21-\x7e]*"]
    rp = str(manifest.get("rocm_path", "")).rstrip("/")
    real = os.path.realpath(ROCM)
    if rp and rp not in ("/opt/rocm", ROCM, real):
        pats.append(re.escape(rp.encode()) + rb"/[\x21-\x7e]*")
    return pats


def scan(path: str, regex: re.Pattern) -> list[str]:
    with open(path, "rb") as f:
        if os.fstat(f.fileno()).st_size == 0:
            return []
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            return [m.group(0).decode(errors="replace") for m in regex.finditer(mm)]
        finally:
            mm.close()


def main() -> int:
    rec = Recorder()
    owned = load_owned()
    elfs = owned["elfs"]
    manifest = load_manifest()
    log_file = log_path("elf-audit.log")
    raw = {}
    gfx = os.environ.get("VP_GFX", "")

    # --- fatbin ---
    fat = {e["name"]: fatbin_info(e["path"]) for e in elfs if e["kind"] == "lib"}
    fat = {k: v for k, v in fat.items() if v["section"]}
    targets = manifest.get("gpu_targets") or {}
    order = sorted(fat, key=lambda n: (not os.path.basename(n).startswith("libopenvx"), n))
    for i, name in enumerate(order):
        info = fat[name]
        raw.setdefault(name, {})["fatbin"] = info
        if not gfx:
            rec(f"fatbin.has-gfx::{name}", "blocked", "no GPU detected (VP_GFX empty)")
        elif gfx in info["arches"]:
            rec(f"fatbin.has-gfx::{name}", "pass", f"{gfx} present among {len(info['arches'])} arch(es)", log=log_file)
        else:
            rec(f"fatbin.has-gfx::{name}", "fail", f"{gfx} missing; code objects: {' '.join(info['arches'])}",
                log=log_file)
        base = os.path.basename(name).split(".so")[0]
        if base in targets:
            want = sorted(targets[base])
            rec(f"fatbin.manifest::{name}", "pass" if want == info["arches"] else "fail",
                f"{len(want)} arch(es) as in the manifest" if want == info["arches"] else
                f"manifest {' '.join(want)} vs shipped {' '.join(info['arches'])}", log=log_file)
        if i > 0:
            twins = [o for o in order[:i] if fat[o]["sha256"] == info["sha256"]]
            rec(f"fatbin.duplicate::{name}", "fail" if twins else "pass",
                f".hip_fatbin ({info['bytes'] / 1e6:.1f} MB) is byte-identical to {', '.join(twins)}" if twins else
                "own device code", log=log_file)

    if not tier_ge("standard"):
        with open(os.path.join(os.environ["VP_OUT"], "raw", "elf_audit.json"), "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=1)
        return 0

    stdcxx = host_libstdcxx(elfs)
    stdcxx_defs = all_defs(nm_dyn(stdcxx)) if stdcxx else set()
    openvx = next((e for e in elfs if os.path.basename(e["rel"]).startswith("libopenvx.so")), None)
    openvx_strong = strong_defs(nm_dyn(openvx["path"])) if openvx else set()
    regex = re.compile(b"|".join(build_patterns(manifest)))

    with open(log_file, "a", encoding="utf-8") as log:
        for e in elfs:
            p, name = e["path"], e["name"]
            _, ph, _ = run(["readelf", "-lW", p], timeout=120)
            _, hdr, _ = run(["readelf", "-hW", p], timeout=60)
            _, notes, _ = run(["readelf", "-nW", p], timeout=60)
            _, dy, _ = run(["readelf", "-dW", p], timeout=60)
            dyn = e["dyn"]
            syms = nm_dyn(p)
            gnu_stack = next((ln.split() for ln in ph.splitlines() if "GNU_STACK" in ln), None)
            nx = bool(gnu_stack) and "E" not in gnu_stack[-2]
            rwx = any(ln.split()[0] == "LOAD" and "RWE" in ln for ln in ph.splitlines() if ln.split())
            textrel = "(TEXTREL)" in dy or "TEXTREL" in dyn["flags"]
            relro = "GNU_RELRO" in ph
            bindnow = "BIND_NOW" in dy or bool(re.search(r"FLAGS_1\).*\bNOW\b", dy))
            canary = any(t == "U" and n == "__stack_chk_fail" for t, n in syms)
            fortify = any(t == "U" and re.fullmatch(r"__\w+_chk", n) for t, n in syms)
            pie = "DYN (" in hdr
            row = {"nx_stack": nx, "rwx_segment": rwx, "textrel": textrel,
                   "relro": "full" if relro and bindnow else "partial" if relro else "none",
                   "bind_now": bindnow, "canary": canary, "fortify": fortify, "pie": pie if e["kind"] == "exe" else None,
                   "build_id": "Build ID" in notes, "mode": oct(stat.S_IMODE(os.stat(p).st_mode))}
            raw.setdefault(name, {})["hardening"] = row
            log.write(f"{name}: {row}\n")
            bad = [k for k, v in (("executable stack", not nx), ("RWX segment", rwx), ("TEXTREL", textrel),
                                  ("not PIE", e["kind"] == "exe" and not pie)) if v]
            info = (f"RELRO={row['relro']} BIND_NOW={bindnow} canary={canary} FORTIFY={fortify}")
            rec(f"elf-hardening::{name}", "fail" if bad else "pass",
                (f"{', '.join(bad)}; " if bad else "NX stack, no TEXTREL/RWX; ") + info, log=log_file)
            if e["rel"].startswith("lib/rocm_sysdeps/"):
                rec(f"elf-hardening.canary-fortify::{name}", "pass" if canary and fortify else "fail",
                    f"bundled parser: stack protector={canary} FORTIFY={fortify} (distro copies have both)",
                    log=log_file)
            rec(f"elf-hygiene.build-id::{name}", "pass" if row["build_id"] else "fail",
                "GNU build-id present" if row["build_id"] else "no GNU build-id note (debuginfo cannot be matched)",
                log=log_file)
            mode_ok = bool(os.stat(p).st_mode & stat.S_IXUSR)
            rec(f"elf-hygiene.mode::{name}", "pass" if mode_ok else "fail",
                f"mode {row['mode']}" + ("" if mode_ok else " (other ROCm/vision .so are 0755; RPM elfdeps skips "
                                         "non-executable files for Provides)"), log=log_file)

            if e["kind"] != "exe":
                if not stdcxx:
                    rec(f"symbols.stdcxx-leak::{name}", "blocked", "host libstdc++.so.6 not resolvable")
                else:
                    leak = sorted(strong_defs(syms) & stdcxx_defs)
                    rec(f"symbols.stdcxx-leak::{name}", "fail" if leak else "pass",
                        f"{len(leak)} strong libstdc++ definitions exported (interpose the host libstdc++), e.g. "
                        f"{' '.join(leak[:4])}" if leak else "no libstdc++ internals exported", log=log_file)
            if openvx and e is not openvx and any(n.startswith("libopenvx.so") for n in dyn["needed"]) \
                    and e["kind"] == "lib":
                dup = sorted((strong_defs(syms) & openvx_strong) - stdcxx_defs)
                rec(f"symbols.dup-exports::{name}", "fail" if dup else "pass",
                    f"re-exports {len(dup)} strong libopenvx symbols, e.g. {' '.join(dup[:4])}" if dup else
                    "no libopenvx symbols re-exported", log=log_file)

            hits = scan(p, regex)
            rec(f"hardcoded-paths.elf::{name}", "fail" if hits else "pass",
                f"{len(hits)} build-machine path(s), e.g. {' | '.join(sorted(set(hits))[:3])}" if hits else
                "no build-machine paths", log=log_file)

        cats: dict[str, list[str]] = {"cmake": [], "python": [], "headers": [], "share": []}
        for rel, kind in owned["entries"].items():
            full = os.path.join(ROCM, rel)
            if kind != "file" or rel.startswith("share/vision-pack/") or os.path.getsize(full) > 20_000_000:
                continue
            if rel in {e["rel"] for e in elfs}:
                continue
            if rel.endswith(".cmake") or "/cmake/" in rel:
                cat = "cmake"
            elif rel.endswith((".py", ".pyi")):
                cat = "python"
            elif rel.startswith("include/"):
                cat = "headers"
            else:
                cat = "share"
            for h in scan(full, regex):
                cats[cat].append(f"{rel}: {h}")
        for cat, hits in cats.items():
            log.write(f"text {cat}: {hits[:50]}\n")
            rec(f"hardcoded-paths.text::{cat}", "fail" if hits else "pass",
                f"{len(hits)} hit(s): {' | '.join(hits[:3])}" if hits else "no build-machine paths", log=log_file)
    with open(os.path.join(os.environ["VP_OUT"], "raw", "elf_audit.json"), "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=1)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
