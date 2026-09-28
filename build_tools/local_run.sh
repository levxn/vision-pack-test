#!/usr/bin/env bash
# Run a suite directly on this host (no Docker), against an existing
# ROCm + vision-pack prefix. Useful for developing suites and reproducing a
# nightly failure locally.
#
#   build_tools/local_run.sh --suite roccv --prefix /opt/rocm-nightly \
#       [--data /path/to/MIVisionX-data] [--tier standard] [--out ./out] \
#       [--manifest file.json] [--dist-tarball vision-pack-dist-*.tar.gz] \
#       [--extended] [--ci-parity] [--no-gpu]
#
# Output goes to <out>/<suite>/ (results.jsonl, junit/, logs/, perf/); the
# download cache (e.g. the OpenVX CTS clone) goes to $VP_CACHE, by default
# /tmp/vp-ci-cache-<uid>. The GPU is pinned with ROCR_VISIBLE_DEVICES because
# bare metal cannot hide the other render nodes the way the container
# launcher does.
#
# --no-gpu emulates a runner without a usable GPU (test.yml's test-nogpu job):
# empty VP_GFX, gpu_access none and ROCR_VISIBLE_DEVICES=-1. Only the suites
# with needs_gpu: false in suites/suites.yaml can run that way.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
suite="" prefix="" data="" tier="standard" out="${REPO}/out" manifest="" extended=0 parity=0 no_gpu=0
dist="${VP_DIST_TARBALL:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --suite) suite="$2"; shift 2 ;;
    --prefix) prefix="$2"; shift 2 ;;
    --data) data="$2"; shift 2 ;;
    --tier) tier="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --manifest) manifest="$2"; shift 2 ;;
    --dist-tarball) dist="$(readlink -f "$2")"; shift 2 ;;
    --extended) extended=1; shift ;;
    --ci-parity) parity=1; shift ;;
    --no-gpu) no_gpu=1; shift ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -n "${suite}" && -n "${prefix}" ]] || { echo "--suite and --prefix are required" >&2; exit 2; }
[[ -d "${prefix}/lib" ]] || { echo "${prefix} does not look like a ROCm prefix" >&2; exit 2; }
manifest="${manifest:-${prefix}/share/vision-pack/vision-pack-manifest.json}"
[[ "${out}" = /* ]] || out="$(pwd)/${out}"
cd "${REPO}"

# suites.yaml is read with awk (it keeps to "  name:" / "    key: value"
# lines), so local runs need no PyYAML.
suite_field() { # <key> <default>
  awk -v s="${suite}" -v k="$1" -v d="$2" '
    /^  [A-Za-z0-9_.-]+:[[:space:]]*$/ { cur = $1; sub(/:$/, "", cur); next }
    cur == s && $1 == k ":" { v = $0; sub(/^[^:]*:[[:space:]]*/, "", v); sub(/[[:space:]]+#.*$/, "", v); print v; found = 1; exit }
    END { if (!found) print d }' suites/suites.yaml
}
grep -qE "^  ${suite}:[[:space:]]*$" suites/suites.yaml || { echo "unknown suite ${suite}" >&2; exit 2; }
entry="$(suite_field entrypoint "suites/${suite}/run.sh")"
access="$(suite_field gpu_access chosen)"

if [[ "${no_gpu}" == 1 ]]; then
  if [[ "$(suite_field needs_gpu true)" != false ]]; then
    echo "local_run: ${suite} needs a GPU (no needs_gpu: false in suites/suites.yaml); without one CI reports it as ${suite}::infra::no-gpu" >&2
    exit 2
  fi
  access=none
  gpu_env="$(printf '%s\n' VP_GPU_PRESENT=0 "VP_NO_GPU_REASON=local_run.sh --no-gpu" VP_GFX= VP_RENDER_MINOR= \
    VP_GPU_INDEX= VP_SDK_FAMILY= VP_GPU_LIST= VP_UNSUPPORTED_GPUS=)"
else
  gpu_env="$("${REPO}/build_tools/detect_gpu.sh" --manifest "${manifest}" 2>/dev/null || true)"
fi
# Values may contain spaces (VP_NO_GPU_REASON), so no eval.
while IFS= read -r kv; do
  [[ "${kv}" =~ ^VP_[A-Z_]+= ]] && export "${kv}"
done <<<"${gpu_env}"

mkdir -p "${out}/${suite}"
export ROCM_PATH="${prefix}"
export VP_OUT="$(cd "${out}/${suite}" && pwd)"
export VP_REPO="${REPO}"
export VP_DATA="${data}"
export VP_TIER="${tier}"
export VP_MANIFEST="${manifest}"
export VP_VISION_PACK_SRC="${REPO}/vision-pack"
export VP_EXTENDED="${extended}"
export VP_CI_PARITY="${parity}"
export VP_NO_CONTAINER=1
export VP_GPU_ACCESS="${access}"
export VP_DIST_TARBALL="${dist}"
export VP_CACHE="${VP_CACHE:-/tmp/vp-ci-cache-$(id -u)}"
export VP_PY="${VP_PY:-/usr/bin/python3}"
# A clean PATH: no pyenv shims or other ROCm installs from the login shell.
export PATH="/usr/local/bin:/usr/bin:/bin"
unset ROCM_HOME HIP_PATH LD_LIBRARY_PATH PYTHONPATH HIP_VISIBLE_DEVICES ROCR_VISIBLE_DEVICES
# Bare metal cannot hide render nodes, so emulate the container's GPU access
# with ROCR_VISIBLE_DEVICES: an invalid index ("-1") leaves no GPU agent, like
# the no-GPU container; "all" leaves every GPU visible.
case "${access}" in
  chosen) [[ -n "${VP_GPU_INDEX:-}" ]] && export ROCR_VISIBLE_DEVICES="${VP_GPU_INDEX}" ;;
  none) export ROCR_VISIBLE_DEVICES=-1 ;;
esac

echo "local_run: suite=${suite} tier=${tier} gfx=${VP_GFX:-none} (index ${VP_GPU_INDEX:-?}) gpu_access=${access} out=${VP_OUT}"
rc=0
bash "${REPO}/${entry}" || rc=$?
echo "local_run: ${suite} exited ${rc}; results in ${VP_OUT}"
exit "${rc}"
