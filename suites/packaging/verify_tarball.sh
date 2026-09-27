#!/usr/bin/env bash
# Verify the dist tarball customers overlay onto a TheRock ROCm prefix:
# symlink chains, runvx exec bit, manifest schema (sha, version, rocm_sdk,
# gpu_targets, submodules), ELF RUNPATHs and build-ids, sysdeps completeness,
# licenses (H4), install docs (M3), and that every DEB payload file is in the
# tarball.
#
#   suites/packaging/verify_tarball.sh --tarball <file> [--debs <dir>] \
#       [--release-json <file>] [--expected-sha <sha>] --out <dir>
#
# Records packaging::tarball::<check> and packaging::tarball::runpath::<object>.
set -uo pipefail
PK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${PK_DIR}/lib/common.sh"

tarball="" debs="" release_json="" expected_sha="" out=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tarball) tarball="$2"; shift 2 ;;
    --debs) debs="$2"; shift 2 ;;
    --release-json) release_json="$2"; shift 2 ;;
    --expected-sha) expected_sha="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) pk_die "unknown argument $1" ;;
  esac
done
[[ -f "${tarball}" ]] || pk_die "--tarball must name an existing file"
tarball="$(cd "$(dirname "${tarball}")" && pwd)/$(basename "${tarball}")"
if [[ -n "${debs}" ]]; then debs="$(pk_abs_dir "${debs}")" || pk_die "no such directory: ${debs}"; fi
pk_init packaging "${out}"

if ! vp_require_cmd tarball::tools tar readelf; then vp_finish; exit 0; fi
root="${VP_WORK}/tarball-root"
args=(tarball --tarball "${tarball}" --root "${root}" --vp-src "${VP_VISION_PACK_SRC}")
[[ -n "${debs}" ]] && args+=(--debs "${debs}")
[[ -n "${release_json}" ]] && args+=(--release-json "${release_json}")
[[ -n "${expected_sha}" ]] && args+=(--expected-sha "${expected_sha}")
pk_py "${args[@]}" >"${VP_OUT}/logs/tarball-checks.log" 2>&1 \
  || vp_result tarball::checks error "pkgcheck.py tarball failed (see logs/tarball-checks.log)" 0 \
       "${VP_OUT}/logs/tarball-checks.log"
grep -E '^  (FAIL|ERROR)|^tarball:' "${VP_OUT}/logs/tarball-checks.log" || true
pk_cleanup_work "${root}"
vp_finish
exit 0
