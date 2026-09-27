#!/usr/bin/env bash
# Resolve (pull or build) the container image for a suite.
#
#   ensure_image.sh --kind test|media|extended [--family gfx120X-all] [--github]
#
# Order of preference:
#   1. $VP_IMAGE_<KIND> (e.g. a repo variable), which must be digest-pinned;
#   2. docker/images.lock (digest-pinned GHCR images published by image.yml);
#   3. a local build from docker/, tagged vp-<kind>:<hash of docker/>, so an
#      unchanged Dockerfile is built once and reused. The extended image is
#      always built locally (per GPU family: its torch wheels are per family).
# Prints the image reference; --github also writes image=<ref> to
# $GITHUB_OUTPUT. Builds are serialised with a lock under $VP_IMAGE_CACHE.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kind=test family="" github=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --kind) kind="$2"; shift 2 ;;
    --family) family="$2"; shift 2 ;;
    --github) github=1; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
case "${kind}" in test|media|extended) ;; *) echo "--kind must be test, media or extended" >&2; exit 2 ;; esac

log() { printf '[ensure-image] %s\n' "$*" >&2; }
die() { printf '::error::ensure-image: %s\n' "$*" >&2; exit 1; }

emit() {
  [[ "${github}" == 1 && -n "${GITHUB_OUTPUT:-}" ]] && echo "image=$1" >>"${GITHUB_OUTPUT}"
  printf '%s\n' "$1"
}

pull() {
  local ref="$1" i
  [[ "${ref}" == *@sha256:* ]] || die "${ref} is not pinned by digest"
  if docker image inspect "${ref}" >/dev/null 2>&1; then return 0; fi
  for i in 1 2 3; do
    docker pull --quiet "${ref}" >&2 && return 0
    log "pull ${ref} failed (attempt ${i}); retrying"
    sleep $((i * 15))
  done
  die "could not pull ${ref}"
}

var="VP_IMAGE_${kind^^}"
ref="${!var:-}"
if [[ -z "${ref}" && "${kind}" != extended && -f "${REPO}/docker/images.lock" ]]; then
  ref="$(awk -F= -v k="${kind}" '$1 == k { sub(/^[^=]*=/, ""); gsub(/[[:space:]]/, ""); print; exit }' \
    "${REPO}/docker/images.lock")"
fi
if [[ -n "${ref}" ]]; then
  log "${kind}: using pinned ${ref}"
  pull "${ref}"
  emit "${ref}"
  exit 0
fi

# Local build. The tag hashes everything the build reads from docker/.
hash="$(cd "${REPO}/docker" && find . -type f ! -name images.lock -print0 | sort -z \
  | xargs -0 sha256sum | sha256sum | cut -c1-16)"
build_args=()
case "${kind}" in
  test) file=Dockerfile.test; tag="vp-test:${hash}" ;;
  media) file=Dockerfile.test-media; tag="vp-media:${hash}" ;;
  extended)
    file=Dockerfile.test-extended
    family="${family:-${VP_SDK_FAMILY:-gfx120X-all}}"
    family="${family%-tests}"
    tag="vp-extended-${family,,}:${hash}"
    build_args+=(--build-arg "AMDGPU_FAMILY=${family}")
    ;;
esac
if [[ "${kind}" != test ]]; then
  base="$("$0" --kind test)"
  build_args+=(--build-arg "BASE_TEST=${base}")
fi

if docker image inspect "${tag}" >/dev/null 2>&1; then
  log "${kind}: reusing local ${tag}"
  emit "${tag}"
  exit 0
fi

lockdir="${VP_IMAGE_CACHE:-/srv/vp-ci/cache/images}"
mkdir -p "${lockdir}" 2>/dev/null || lockdir="${TMPDIR:-/tmp}"
exec {lockfd}>"${lockdir}/build-${tag%%:*}.lock"
flock -w 5400 "${lockfd}" || die "timed out waiting for another build of ${tag}"
if ! docker image inspect "${tag}" >/dev/null 2>&1; then
  log "${kind}: building ${tag} from docker/${file}"
  docker build --file "${REPO}/docker/${file}" --tag "${tag}" \
    --label "vp-ci.kind=${kind}" --label "vp-ci.content-hash=${hash}" \
    ${build_args[@]+"${build_args[@]}"} "${REPO}/docker" >&2 \
    || die "docker build of ${tag} failed"
fi
flock -u "${lockfd}"
emit "${tag}"
