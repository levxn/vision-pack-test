#!/usr/bin/env bash
# Pre-job hook for the vision-pack-test self-hosted runners.
#
# Installed root-owned (0755) at /opt/vp-hooks/job-started.sh by runner/setup.sh
# and referenced from the runner's .env as ACTIONS_RUNNER_HOOK_JOB_STARTED.
# The runner executes it on the host before any workflow step; a non-zero exit
# fails the job before any repository code runs. This is the real security
# gate for a self-hosted runner attached to a public repository: a fork PR can
# add its own workflow targeting this runner's label, but it cannot edit this
# file.
#
# Overrides (optional): /etc/vp-ci/hooks.conf (root-owned), sourced below.
set -euo pipefail

VP_ALLOWED_REPO="levxn/vision-pack-test"
VP_ALLOWED_WORKFLOWS=".github/workflows/nightly.yml"
VP_ALLOWED_REF="refs/heads/main"
VP_ALLOWED_EVENTS="schedule workflow_dispatch"
VP_MIN_FREE_GB=100
VP_ROOT="/srv/vp-ci"
# gpu | cpu. Set per runner instance in its .env (VP_RUNNER_ROLE=cpu for vp-cpu).
VP_RUNNER_ROLE="${VP_RUNNER_ROLE:-gpu}"

if [[ -r /etc/vp-ci/hooks.conf ]]; then
  # shellcheck source=/dev/null
  . /etc/vp-ci/hooks.conf
fi

fail() {
  echo "::error title=vp-ci pre-job hook::$*"
  exit 1
}

event="${GITHUB_EVENT_NAME:-}"
allowed_event=0
for e in ${VP_ALLOWED_EVENTS}; do
  [[ "${event}" == "${e}" ]] && allowed_event=1
done
[[ "${allowed_event}" == 1 ]] || fail "event '${event}' is not allowed on this runner"

[[ "${GITHUB_REPOSITORY:-}" == "${VP_ALLOWED_REPO}" ]] \
  || fail "repository '${GITHUB_REPOSITORY:-}' is not allowed on this runner"

# For jobs of reusable workflows, GITHUB_WORKFLOW_REF is the top-level caller,
# so allow-listing nightly.yml covers test.yml/report.yml/build.yml jobs too.
wf_ref="${GITHUB_WORKFLOW_REF:-}"
allowed_wf=0
for wf in ${VP_ALLOWED_WORKFLOWS}; do
  [[ "${wf_ref}" == "${VP_ALLOWED_REPO}/${wf}@${VP_ALLOWED_REF}" ]] && allowed_wf=1
done
[[ "${allowed_wf}" == 1 ]] || fail "workflow '${wf_ref}' is not allow-listed (need ${VP_ALLOWED_WORKFLOWS} on ${VP_ALLOWED_REF})"

if [[ "${VP_RUNNER_ROLE}" == "gpu" ]]; then
  [[ -e /dev/kfd ]] || fail "/dev/kfd is missing (amdgpu driver not loaded?)"
  ls /dev/dri/renderD* >/dev/null 2>&1 || fail "no /dev/dri/renderD* nodes"
fi

command -v docker >/dev/null 2>&1 || fail "docker is not installed"
docker info >/dev/null 2>&1 || fail "docker daemon unreachable for $(id -un)"

mkdir -p "${VP_ROOT}/runs" "${VP_ROOT}/cache" 2>/dev/null || true
avail_gb="$(df --output=avail -BG "${VP_ROOT}" | tail -1 | tr -dc '0-9')"
(( ${avail_gb:-0} >= VP_MIN_FREE_GB )) \
  || fail "only ${avail_gb:-0} GB free on ${VP_ROOT} (need ${VP_MIN_FREE_GB})"

# Reclaim anything a previous (possibly cancelled) container job left root-owned
# in the runner work tree, so actions/checkout does not fail with EACCES.
if [[ -n "${GITHUB_WORKSPACE:-}" ]]; then
  work_root="$(dirname "$(dirname "${GITHUB_WORKSPACE}")")"
  if [[ -d "${work_root}" ]]; then
    /opt/vp-hooks/vp-reclaim.sh "${work_root}" || echo "::warning::workspace reclaim failed"
  fi
fi

echo "vp-ci pre-job hook: ok (event=${event}, role=${VP_RUNNER_ROLE}, free=${avail_gb}G)"
