#!/usr/bin/env bash
# Post-job hook for the vision-pack-test self-hosted runners.
#
# Installed root-owned (0755) at /opt/vp-hooks/job-completed.sh by
# runner/setup.sh and referenced as ACTIONS_RUNNER_HOOK_JOB_COMPLETED.
# Runs even when the job failed or was cancelled. It never fails the job.
set -uo pipefail

VP_ROOT="/srv/vp-ci"
VP_KEEP_RUNS=5
if [[ -r /etc/vp-ci/hooks.conf ]]; then
  # shellcheck source=/dev/null
  . /etc/vp-ci/hooks.conf
fi

# 1. Kill test containers this workflow run started and that are still alive
#    (a cancelled job leaves its `docker run` orphaned). run_in_container.sh
#    labels every container with vp-ci.run=<run_id>.
if command -v docker >/dev/null 2>&1 && [[ -n "${GITHUB_RUN_ID:-}" ]]; then
  ids="$(docker ps -q --filter "label=vp-ci.run=${GITHUB_RUN_ID}" 2>/dev/null || true)"
  if [[ -n "${ids}" ]]; then
    echo "vp-ci post-job hook: removing leftover containers: ${ids}"
    # shellcheck disable=SC2086
    docker rm -f ${ids} >/dev/null 2>&1 || true
  fi
  # Anything labelled vp-ci that is older than 12 hours is an orphan.
  docker ps --filter "label=vp-ci.run" --format '{{.ID}} {{.RunningFor}}' 2>/dev/null \
    | awk '/(days|[0-9]{2} hours)/ {print $1}' \
    | xargs -r docker rm -f >/dev/null 2>&1 || true
fi

# 2. Give root-owned files back to the runner user.
if [[ -n "${GITHUB_WORKSPACE:-}" ]]; then
  work_root="$(dirname "$(dirname "${GITHUB_WORKSPACE}")")"
  [[ -d "${work_root}" ]] && /opt/vp-hooks/vp-reclaim.sh "${work_root}" || true
fi
[[ -d "${VP_ROOT}/runs" ]] && /opt/vp-hooks/vp-reclaim.sh "${VP_ROOT}/runs" || true

# 3. Keep only the newest VP_KEEP_RUNS per-run ROCm prefixes.
if [[ -d "${VP_ROOT}/runs" ]]; then
  mapfile -t old < <(ls -1dt "${VP_ROOT}"/runs/*/ 2>/dev/null | tail -n +"$((VP_KEEP_RUNS + 1))")
  for d in "${old[@]}"; do
    case "${d}" in
      "${VP_ROOT}"/runs/?*/) echo "vp-ci post-job hook: pruning ${d}"; rm -rf -- "${d}" ;;
    esac
  done
fi

exit 0
