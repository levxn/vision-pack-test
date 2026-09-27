#!/usr/bin/env bash
# robustness-nogpu (gpu_access: none): CPU paths with no GPU at all.
#
# In CI the container has no /dev/kfd and no render node. local_run.sh
# emulates that with ROCR_VISIBLE_DEVICES=-1, which leaves ROCr with zero GPU
# agents but keeps /dev/kfd and the render nodes openable; env::no-gpu-agents
# records which situation this run is in.
set -uo pipefail
source "${VP_REPO}/build_tools/lib/vp.sh"
vp_init robustness-nogpu

if ! vp_tier_ge comprehensive; then
  vp_skip "tier::below-comprehensive" "robustness-nogpu runs in the comprehensive tier and above"
  vp_finish
  exit 0
fi

CR="${VP_REPO}/suites/rocpydecode/checked_run.py"
PROBES="${VP_REPO}/suites/robustness/probes"
TINY="${ROCM_PATH}/share/rocal/test/data/images/AMD-tinyDataSet"
export TMPDIR="${VP_WORK}/tmp"
mkdir -p "${TMPDIR}"

have_py() { "${VP_PY}" -c "import $1" >/dev/null 2>&1; }

fresh_dir() {
  local d="${VP_WORK}/cwd/$1"
  rm -rf "${d}"
  mkdir -p "${d}"
  printf '%s' "${d}"
}

cr() {
  local id="$1"; shift
  "${VP_PY}" "${CR}" --id "${id}" --timeout 300 --error-rc 70 "$@"
}

# The premise: nothing may see a GPU. If this fails, every result below is suspect.
cr "env::no-gpu-agents" --timeout 120 -- "${VP_PY}" "${PROBES}/gpu_agents.py" --expect 0

# Imports of every shipped Python module (torch-only plugins need torch).
for m in rocal_pybind amd.rocal amd.rocal.fn amd.rocal.pipeline amd.rocal.types amd.rocal.readers \
         amd.rocal.decoders amd.rocal.plugin.generic rocpycv rocpydecode rocpyjpegdecode \
         pyRocVideoDecode.decoder pyRocVideoDecode.decodercpu pyRocVideoDecode.demuxer pyRocVideoDecode.types \
         pyRocJpegDecode.decoder pyRocJpegDecode.types; do
  vp_run "import::${m}" --timeout 120 -- "${VP_PY}" -c "import ${m}"
done
if have_py torch; then
  vp_run "import::amd.rocal.plugin.pytorch" --timeout 120 -- "${VP_PY}" -c "import amd.rocal.plugin.pytorch"
else
  vp_blocked "import::amd.rocal.plugin.pytorch" "torch is not installed"
fi

# MIVisionX: a CPU graph must work; asking for the GPU must fail cleanly.
cr "mivisionx::runvx-cpu-graph" --backend CPU --env AGO_DEFAULT_TARGET=CPU --cwd "$(fresh_dir mvx_cpu)" \
  -- "${VP_PY}" "${PROBES}/runvx_graph.py" --mode correct
cr "mivisionx::runvx-gpu-request-clean-error" --backend GPU --cwd "$(fresh_dir mvx_gpu)" \
  -- "${VP_PY}" "${PROBES}/runvx_graph.py" --mode error --affinity GPU

# rocCV: CPU operators on host tensors; Tensor.copy_to(CPU) still needs HIP (L5).
cr "roccv::cpu-flip" --backend CPU --cwd "$(fresh_dir roccv_cpu)" \
  -- "${VP_PY}" "${PROBES}/roccv_flip.py" --device cpu --mode correct
cr "roccv::cpu-flip-copy-to" --backend CPU --cwd "$(fresh_dir roccv_cpu_copy)" \
  -- "${VP_PY}" "${PROBES}/roccv_flip.py" --device cpu --mode correct --copy-to
cr "roccv::gpu-request-clean-error" --backend GPU --cwd "$(fresh_dir roccv_gpu)" \
  -- "${VP_PY}" "${PROBES}/roccv_flip.py" --device gpu --mode error

# rocAL: CPU pipelines (M13: CPU mode still needs a GPU); a GPU pipeline must fail cleanly.
cr "rocal::cpu-decode-only" --backend CPU --cwd "$(fresh_dir rocal_cpu_decode)" \
  -- "${VP_PY}" "${PROBES}/rocal_pipeline.py" --backend cpu --mode correct --data "${TINY}"
cr "rocal::cpu-decode-resize" --backend CPU --cwd "$(fresh_dir rocal_cpu_resize)" \
  -- "${VP_PY}" "${PROBES}/rocal_pipeline.py" --backend cpu --mode correct --data "${TINY}" --resize 224 224
cr "rocal::gpu-request-clean-error" --backend GPU --cwd "$(fresh_dir rocal_gpu)" \
  -- "${VP_PY}" "${PROBES}/rocal_pipeline.py" --backend gpu --mode error --data "${TINY}" --resize 224 224

# rocPyDecode / rocPyJpegDecode: creating a GPU decoder must fail cleanly.
cr "rocpydecode::video-decoder-clean-error" --backend GPU --cwd "$(fresh_dir pyd_video)" \
  -- "${VP_PY}" "${PROBES}/pyd_nogpu.py" video
cr "rocpydecode::jpeg-decoder-clean-error" --backend GPU --cwd "$(fresh_dir pyd_jpeg)" \
  -- "${VP_PY}" "${PROBES}/pyd_nogpu.py" jpeg

vp_finish
exit 0
