#!/usr/bin/env bash
# Clean-system install smoke test for the DEBs (runs as root in a bare
# ubuntu:24.04 container; any disposable Ubuntu 24.04 works).
#
#   suites/packaging/install_smoke_deb.sh --debs <dir> --out <dir> \
#       [--therock-date YYYYMMDD] [--plan-only]
#
# 1. Plants host copies of the stock libraries the bundled sysdeps were
#    renamed away from (decoys), before anything from vision-pack.
# 2. Adds TheRock's nightly APT repository and checks every external Depends
#    against its index (install-deb::depends::<name>).
# 3. apt install ./amdrocm-vision*.deb against the real repository
#    (install-deb::install.therock). If that cannot resolve, falls back to
#    equivs stubs for the unresolvable ROCm Depends, installing the matching
#    TheRock library packages as well when possible (mode stubs+therock-libs,
#    else stubs), and finally to dpkg -i --force-depends. install-deb::install
#    says which mode was used.
# 4. Ports upstream package.yml smoke-test: isolated SONAMEs, decoys not
#    shadowing, the .pth putting /opt/rocm/lib on sys.path, then imports,
#    ldd, dpkg --verify and a clean purge.
#
# --plan-only needs no root and changes nothing: package list, Depends parsing
# and the repository checks only.
#
# Environment: VP_THEROCK_DEB_REPO (full repo URL override), VP_THEROCK_BASE,
# VP_THEROCK_DISTRO (default ubuntu2404), VP_THEROCK_DATE, VP_INSTALL_THEROCK_LIBS
# (default 1), VP_ALLOW_SYSTEM_INSTALL=1 to run outside a container/hosted runner.
set -uo pipefail
PK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PK_DIR}/lib/common.sh"

debs="" out="" date="${VP_THEROCK_DATE:-}" plan_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --debs) debs="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --therock-date) date="$2"; shift 2 ;;
    --plan-only) plan_only=1; shift ;;
    -h|--help) sed -n '2,29p' "$0"; exit 0 ;;
    *) pk_die "unknown argument $1" ;;
  esac
done
[[ -n "${debs}" ]] || pk_die "--debs is required"
debs="$(pk_abs_dir "${debs}")" || pk_die "no such directory: ${debs}"
mapfile -t DEBS < <(find "${debs}" -maxdepth 1 -name 'amdrocm-vision*.deb' | sort)
[[ ${#DEBS[@]} -gt 0 ]] || pk_die "no amdrocm-vision*.deb in ${debs}"
if [[ "${plan_only}" == 0 ]]; then
  [[ "$(id -u)" == 0 ]] || pk_die "must run as root (use --plan-only for the read-only checks)"
  pk_disposable || pk_die "refusing to install packages on a non-disposable host; run it in a container or set VP_ALLOW_SYSTEM_INSTALL=1"
fi
G=install-deb
distro="${VP_THEROCK_DISTRO:-ubuntu2404}"
export DEBIAN_FRONTEND=noninteractive
APT=(apt-get -y -q -o Acquire::Retries=5 -o Acquire::http::Timeout=60 -o Dpkg::Use-Pty=0)

if [[ "${plan_only}" == 0 ]]; then
  # vp_result needs jq and the checks need python3, so install them first.
  mkdir -p "${out}"
  if ! { pk_retry 3 "${APT[@]}" update && pk_retry 3 "${APT[@]}" install --no-install-recommends \
         ca-certificates curl jq python3 binutils libc-bin dpkg-dev file; } >"${out}/prereqs.log" 2>&1; then
    tail -20 "${out}/prereqs.log" >&2
    pk_die "cannot install the prerequisites (see ${out}/prereqs.log)"
  fi
fi
pk_init packaging "${out}"
[[ -f "${VP_OUT}/prereqs.log" ]] && mv -f "${VP_OUT}/prereqs.log" "${VP_OUT}/logs/prereqs.log"
if ! vp_require_cmd "${G}::tools" dpkg-deb curl python3; then vp_finish; exit 0; fi

names="$(for f in "${DEBS[@]}"; do dpkg-deb -f "${f}" Package; done | sort | tr '\n' ' ')"
vp_result "${G}::plan" pass "${#DEBS[@]} packages: ${names}"

# --- decoys (before any vision package) ------------------------------------
planted=0
if [[ "${plan_only}" == 0 ]]; then
  for p in libturbojpeg libprotobuf32t64 libprotobuf-lite32t64 liblmdb0 libsndfile1 libjpeg-turbo8; do
    "${APT[@]}" install --no-install-recommends "${p}" >>"${VP_OUT}/logs/decoys.log" 2>&1 \
      || echo "decoy ${p} unavailable" >>"${VP_OUT}/logs/decoys.log"
  done
  planted="$(pk_count_decoys)"
  if [[ "${planted}" -gt 0 ]]; then
    vp_result "${G}::decoys" pass "${planted} stock SONAME(s) on the default loader path" 0 "${VP_OUT}/logs/decoys.log"
  else
    vp_result "${G}::decoys" fail "no decoy package could be installed" 0 "${VP_OUT}/logs/decoys.log"
  fi
fi

# --- TheRock repository and Depends resolution -------------------------------
repo="" index="${VP_WORK}/therock-Packages" stubs="${VP_WORK}/stubs.tsv"
if repo="$(pk_therock_repo "${distro}" "${date}" deb)" && [[ -n "${repo}" ]] \
   && pk_fetch "${repo}/dists/stable/main/binary-amd64/Packages" "${index}" 300; then
  vp_result "${G}::therock.repo" pass "deb [trusted=yes] ${repo} stable main ($(grep -c '^Package:' "${index}") packages)"
else
  vp_result "${G}::therock.repo" blocked "TheRock nightly repo unreachable (${repo:-${PK_THEROCK_BASE}/${distro}/})"
  repo="" index=""
fi
pk_py depends --pkg-dir "${debs}" --format deb --index "${index}" --group "${G}" --stubs-out "${stubs}" \
  >"${VP_OUT}/logs/depends.log" 2>&1 || vp_result "${G}::depends" error "pkgcheck.py depends failed" 0 \
  "${VP_OUT}/logs/depends.log"
if [[ "${plan_only}" == 1 ]]; then
  cat "${VP_OUT}/logs/depends.log"
  vp_finish
  exit 0
fi

# --- install ------------------------------------------------------------------
mode=""
ilog="${VP_OUT}/logs/install-therock.log"
if [[ -n "${repo}" ]]; then
  echo "deb [trusted=yes] ${repo} stable main" >/etc/apt/sources.list.d/therock-nightly.list
  pk_retry 3 "${APT[@]}" update >"${ilog}" 2>&1
  if "${APT[@]}" install --no-install-recommends "${DEBS[@]}" >>"${ilog}" 2>&1; then
    mode=therock
    vp_result "${G}::install.therock" pass "all Depends resolved from ${repo}" 0 "${ilog}"
  else
    vp_result "${G}::install.therock" fail "apt cannot resolve against TheRock's repo: $(grep -E 'Depends:|but it is not|unmet|E: ' "${ilog}" | head -8 | tr -s ' \n' ' ')" 0 "${ilog}"
  fi
else
  vp_result "${G}::install.therock" blocked "TheRock repo unreachable" 0
fi

if [[ -z "${mode}" ]]; then
  slog="${VP_OUT}/logs/install-fallback.log"
  : >"${slog}"
  stubdir="${VP_WORK}/stubs"
  mkdir -p "${stubdir}"
  have_equivs=0
  pk_retry 2 "${APT[@]}" install --no-install-recommends equivs >>"${slog}" 2>&1 && have_equivs=1
  libs=()
  if [[ -n "${repo}" && "${VP_INSTALL_THEROCK_LIBS:-1}" == 1 && -s "${stubs}" ]]; then
    # The real libraries behind the unversioned names (amdrocm-rpp ->
    # amdrocm-rpp10.2; hip-runtime-amd -> amdrocm-runtime10.2).
    while IFS=$'\t' read -r n v; do
      mm="$(sed -E 's/^([0-9]+\.[0-9]+).*/\1/' <<<"${v}")"
      [[ "${n}" == hip-runtime-amd ]] && n=amdrocm-runtime
      grep -qx "Package: ${n}${mm}" "${index}" && libs+=("${n}${mm}")
    done <"${stubs}"
  fi
  if [[ "${have_equivs}" == 1 ]]; then
    ok=1
    while IFS=$'\t' read -r n v; do
      [[ -n "${n}" ]] || continue
      printf 'Section: misc\nPriority: optional\nStandards-Version: 3.9.2\nPackage: %s\nVersion: %s\nArchitecture: all\nDescription: vision-pack-test stub for %s\n stub\n' \
        "${n}" "${v}" "${n}" >"${stubdir}/${n}.control"
      (cd "${stubdir}" && equivs-build "${n}.control") >>"${slog}" 2>&1 || ok=0
    done <"${stubs}"
    if [[ "${ok}" == 1 ]]; then
      mode=stubs
      if [[ ${#libs[@]} -gt 0 ]] && "${APT[@]}" install --no-install-recommends "${libs[@]}" >>"${slog}" 2>&1; then
        mode="stubs+therock-libs"
      fi
      mapfile -t STUBDEBS < <(find "${stubdir}" -name '*.deb')
      if { [[ ${#STUBDEBS[@]} -eq 0 ]] || dpkg -i "${STUBDEBS[@]}"; } >>"${slog}" 2>&1 \
         && "${APT[@]}" install --no-install-recommends "${DEBS[@]}" >>"${slog}" 2>&1; then
        :
      else
        mode=""
      fi
    fi
  fi
  if [[ -z "${mode}" ]]; then
    dpkg -i --force-depends "${DEBS[@]}" >>"${slog}" 2>&1
    mode=force-depends
  fi
  ilog="${slog}"
fi
not_ok=""
for f in "${DEBS[@]}"; do
  p="$(dpkg-deb -f "${f}" Package)"
  dpkg-query -W -f='${db:Status-Abbrev}' "${p}" 2>/dev/null | grep -q '^ii' || not_ok+="${p} "
done
if [[ -z "${not_ok}" ]]; then
  vp_result "${G}::install" pass "mode=${mode}: ${#DEBS[@]} packages installed ($(sed 's/\t/ /g' "${stubs}" 2>/dev/null | tr '\n' ',' ))" 0 "${ilog}"
else
  vp_result "${G}::install" fail "mode=${mode}: not installed/configured: ${not_ok}" 0 "${ilog}"
fi

# --- checks (upstream smoke-test and more) ------------------------------------
pkgs=()
for f in "${DEBS[@]}"; do pkgs+=("$(dpkg-deb -f "${f}" Package)"); done
vlog="${VP_OUT}/logs/dpkg-verify.log"
dpkg --verify "${pkgs[@]}" >"${vlog}" 2>&1
if [[ -s "${vlog}" ]]; then
  vp_result "${G}::dpkg.verify" fail "$(head -5 "${vlog}" | tr '\n' ' ')" 0 "${vlog}"
else
  vp_result "${G}::dpkg.verify" pass "installed files match the md5sums" 0 "${vlog}"
fi
pk_isolation_checks "${G}" "${planted}"

pth=/usr/lib/python3/dist-packages/amdrocm-vision.pth
if [[ -f "${pth}" && "$(tr -d '[:space:]' <"${pth}")" == /opt/rocm/lib ]]; then
  vp_result "${G}::pth.shipped" pass "${pth}: /opt/rocm/lib"
else
  vp_result "${G}::pth.shipped" fail "${pth} missing or not '/opt/rocm/lib'"
fi
if env -u PYTHONPATH python3 -c 'import sys; sys.exit(0 if any(p.rstrip("/") == "/opt/rocm/lib" for p in sys.path) else 1)'; then
  vp_result "${G}::pth.syspath" pass "$(python3 -V 2>&1) has /opt/rocm/lib on sys.path without PYTHONPATH"
else
  vp_result "${G}::pth.syspath" fail "/opt/rocm/lib not on sys.path of $(python3 -V 2>&1): the .pth is not honoured"
fi
pk_import_checks "${G}" python3 "${mode}"
pk_ldd_checks "${G}" "${mode}"

# --- removal leaves nothing behind -----------------------------------------------
rlog="${VP_OUT}/logs/remove.log"
if [[ "${mode}" == force-depends ]]; then
  dpkg --purge --force-depends "${pkgs[@]}" >"${rlog}" 2>&1
else
  "${APT[@]}" purge "${pkgs[@]}" >"${rlog}" 2>&1
fi
left=""
for f in "${DEBS[@]}"; do
  while IFS= read -r p; do
    [[ -e "${p}" || -L "${p}" ]] && [[ ! -d "${p}" || -L "${p}" ]] && left+="${p} "
  done < <(dpkg-deb -c "${f}" | awk '$1 !~ /^d/ {sub(/^\./, "", $6); print $6}')
done
if [[ -z "${left}" ]]; then
  vp_result "${G}::remove.clean" pass "purge removed every packaged file" 0 "${rlog}"
else
  vp_result "${G}::remove.clean" fail "left behind: ${left:0:1500}" 0 "${rlog}"
fi
vp_finish
exit 0
