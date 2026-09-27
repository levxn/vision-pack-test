#!/usr/bin/env bash
# Clean-system install smoke test for the RPMs (runs as root in a bare
# rockylinux:9 container; any disposable EL9 works).
#
#   suites/packaging/install_smoke_rpm.sh --rpms <dir> --out <dir> \
#       [--therock-date YYYYMMDD] [--plan-only]
#
# Same flow as install_smoke_deb.sh: decoy host libraries, TheRock's nightly
# RPM repository (install-rpm::depends::<name>), dnf install of every RPM
# (install-rpm::install.therock), fallback rpm -i --nodeps (with the matching
# TheRock library packages when possible: mode nodeps+therock-libs, else
# nodeps), then isolation, .pth (EL9 python3 is 3.9; the modules are cp312, so
# python3.12 is checked too), imports, ldd, rpm -V and rpm -e leftovers.
#
# Environment: VP_THEROCK_RPM_REPO, VP_THEROCK_BASE, VP_THEROCK_DISTRO (default
# rhel9), VP_THEROCK_DATE, VP_INSTALL_THEROCK_LIBS (default 1),
# VP_ALLOW_SYSTEM_INSTALL=1 to run outside a container/hosted runner.
set -uo pipefail
PK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PK_DIR}/lib/common.sh"

rpms="" out="" date="${VP_THEROCK_DATE:-}" plan_only=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rpms) rpms="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --therock-date) date="$2"; shift 2 ;;
    --plan-only) plan_only=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) pk_die "unknown argument $1" ;;
  esac
done
[[ -n "${rpms}" ]] || pk_die "--rpms is required"
rpms="$(pk_abs_dir "${rpms}")" || pk_die "no such directory: ${rpms}"
mapfile -t RPMS < <(find "${rpms}" -maxdepth 1 -name 'amdrocm-*.rpm' | sort)
[[ ${#RPMS[@]} -gt 0 ]] || pk_die "no amdrocm-*.rpm in ${rpms}"
if [[ "${plan_only}" == 0 ]]; then
  [[ "$(id -u)" == 0 ]] || pk_die "must run as root (use --plan-only for the read-only checks)"
  pk_disposable || pk_die "refusing to install packages on a non-disposable host; run it in a container or set VP_ALLOW_SYSTEM_INSTALL=1"
fi
G=install-rpm
distro="${VP_THEROCK_DISTRO:-rhel9}"
DNF=(dnf -y -q --setopt=retries=5 --setopt=timeout=60 --setopt=install_weak_deps=False)

if [[ "${plan_only}" == 0 ]]; then
  mkdir -p "${out}"
  if ! pk_retry 3 "${DNF[@]}" install jq python3 binutils cpio findutils file which >"${out}/prereqs.log" 2>&1; then
    tail -20 "${out}/prereqs.log" >&2
    pk_die "cannot install the prerequisites (see ${out}/prereqs.log)"
  fi
fi
pk_init packaging "${out}"
[[ -f "${VP_OUT}/prereqs.log" ]] && mv -f "${VP_OUT}/prereqs.log" "${VP_OUT}/logs/prereqs.log"
if ! vp_require_cmd "${G}::tools" rpm curl python3; then vp_finish; exit 0; fi

names=()
for f in "${RPMS[@]}"; do names+=("$(rpm -qp --nosignature --qf '%{NAME}' "${f}")"); done
vp_result "${G}::plan" pass "${#RPMS[@]} packages: ${names[*]}"

planted=0
if [[ "${plan_only}" == 0 ]]; then
  for p in libjpeg-turbo turbojpeg protobuf protobuf-lite lmdb-libs libsndfile; do
    "${DNF[@]}" install "${p}" >>"${VP_OUT}/logs/decoys.log" 2>&1 || echo "decoy ${p} unavailable" >>"${VP_OUT}/logs/decoys.log"
  done
  planted="$(pk_count_decoys)"
  if [[ "${planted}" -gt 0 ]]; then
    vp_result "${G}::decoys" pass "${planted} stock SONAME(s) on the default loader path" 0 "${VP_OUT}/logs/decoys.log"
  else
    vp_result "${G}::decoys" fail "no decoy package could be installed" 0 "${VP_OUT}/logs/decoys.log"
  fi
fi

repo="" index="${VP_WORK}/therock-primary.xml.gz" stubs="${VP_WORK}/unresolved.tsv"
if repo="$(pk_therock_repo "${distro}" "${date}" rpm)" && [[ -n "${repo}" ]] \
   && pk_fetch "${repo}/repodata/repomd.xml" "${VP_WORK}/repomd.xml" 120 \
   && primary="$(grep -oE 'repodata/[^"]*primary\.xml[^"]*' "${VP_WORK}/repomd.xml" | head -1)" \
   && [[ "${primary}" == *.gz ]] && pk_fetch "${repo}/${primary}" "${index}" 300; then
  vp_result "${G}::therock.repo" pass "baseurl=${repo} gpgcheck=0"
else
  vp_result "${G}::therock.repo" blocked "TheRock nightly repo unreachable or without gzip primary.xml (${repo:-${PK_THEROCK_BASE}/${distro}/})"
  repo="" index=""
fi
pk_py depends --pkg-dir "${rpms}" --format rpm --index "${index}" --group "${G}" --stubs-out "${stubs}" \
  >"${VP_OUT}/logs/depends.log" 2>&1 || vp_result "${G}::depends" error "pkgcheck.py depends failed" 0 \
  "${VP_OUT}/logs/depends.log"
if [[ "${plan_only}" == 1 ]]; then
  cat "${VP_OUT}/logs/depends.log"
  vp_finish
  exit 0
fi

mode=""
ilog="${VP_OUT}/logs/install-therock.log"
if [[ -n "${repo}" ]]; then
  printf '[therock-nightly]\nname=TheRock ROCm nightly\nbaseurl=%s\nenabled=1\ngpgcheck=0\nrepo_gpgcheck=0\n' "${repo}" \
    >/etc/yum.repos.d/therock-nightly.repo
  if "${DNF[@]}" install "${RPMS[@]}" >"${ilog}" 2>&1; then
    mode=therock
    vp_result "${G}::install.therock" pass "all Requires resolved from ${repo}" 0 "${ilog}"
  else
    vp_result "${G}::install.therock" fail "dnf cannot resolve against TheRock's repo: $(grep -E 'nothing provides|conflicts|Problem|Error' "${ilog}" | head -8 | tr -s ' \n' ' ')" 0 "${ilog}"
  fi
else
  vp_result "${G}::install.therock" blocked "TheRock repo unreachable" 0
fi

if [[ -z "${mode}" ]]; then
  ilog="${VP_OUT}/logs/install-fallback.log"
  mode=nodeps
  libs=()
  if [[ -n "${repo}" && "${VP_INSTALL_THEROCK_LIBS:-1}" == 1 && -s "${stubs}" ]]; then
    while IFS=$'\t' read -r n v; do
      [[ "${n}" == *.so* ]] && continue
      mm="$(sed -E 's/^([0-9]+\.[0-9]+).*/\1/' <<<"${v}")"
      [[ "${n}" == hip-runtime-amd ]] && n=amdrocm-runtime
      libs+=("${n}${mm}")
    done <"${stubs}"
    if [[ ${#libs[@]} -gt 0 ]] && "${DNF[@]}" install "${libs[@]}" >"${ilog}" 2>&1; then
      mode="nodeps+therock-libs"
    fi
  fi
  rpm -ivh --nodeps "${RPMS[@]}" >>"${ilog}" 2>&1
fi
not_ok=""
for n in "${names[@]}"; do rpm -q "${n}" >/dev/null 2>&1 || not_ok+="${n} "; done
if [[ -z "${not_ok}" ]]; then
  vp_result "${G}::install" pass "mode=${mode}: ${#RPMS[@]} packages installed" 0 "${ilog}"
else
  vp_result "${G}::install" fail "mode=${mode}: not installed: ${not_ok}" 0 "${ilog}"
fi

vlog="${VP_OUT}/logs/rpm-verify.log"
rpm -V "${names[@]}" >"${vlog}" 2>&1
if grep -qvE '^\s*$' "${vlog}"; then
  vp_result "${G}::rpm.verify" fail "$(head -5 "${vlog}" | tr '\n' ' ')" 0 "${vlog}"
else
  vp_result "${G}::rpm.verify" pass "installed files match the RPM database" 0 "${vlog}"
fi
pk_isolation_checks "${G}" "${planted}"

pth=/usr/lib/python3/dist-packages/amdrocm-vision.pth
site_pth="$(python3 -c 'import site,os; print(next((os.path.join(d,"amdrocm-vision.pth") for d in site.getsitepackages() if os.path.exists(os.path.join(d,"amdrocm-vision.pth"))), ""))')"
if [[ -n "${site_pth}" ]]; then
  vp_result "${G}::pth.shipped" pass "%post wrote ${site_pth} (payload copy at ${pth} is not a site dir on EL)"
else
  vp_result "${G}::pth.shipped" fail "no amdrocm-vision.pth in any python3 site-packages; %post did not register it"
fi
syspath_ok() { env -u PYTHONPATH "$1" -c 'import sys; sys.exit(0 if any(p.rstrip("/") == "/opt/rocm/lib" for p in sys.path) else 1)'; }
if syspath_ok python3; then
  vp_result "${G}::pth.syspath" pass "$(python3 -V 2>&1) has /opt/rocm/lib on sys.path"
else
  vp_result "${G}::pth.syspath" fail "/opt/rocm/lib not on sys.path of $(python3 -V 2>&1)"
fi
py312=""
if pk_retry 2 "${DNF[@]}" install python3.12 >>"${VP_OUT}/logs/python312.log" 2>&1; then py312="$(command -v python3.12)"; fi
if [[ -z "${py312}" ]]; then
  vp_blocked "${G}::pth.python3.12" "python3.12 not installable from the EL9 repos"
  for mod in "${PK_PY_MODULES[@]}"; do vp_blocked "${G}::import::${mod}" "python3.12 unavailable (modules are cp312-only)"; done
else
  if syspath_ok "${py312}"; then
    vp_result "${G}::pth.python3.12" pass "python3.12 has /opt/rocm/lib on sys.path"
  else
    vp_result "${G}::pth.python3.12" fail "python3.12 (the only interpreter the cp312 modules load in) does not get /opt/rocm/lib: %post registered the path for $(python3 -V 2>&1) only"
  fi
  pk_import_checks "${G}" "${py312}" "${mode}"
fi
pk_ldd_checks "${G}" "${mode}"

rlog="${VP_OUT}/logs/remove.log"
rpm -e --nodeps "${names[@]}" >"${rlog}" 2>&1
left=""
for f in "${RPMS[@]}"; do
  while IFS= read -r p; do
    [[ -e "${p}" || -L "${p}" ]] && [[ ! -d "${p}" || -L "${p}" ]] && left+="${p} "
  done < <(rpm -qpl --nosignature "${f}" 2>/dev/null)
done
[[ -n "${site_pth}" && -e "${site_pth}" ]] && left+="${site_pth} (written by %post) "
if [[ -z "${left}" ]]; then
  vp_result "${G}::remove.clean" pass "rpm -e removed every packaged file" 0 "${rlog}"
else
  vp_result "${G}::remove.clean" fail "left behind: ${left:0:1500}" 0 "${rlog}"
fi
vp_finish
exit 0
