#!/usr/bin/env python3
"""Third-party license texts and install docs in the vision-pack payload.

  license::<component>              a license text ships for every third-party
                                    component the manifest lists (runtime or
                                    compiled in): H4 when missing
  license.bundled::<owner>/<comp>   a library that embeds pybind11/dlpack ships
                                    that license in its own doc directory (so a
                                    per-package install carries it)
  license::no-asan-doc-dirs         no share/doc/*-asan folders without ASan libs
  docs::install-usage               the payload documents how to install and use
                                    the tarball (extract location, PYTHONPATH): M3
"""
from __future__ import annotations

import mmap
import os
import re

from vp_owned import ROCM, Recorder, load_manifest, load_owned, log_path

LICENSE_NAME = re.compile(r"(licen[cs]e|copying|notice|copyright|readme\.ijg)", re.I)
MARKERS = {
    "libjpeg-turbo": [r"libjpeg-turbo", r"Independent JPEG Group"],
    "libsndfile": [r"libsndfile", r"Erik de Castro Lopo"],
    "lmdb": [r"OpenLDAP Public License", r"Symas Corporation"],
    "protobuf": [r"Protocol Buffers"],
    "rapidjson": [r"RapidJSON", r"THL A29 Limited"],
    "pybind11": [r"Wenzel Jakob", r"pybind11"],
    "dlpack": [r"DLPack", r"dlpack"],
}
EMBED = {"pybind11": b"pybind11", "dlpack": b"dltensor"}
OWNER = [("librocal", "rocal"), ("rocal_pybind", "rocal"), ("libroccv", "roccv"), ("rocpycv", "roccv"),
         ("rocpyjpegdecode", "rocpyjpegdecode"), ("rocpydecode", "rocpydecode"), ("libopenvx", "mivisionx"),
         ("libvxu", "mivisionx"), ("libvx_rpp", "mivisionx"), ("runvx", "mivisionx")]


def read_text(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(2_000_000).decode("utf-8", errors="replace")
    except OSError:
        return ""


def license_files(entries: dict[str, str]) -> list[str]:
    return sorted(r for r, k in entries.items()
                  if k == "file" and r.startswith("share/doc/") and LICENSE_NAME.search(os.path.basename(r)))


def covers(rel: str, text: str, comp: str) -> bool:
    if f"/{comp}/" in f"/{rel.lower()}":
        return True
    return any(re.search(p, text) for p in MARKERS.get(comp, []))


def embeds(path: str, needle: bytes) -> bool:
    with open(path, "rb") as f:
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        try:
            return mm.find(needle) >= 0
        finally:
            mm.close()


def main() -> int:
    rec = Recorder()
    owned = load_owned()
    entries = owned["entries"]
    m = load_manifest()
    log_file = log_path("license-scan.log")
    lfiles = license_files(entries)
    texts = {r: read_text(os.path.join(ROCM, r)) for r in lfiles}
    with open(log_file, "w", encoding="utf-8") as log:
        log.write("license files in the payload:\n" + "\n".join(lfiles) + "\n")

        comps = [os.path.basename(s["path"]) for s in m.get("submodules") or []
                 if s.get("role", "vision library") != "vision library"]
        if not comps:
            rec("license::manifest-components", "error", "manifest lists no third-party submodules")
        for comp in comps:
            hits = [r for r in lfiles if covers(r, texts[r], comp)]
            log.write(f"{comp}: {hits}\n")
            rec(f"license::{comp}", "pass" if hits else "fail",
                f"license text at {', '.join(hits[:3])}" if hits else
                f"no license text for redistributed/compiled-in {comp} anywhere under share/doc", log=log_file)

        pairs: dict[str, set[str]] = {}
        for e in owned["elfs"]:
            base = os.path.basename(e["rel"])
            owner = next((o for prefix, o in OWNER if base.startswith(prefix)), None)
            if owner is None:
                continue
            for comp, needle in EMBED.items():
                if embeds(e["path"], needle):
                    pairs.setdefault(f"{owner}/{comp}", set()).add(base)
        for key in sorted(pairs):
            owner, comp = key.split("/")
            dirs = (f"share/doc/{owner}/", f"share/doc/amdrocm-{owner}/")
            hits = [r for r in lfiles if r.startswith(dirs) and covers(r, texts[r], comp)]
            elsewhere = [r for r in lfiles if covers(r, texts[r], comp) and not r.startswith(dirs)]
            rec(f"license.bundled::{key}", "pass" if hits else "fail",
                f"{comp} embedded in {', '.join(sorted(pairs[key]))}; license at {hits[0]}" if hits else
                f"{comp} embedded in {', '.join(sorted(pairs[key]))} but no {comp} license under "
                f"share/doc/{owner}/" + (f" (only at {', '.join(elsewhere[:2])})" if elsewhere else ""),
                log=log_file)

        asan = sorted({r.split("/")[2] for r in entries if re.match(r"^share/doc/[^/]+-asan(/|$)", r)})
        asan_libs = [r for r in entries if re.search(r"(^|/)lib/asan/|[-_]asan\.so", r)]
        if asan and not asan_libs:
            rec("license::no-asan-doc-dirs", "fail",
                f"ASan doc folders shipped without ASan libraries: {', '.join(asan)}", log=log_file)
        else:
            rec("license::no-asan-doc-dirs", "pass", "no stray *-asan doc folders", log=log_file)

        docs = [r for r, k in entries.items() if k == "file" and (
            re.match(r"^(README|INSTALL)[^/]*$", r, re.I) or
            re.match(r"^share/doc/(vision-pack|amdrocm-vision)[^/]*/(README|INSTALL|USAGE)[^/]*$", r, re.I))]
        good = [r for r in docs if "PYTHONPATH" in read_text(os.path.join(ROCM, r))]
        rec("docs::install-usage", "pass" if good else "fail",
            f"install/usage doc: {good[0]}" if good else
            "no install/usage document for the tarball (where to extract, PYTHONPATH, Python 3.12 only, numpy)"
            + (f"; found without PYTHONPATH guidance: {', '.join(docs)}" if docs else ""), log=log_file)
    print(rec.counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
