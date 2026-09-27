#!/usr/bin/env bash
# CI step (test.yml): run one matrix suite in its container on the runner.
#
# Environment (set by the workflow step):
#   SUITE ENTRY KIND ACCESS TIMEOUT_MIN TIER PREFIX GFX MINOR RUN_DIR VP_ROOT
#   IMAGE_TEST IMAGE_MEDIA IMAGE_EXTENDED [DIST_TARBALL VP_UNSUPPORTED_GPUS VP_SDK_FAMILY]
#
# A suite's run.sh exits 0 once it has recorded its results, so a non-zero
# exit here is an infrastructure problem (container failure, time budget
# exhausted). The step then fails, records runner-status.json for the report
# and prints how to reproduce. The time budget leaves room for the upload.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO}"
: "${SUITE:?}" "${ENTRY:?}" "${KIND:?}" "${ACCESS:?}" "${TIMEOUT_MIN:?}" "${TIER:?}" "${PREFIX:?}" "${RUN_DIR:?}"

case "${KIND}" in
  test) image="${IMAGE_TEST:-}" ;;
  media) image="${IMAGE_MEDIA:-}" ;;
  extended) image="${IMAGE_EXTENDED:-}" ;;
  *) echo "::error::unknown image kind ${KIND}"; exit 2 ;;
esac
[[ -n "${image}" ]] || { echo "::error::prepare-rocm prepared no ${KIND} image"; exit 1; }

out="${RUN_DIR}/results/${SUITE}"
mkdir -p "${out}"
extra=()
if [[ "${SUITE}" == install-test ]]; then
  shopt -s nullglob
  for t in "${out}"/input/*.tar; do tar -xf "${t}" -C "${out}/input"; done
  shopt -u nullglob
  extra+=(--env "VP_DEB_DIR=/opt/vp/out/input/deb")
fi
[[ -n "${DIST_TARBALL:-}" && -f "${DIST_TARBALL}" ]] && extra+=(--dist-tarball "${DIST_TARBALL}")

budget=$((TIMEOUT_MIN * 60 - 240))
((budget >= 300)) || budget=300
cmd=(build_tools/run_in_container.sh --suite "${SUITE}" --entrypoint "${ENTRY}" --prefix "${PREFIX}"
     --out "${out}" --image "${image}" --data "${VP_ROOT}/data/MIVisionX-data" --cache "${VP_ROOT}/cache/suites"
     --tier "${TIER}" --gfx "${GFX:-}" --render-minor "${MINOR:-}" --gpu-access "${ACCESS}"
     ${extra[@]+"${extra[@]}"})

echo "::group::${SUITE}: ${cmd[*]}"
rc=0
timeout -k 60 "${budget}" "${cmd[@]}" || rc=$?
echo "::endgroup::"

reason=ok
if ((rc == 124 || rc == 137)); then
  reason="time budget of ${budget}s exhausted"
elif ((rc != 0)); then
  reason="exited ${rc}"
fi
jq -n --arg suite "${SUITE}" --argjson rc "${rc}" --arg reason "${reason}" --argjson budget "${budget}" \
  '{suite:$suite, rc:$rc, reason:$reason, budget_s:$budget}' >"${out}/runner-status.json"

{
  echo "### ${SUITE}"
  if [[ -f "${out}/summary.json" ]]; then
    jq -r '"| status | count |\n|---|---|\n" + (.counts // {} | to_entries | map("| \(.key) | \(.value) |") | join("\n"))' \
      "${out}/summary.json"
  else
    echo "No summary.json: the suite did not finish (${reason})."
  fi
} >>"${GITHUB_STEP_SUMMARY:-/dev/null}"

if ((rc != 0)); then
  echo "::error title=${SUITE}::suite ${reason}; results may be partial"
  cat <<EOF
Reproduce on the runner (same prefix and image):
  VP_UNSUPPORTED_GPUS='${VP_UNSUPPORTED_GPUS:-}' ${cmd[*]}
Reproduce on any machine with a ROCm + vision-pack prefix:
  build_tools/local_run.sh --suite ${SUITE} --prefix <prefix> --data <MIVisionX-data> --tier ${TIER}
EOF
fi
exit "${rc}"
