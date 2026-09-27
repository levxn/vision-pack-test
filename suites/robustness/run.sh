#!/usr/bin/env bash
# Robustness (gpu_access: all): unsupported-GPU negatives, exit-code honesty and hang guards.
#
# Device indices come from enumerating GPU agents with rocminfo in this
# environment (ROCR_VISIBLE_DEVICES unset), never from host indices: inside a
# container ROCr numbers only the GPUs whose render nodes were passed in.
# Every probe that uses a GPU pins exactly one with ROCR_VISIBLE_DEVICES, and
# GPU work runs serially.
set -uo pipefail
source "${VP_REPO}/build_tools/lib/vp.sh"
vp_init robustness

if ! vp_tier_ge comprehensive; then
  vp_skip "tier::below-comprehensive" "robustness runs in the comprehensive tier and above"
  vp_finish
  exit 0
fi

CR="${VP_REPO}/suites/rocpydecode/checked_run.py"
PROBES="${VP_SUITE_DIR}/probes"
TINY="${ROCM_PATH}/share/rocal/test/data/images/AMD-tinyDataSet"
PYAPI="${ROCM_PATH}/share/rocal/test/python_api"
RVT="${ROCM_PATH}/share/mivisionx/test/vision_tests/runVisionTests.py"
export TMPDIR="${VP_WORK}/tmp"
mkdir -p "${TMPDIR}"

have_py() { "${VP_PY}" -c "import $1" >/dev/null 2>&1; }

fresh_dir() {
  local d="${VP_WORK}/cwd/$1"
  rm -rf "${d}"
  mkdir -p "${d}"
  printf '%s' "${d}"
}

# cr <id> [checked_run options] -- cmd... ; probes report a crashed child with exit 70.
cr() {
  local id="$1"; shift
  "${VP_PY}" "${CR}" --id "${id}" --timeout 300 --error-rc 70 "$@"
}

# ---------------------------------------------------------------------------
# GPU agents in ROCr order, as this process sees them.
# ---------------------------------------------------------------------------
mapfile -t AGENTS < <(env -u ROCR_VISIBLE_DEVICES timeout -k 5 60 rocminfo 2>/dev/null \
  | awk '/^  Name:/ { n = $2 } /^ *Device Type:/ { if ($3 == "GPU") print n }')
vp__log "GPU agents (ROCr order): ${AGENTS[*]:-none}; VP_GFX=${VP_GFX:-none}; VP_UNSUPPORTED_GPUS=${VP_UNSUPPORTED_GPUS:-none}"

# agent_index <gfx> <occurrence>: index of the n-th (0-based) GPU agent with that gfx, or empty.
agent_index() {
  local gfx="$1" want="$2" i seen=0
  for i in "${!AGENTS[@]}"; do
    if [[ "${AGENTS[$i]}" == "${gfx}" ]]; then
      if [[ "${seen}" == "${want}" ]]; then echo "${i}"; return; fi
      seen=$((seen + 1))
    fi
  done
}

CHOSEN_IDX=""
[[ -n "${VP_GFX}" ]] && CHOSEN_IDX="$(agent_index "${VP_GFX}" 0)"
PIN=()
[[ -n "${CHOSEN_IDX}" ]] && PIN=(--env "ROCR_VISIBLE_DEVICES=${CHOSEN_IDX}")

# ---------------------------------------------------------------------------
# Unsupported-GPU negatives (M21), with the same probes on the chosen GPU as controls.
# ---------------------------------------------------------------------------
LAUNCH_PROBE=""
LAUNCH_PROBE_WHY=""
build_launch_probe() {
  [[ -n "${LAUNCH_PROBE}${LAUNCH_PROBE_WHY}" ]] && return
  local cxx="${ROCM_PATH}/lib/llvm/bin/amdclang++" b="${VP_WORK}/roccv-launch-probe"
  if ! command -v cmake >/dev/null 2>&1 || ! command -v ninja >/dev/null 2>&1 || [[ ! -x "${cxx}" ]]; then
    LAUNCH_PROBE_WHY="needs cmake, ninja and ${cxx}"
    return
  fi
  rm -rf "${b}"
  if vp_run "unsupported-gpu.build::roccv-launch-probe.configure" --timeout 300 -- \
       cmake -S "${PROBES}/roccv_launch" -B "${b}" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER="${cxx}" \
       -DROCM_PATH="${ROCM_PATH}" "-DCMAKE_PREFIX_PATH=${ROCM_PATH};${ROCM_PATH}/lib/cmake" \
     && vp_run "unsupported-gpu.build::roccv-launch-probe.build" --timeout 600 -- cmake --build "${b}"; then
    LAUNCH_PROBE="${b}/launch_probe"
  else
    LAUNCH_PROBE_WHY="the rocCV launch probe did not build"
  fi
}

# gpu_probes <group> <agent index> <mode>
gpu_probes() {
  local g="$1" idx="$2" mode="$3" tag="${1//[^A-Za-z0-9]/_}"
  local -a env=(--backend GPU --env "ROCR_VISIBLE_DEVICES=${idx}")
  cr "${g}::mivisionx-gpu-graph" "${env[@]}" --cwd "$(fresh_dir "${tag}_mvx")" \
    -- "${VP_PY}" "${PROBES}/runvx_graph.py" --mode "${mode}" --affinity GPU
  cr "${g}::rocal-gpu-decode-resize" "${env[@]}" --cwd "$(fresh_dir "${tag}_rocal")" \
    -- "${VP_PY}" "${PROBES}/rocal_pipeline.py" --backend gpu --mode "${mode}" --data "${TINY}" --resize 224 224
  cr "${g}::roccv-flip-zeros" "${env[@]}" --cwd "$(fresh_dir "${tag}_roccv")" \
    -- "${VP_PY}" "${PROBES}/roccv_flip.py" --device gpu --mode "${mode}"
  build_launch_probe
  if [[ -n "${LAUNCH_PROBE}" ]]; then
    cr "${g}::roccv-cpp-launch-error" "${env[@]}" --cwd "$(fresh_dir "${tag}_roccv_cpp")" -- "${LAUNCH_PROBE}" "${mode}"
  else
    vp_blocked "${g}::roccv-cpp-launch-error" "${LAUNCH_PROBE_WHY}"
  fi
}

if [[ -z "${VP_UNSUPPORTED_GPUS:-}" ]]; then
  vp_skip "unsupported-gpu::none-present" "no unsupported GPU on this runner"
elif [[ ${#AGENTS[@]} -eq 0 ]]; then
  vp_result "unsupported-gpu::agent-enumeration" error "rocminfo lists no GPU agents although VP_UNSUPPORTED_GPUS=${VP_UNSUPPORTED_GPUS}"
else
  if [[ -n "${CHOSEN_IDX}" ]]; then
    gpu_probes "unsupported-gpu.control" "${CHOSEN_IDX}" correct
  else
    vp_result "unsupported-gpu.control::device-visible" error "${VP_GFX:-no chosen GPU} is not among the GPU agents (${AGENTS[*]})"
  fi
  declare -A occurrence=()
  IFS=, read -r -a unsupported <<<"${VP_UNSUPPORTED_GPUS}"
  for u in "${unsupported[@]}"; do
    gfx="${u%%:*}"
    [[ -n "${gfx}" ]] || continue
    n="${occurrence[${gfx}]:-0}"
    occurrence[${gfx}]=$((n + 1))
    group="unsupported-gpu.${gfx}"
    [[ "${n}" -gt 0 ]] && group="${group}.${n}"
    idx="$(agent_index "${gfx}" "${n}")"
    if [[ -z "${idx}" ]]; then
      vp_result "${group}::device-visible" error "${gfx} (${u}) is not among the GPU agents here (${AGENTS[*]})"
      continue
    fi
    vp__log "${group}: ROCR_VISIBLE_DEVICES=${idx}"
    gpu_probes "${group}" "${idx}" honest
  done
fi

# ---------------------------------------------------------------------------
# Exit-code honesty: controlled failing cases that must end with a non-zero status.
# ---------------------------------------------------------------------------
# M8: Pipeline.build() calls exit(0) when rocalVerify fails.
cr "exit-code::rocal-build-exit0" --backend GPU "${PIN[@]}" --expect-nonzero --error-if "CONTROL-INVALID" \
  --cwd "$(fresh_dir rocal_build_exit0)" -- "${VP_PY}" "${PROBES}/rocal_verify_fail.py" "${TINY}"

# H16: runVisionTests.py ignores runvx's exit status. A runvx that always fails must fail the run.
FAKE="${VP_WORK}/fake-runvx"
rm -rf "${FAKE}"
mkdir -p "${FAKE}"
printf '#!/bin/sh\necho "fake runvx: simulated failure" >&2\nexit 1\n' >"${FAKE}/runvx"
chmod +x "${FAKE}/runvx"
cr "exit-code::runvisiontests-ignores-runvx-failure" --expect-nonzero --require "fake runvx: simulated failure" \
  --cwd "$(fresh_dir runvisiontests)" -- "${VP_PY}" "${RVT}" --runvx_directory "${FAKE}" \
  --hardware_mode CPU --backend_type CPU --test_filter 1 --num_frames 1

# rocAL's golden comparator logs FAILED but always exits 0.
d="$(fresh_dir image_comparison)"
if "${VP_PY}" "${PROBES}/make_compare_fixture.py" "${d}" >/dev/null 2>&1; then
  cr "exit-code::rocal-image-comparison-exit0" --expect-nonzero --require "Total case failed --> 1" --cwd "${d}" \
    -- "${VP_PY}" "${PYAPI}/image_comparison.py" golden/ rocal/
else
  vp_blocked "exit-code::rocal-image-comparison-exit0" "could not create the fixture (needs numpy and Pillow)"
fi

# rocAL's unit_test.py prints "Install tensorflow" and exits 0 (tensorflow hidden on purpose).
if have_py cv2; then
  d="$(fresh_dir unit_test_tf)"
  mkdir -p "${d}/tfrecord"
  cr "exit-code::rocal-unit-test-missing-tensorflow-exit0" --expect-nonzero --require "Install tensorflow" --cwd "${d}" \
    --env "PYTHONPATH=${PROBES}/stubs/notf:${PYTHONPATH}" \
    -- "${VP_PY}" "${PYAPI}/unit_test.py" --reader-type tf_classification --image-dataset-path "${d}/tfrecord/" \
    --batch-size 2 --no-display
else
  vp_blocked "exit-code::rocal-unit-test-missing-tensorflow-exit0" "unit_test.py imports cv2 (python3-opencv not installed)"
fi

# rocAL's audio_unit_test.py exits 0 on an invalid test case (and on every failed case, H5).
if have_py torch && have_py matplotlib; then
  cr "exit-code::rocal-audio-unit-test-exit0" --expect-nonzero --require "Invalid Test Case" \
    --cwd "$(fresh_dir audio_unit_test)" -- "${VP_PY}" "${PYAPI}/audio_unit_test.py" --test_case 9999
else
  vp_blocked "exit-code::rocal-audio-unit-test-exit0" "audio_unit_test.py imports torch and matplotlib"
fi

# amd.rocal.readers.tfrecord() calls exit() (status 0) on a feature key missing from the key map.
cr "exit-code::rocal-tfrecord-missing-key-exit0" --expect-nonzero --error-if "CONTROL-INVALID" \
  --cwd "$(fresh_dir tfrecord_exit)" -- "${VP_PY}" "${PROBES}/rocal_tfrecord_exit.py"

# rocPyDecode's decoder_test.py catches its own argument error and calls exit() (status 0).
cr "exit-code::rocpydecode-decoder-test-bad-args-exit0" --expect-nonzero --require "Error:" \
  --cwd "$(fresh_dir decoder_test_args)" -- "${VP_PY}" "${ROCM_PATH}/share/rocpydecode/tests/decoder_test.py"

# ---------------------------------------------------------------------------
# Hang guards. A timeout is recorded as error, which is how M12 reproduces.
# ---------------------------------------------------------------------------
COCO="rocal_data/coco/coco_10_img/images"
if [[ -n "${VP_DATA}" && -d "${VP_DATA}/${COCO}" ]]; then
  base="${VP_DATA%/}"
  stub_env=()
  have_py cv2 || stub_env=(--env "PYTHONPATH=${PYTHONPATH}:${PROBES}/stubs/cv2")
  # external_source_reader.py builds ROCAL_DATA_PATH + "rocal_data/..."; without a trailing
  # separator it finds no files and rocalRun blocks forever (M12). Terminating with an error passes.
  hang_modes=(cpu)
  vp_tier_ge full && hang_modes+=(gpu)
  for m in "${hang_modes[@]}"; do
    id="hang::external-source-no-separator"
    [[ "${m}" == gpu ]] && id="${id}.gpu"
    d="$(fresh_dir "external_source_nosep_${m}")"
    cr "${id}" --timeout 60 "${PIN[@]}" "${stub_env[@]}" --env "ROCAL_DATA_PATH=${base}" --expect-nonzero \
      --pass-if-file "output_folder/external_source_reader/mode0/*.png" --blocked-if "VPT-CV2-STUB used" --cwd "${d}" \
      -- "${VP_PY}" "${PYAPI}/external_source_reader.py" "${m}" 2
  done
  if have_py cv2; then
    cr "hang::external-source-with-separator" --timeout 180 "${PIN[@]}" --env "ROCAL_DATA_PATH=${base}/" \
      --require "MODE 2" --cwd "$(fresh_dir external_source_sep)" \
      -- "${VP_PY}" "${PYAPI}/external_source_reader.py" cpu 2
  else
    vp_blocked "hang::external-source-with-separator" "external_source_reader.py writes PNGs with cv2 (python3-opencv not installed)"
  fi
else
  vp_blocked "hang::external-source-no-separator" "dataset ${COCO} not available (VP_DATA=${VP_DATA:-unset})"
  vp_tier_ge full && vp_blocked "hang::external-source-no-separator.gpu" "dataset ${COCO} not available"
  vp_blocked "hang::external-source-with-separator" "dataset ${COCO} not available"
fi

vp_finish
exit 0
