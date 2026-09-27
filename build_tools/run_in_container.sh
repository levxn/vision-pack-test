#!/usr/bin/env bash
# Run one suite inside the test container on the self-hosted runner.
#
#   run_in_container.sh --suite rocal --prefix /srv/vp-ci/runs/<run>/rocm --out <dir> \
#       [--entrypoint suites/rocal/run.sh] [--image vp-test:<tag>] [--data <dir>] \
#       [--cache <dir>] [--tier comprehensive] [--gfx gfx1201] [--render-minor 128] \
#       [--gpu-access chosen|all|none] [--manifest <file>] [--dist-tarball <file>] \
#       [--env KEY=VALUE]... [-- command...]
#
# --dist-tarball mounts the vision-pack dist tarball read-only and exports
# VP_DIST_TARBALL (loader-audit compares it with the prefix; sdk-consumer
# tests it standalone).
#
# The container sees only the chosen GPU (its render node plus /dev/kfd), runs
# as root like TheRock's CI, mounts the ROCm prefix, dataset and repository
# read-only, and writes only to the output directory and the cache. Afterwards
# the output directory is chowned back to the invoking user.
#   --gpu-access all   also exposes GPUs the build does not target
#                      (VP_UNSUPPORTED_GPUS), for the robustness negatives
#   --gpu-access none  exposes no GPU device at all (--no-gpu is an alias)
# With VP_NO_CONTAINER=1 the suite runs directly on the host instead (see
# local_run.sh).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
suite="" prefix="" out="" entry="" image="${VP_IMAGE:-}" data="${VP_DATA:-}" tier="${VP_TIER:-comprehensive}"
gfx="${VP_GFX:-}" minor="${VP_RENDER_MINOR:-}" access=chosen manifest="" cache="${VP_CACHE:-}"
dist="${VP_DIST_TARBALL:-}"
extra_env=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite) suite="$2"; shift 2 ;;
    --prefix) prefix="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --entrypoint) entry="$2"; shift 2 ;;
    --image) image="$2"; shift 2 ;;
    --data) data="$2"; shift 2 ;;
    --cache) cache="$2"; shift 2 ;;
    --tier) tier="$2"; shift 2 ;;
    --gfx) gfx="$2"; shift 2 ;;
    --render-minor) minor="$2"; shift 2 ;;
    --gpu-access) access="$2"; shift 2 ;;
    --no-gpu) access=none; shift ;;
    --manifest) manifest="$2"; shift 2 ;;
    --dist-tarball) dist="$2"; shift 2 ;;
    --env) extra_env+=("$2"); shift 2 ;;
    --) shift; break ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -n "${suite}" && -n "${prefix}" && -n "${out}" ]] || { echo "--suite, --prefix and --out are required" >&2; exit 2; }
case "${access}" in chosen|all|none) ;; *) echo "--gpu-access must be chosen, all or none" >&2; exit 2 ;; esac
if [[ -n "${dist}" ]]; then
  [[ -f "${dist}" ]] || { echo "--dist-tarball ${dist} does not exist" >&2; exit 2; }
  dist="$(readlink -f "${dist}")"
fi
entry="${entry:-suites/${suite}/run.sh}"
mkdir -p "${out}"
out="$(cd "${out}" && pwd)"
prefix="$(cd "${prefix}" && pwd)"
if [[ -n "${cache}" ]]; then
  mkdir -p "${cache}"
  cache="$(cd "${cache}" && pwd)"
fi

if [[ "${VP_NO_CONTAINER:-0}" == 1 ]]; then
  exec env ROCM_PATH="${prefix}" VP_OUT="${out}" VP_REPO="${REPO}" VP_DATA="${data}" VP_TIER="${tier}" \
    VP_GFX="${gfx}" VP_MANIFEST="${manifest:-${prefix}/share/vision-pack/vision-pack-manifest.json}" \
    VP_VISION_PACK_SRC="${REPO}/vision-pack" VP_GPU_ACCESS="${access}" VP_DIST_TARBALL="${dist}" \
    VP_CACHE="${cache:-/tmp/vp-ci-cache-$(id -u)}" ${extra_env[@]+"${extra_env[@]}"} \
    bash "${REPO}/${entry}" "$@"
fi

[[ -n "${image}" ]] || { echo "--image (or VP_IMAGE) is required" >&2; exit 2; }

# Container paths. The prefix deliberately is not /opt/rocm, so anything that
# ignores ROCM_PATH and falls back to /opt/rocm fails loudly instead of
# silently working.
C_PREFIX=/opt/vp/rocm
C_REPO=/opt/vp/repo
C_DATA=/opt/vp/data
C_OUT=/opt/vp/out

args=(
  run --rm --init
  --user 0:0
  --ipc=host
  --security-opt seccomp=unconfined
  --ulimit memlock=-1:-1 --ulimit nofile=1048576:1048576 --ulimit core=0
  --label "vp-ci.run=${GITHUB_RUN_ID:-local}"
  --label "vp-ci.suite=${suite}"
  --name "vp-${suite}-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$$"
  -v "${prefix}:${C_PREFIX}:ro"
  -v "${REPO}:${C_REPO}:ro"
  -v "${out}:${C_OUT}"
  -w "${C_OUT}"
  -e "ROCM_PATH=${C_PREFIX}"
  -e "VP_OUT=${C_OUT}"
  -e "VP_REPO=${C_REPO}"
  -e "VP_TIER=${tier}"
  -e "VP_GFX=${gfx}"
  -e "VP_SUITE_NAME=${suite}"
  -e "VP_VISION_PACK_SRC=${C_REPO}/vision-pack"
  -e "VP_UNSUPPORTED_GPUS=${VP_UNSUPPORTED_GPUS:-}"
  -e "VP_GPU_ACCESS=${access}"
  -e "VP_EXTENDED=${VP_EXTENDED:-0}"
  -e "VP_BUILD_JOBS=${VP_BUILD_JOBS:-$(nproc)}"
  -e "GITHUB_ACTIONS=${GITHUB_ACTIONS:-}"
)
if [[ -n "${manifest}" ]]; then
  args+=(-v "$(readlink -f "${manifest}"):/opt/vp/manifest.json:ro" -e "VP_MANIFEST=/opt/vp/manifest.json")
else
  args+=(-e "VP_MANIFEST=${C_PREFIX}/share/vision-pack/vision-pack-manifest.json")
fi
if [[ -n "${data}" && -d "${data}" ]]; then
  args+=(-v "$(readlink -f "${data}"):${C_DATA}:ro" -e "VP_DATA=${C_DATA}")
fi
if [[ -n "${cache}" ]]; then
  args+=(-v "${cache}:/opt/vp/cache" -e "VP_CACHE=/opt/vp/cache")
fi
if [[ -n "${dist}" ]]; then
  args+=(-v "${dist}:/opt/vp/dist/$(basename "${dist}"):ro" -e "VP_DIST_TARBALL=/opt/vp/dist/$(basename "${dist}")")
fi
if [[ "${access}" != none ]]; then
  [[ -e /dev/kfd ]] || { echo "::error::/dev/kfd missing on the runner" >&2; exit 3; }
  [[ -n "${minor}" ]] || { echo "::error::--render-minor is required for GPU suites" >&2; exit 2; }
  minors=("${minor}")
  if [[ "${access}" == all && -n "${VP_UNSUPPORTED_GPUS:-}" ]]; then
    IFS=, read -r -a unsupported <<<"${VP_UNSUPPORTED_GPUS}"
    for u in "${unsupported[@]}"; do
      IFS=: read -r _ m _ <<<"${u}"
      [[ -n "${m}" ]] && minors+=("${m}")
    done
  fi
  # Only the listed render nodes: other GPUs (e.g. an iGPU the build does not
  # target) stay invisible, so no *_VISIBLE_DEVICES variable is needed. ROCr
  # numbers the visible GPUs from 0 in KFD order inside the container.
  args+=(--device /dev/kfd --group-add "$(stat -c %g /dev/kfd)")
  for m in "${minors[@]}"; do
    node="/dev/dri/renderD${m}"
    [[ -e "${node}" ]] || { echo "::error::${node} does not exist" >&2; exit 3; }
    args+=(--device "${node}" --group-add "$(stat -c %g "${node}")")
  done
fi
for e in ${extra_env[@]+"${extra_env[@]}"}; do args+=(-e "${e}"); done

cmd=(bash "${C_REPO}/${entry}")
[[ $# -gt 0 ]] && cmd=("$@")

reclaim() {
  docker run --rm --network none -v "${out}:/w" "${image}" chown -R "$(id -u):$(id -g)" /w >/dev/null 2>&1 || true
}
trap reclaim EXIT

echo "run_in_container: suite=${suite} image=${image} gfx=${gfx:-none} render=${minor:-none} gpu_access=${access} tier=${tier}"
rc=0
docker "${args[@]}" "${image}" "${cmd[@]}" || rc=$?
exit "${rc}"
