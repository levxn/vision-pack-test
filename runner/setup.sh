#!/usr/bin/env bash
# Bootstrap the dedicated AMD GPU machine as a self-hosted runner for
# levxn/vision-pack-test. Run once, as root, on the runner host.
#
#   sudo ./runner/setup.sh --repo levxn/vision-pack-test --token <REGISTRATION_TOKEN> \
#        [--name vp-gpu-01] [--user ci-runner] [--data-src /path/to/MIVisionX-data] \
#        [--runner-version 2.329.0] [--with-cpu-runner] [--skip-register]
#
# Get the registration token from: repo Settings -> Actions -> Runners ->
# New self-hosted runner (valid for one hour; it can register both instances).
#
# The script is idempotent: re-running it updates hooks, config and packages.
# It does NOT install the amdgpu kernel driver (host-specific, see README.md).
set -euo pipefail

REPO=""
TOKEN=""
NAME="vp-gpu-01"
RUNNER_USER="ci-runner"
DATA_SRC=""
RUNNER_VERSION=""
WITH_CPU_RUNNER=0
SKIP_REGISTER=0
VP_ROOT="/srv/vp-ci"
RUNNER_ROOT="/srv/actions-runner"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() { sed -n '2,15p' "$0"; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --user) RUNNER_USER="$2"; shift 2 ;;
    --data-src) DATA_SRC="$2"; shift 2 ;;
    --runner-version) RUNNER_VERSION="$2"; shift 2 ;;
    --with-cpu-runner) WITH_CPU_RUNNER=1; shift ;;
    --skip-register) SKIP_REGISTER=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done

log() { printf '\n==> %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(id -u)" == 0 ]] || die "run as root (sudo)"
[[ -n "${REPO}" ]] || die "--repo owner/name is required"
if [[ "${SKIP_REGISTER}" == 0 && -z "${TOKEN}" ]]; then
  die "--token is required unless --skip-register is given"
fi

. /etc/os-release
case "${VERSION_ID:-}" in 22.04|24.04) ;; *) echo "WARNING: tested on Ubuntu 22.04/24.04, found ${PRETTY_NAME:-unknown}" ;; esac

log "Checking the GPU driver"
if [[ -e /dev/kfd ]]; then
  echo "/dev/kfd present"
  for p in /sys/class/kfd/kfd/topology/nodes/*/properties; do
    v="$(awk '$1=="gfx_target_version"{print $2}' "$p")"
    [[ "${v:-0}" -gt 0 ]] || continue
    printf '  GPU node %s: gfx%d%x%x (render minor %s)\n' "$(basename "$(dirname "$p")")" \
      $((v / 10000)) $(((v / 100) % 100)) $((v % 100)) "$(awk '$1=="drm_render_minor"{print $2}' "$p")"
  done
else
  echo "WARNING: /dev/kfd missing. Install/load the amdgpu kernel driver before running GPU jobs (see runner/README.md)."
fi

log "Installing host packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  ca-certificates curl jq git git-lfs tar pigz zstd python3 python3-yaml rsync acl \
  docker.io cron
systemctl enable --now docker

log "Creating runner user ${RUNNER_USER}"
if ! id "${RUNNER_USER}" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "${RUNNER_USER}"
fi
for g in docker video render; do
  getent group "$g" >/dev/null && usermod -aG "$g" "${RUNNER_USER}"
done
# No sudo rights for the runner user: nothing in the workflows needs them.
rm -f "/etc/sudoers.d/${RUNNER_USER}" 2>/dev/null || true

log "Creating ${VP_ROOT}"
install -d -o "${RUNNER_USER}" -g "${RUNNER_USER}" -m 0755 \
  "${VP_ROOT}" "${VP_ROOT}/runs" "${VP_ROOT}/cache" \
  "${VP_ROOT}/cache/sdk" "${VP_ROOT}/cache/pip" "${VP_ROOT}/cache/cts" "${VP_ROOT}/cache/images"
install -d -o root -g root -m 0755 "${VP_ROOT}/data"

if [[ -n "${DATA_SRC}" ]]; then
  log "Copying the test dataset from ${DATA_SRC}"
  [[ -d "${DATA_SRC}/rocal_data" ]] || die "${DATA_SRC} must contain rocal_data/"
  install -d -o root -g root -m 0755 "${VP_ROOT}/data/MIVisionX-data"
  rsync -a --chown=root:root "${DATA_SRC}/" "${VP_ROOT}/data/MIVisionX-data/"
  # Read-only master copy. Suites copy LMDB subsets into scratch before use,
  # because rocAL's LMDB readers rewrite lock.mdb even when only reading (M14).
  chmod -R a-w,a+rX "${VP_ROOT}/data/MIVisionX-data"
else
  echo "No --data-src given; copy MIVisionX-data to ${VP_ROOT}/data/MIVisionX-data later."
fi

log "Installing job hooks into /opt/vp-hooks"
install -d -o root -g root -m 0755 /opt/vp-hooks /etc/vp-ci
install -o root -g root -m 0755 "${HERE}/hooks/job-started.sh" /opt/vp-hooks/job-started.sh
install -o root -g root -m 0755 "${HERE}/hooks/job-completed.sh" /opt/vp-hooks/job-completed.sh
install -o root -g root -m 0755 "${HERE}/hooks/vp-reclaim.sh" /opt/vp-hooks/vp-reclaim.sh
cat >/etc/vp-ci/hooks.conf <<EOF
# vision-pack-test runner hook configuration (root-owned; read by /opt/vp-hooks/*).
VP_ALLOWED_REPO="${REPO}"
VP_ALLOWED_WORKFLOWS=".github/workflows/nightly.yml"
VP_ALLOWED_REF="refs/heads/main"
VP_ALLOWED_EVENTS="schedule workflow_dispatch"
VP_MIN_FREE_GB=100
VP_ROOT="${VP_ROOT}"
VP_KEEP_RUNS=5
EOF
chmod 0644 /etc/vp-ci/hooks.conf

log "Disabling apport (crashing tests must not write to /var/crash)"
if systemctl list-unit-files apport.service >/dev/null 2>&1; then
  systemctl disable --now apport.service || true
fi
[[ -f /etc/default/apport ]] && sed -i 's/^enabled=.*/enabled=0/' /etc/default/apport
echo 'kernel.core_pattern = core' >/etc/sysctl.d/60-vp-ci-core.conf
sysctl -q -p /etc/sysctl.d/60-vp-ci-core.conf || true

log "Excluding the runner service from needrestart"
install -d /etc/needrestart/conf.d
echo '$nrconf{override_rc}{qr(^actions\.runner\..+\.service$)} = 0;' \
  >/etc/needrestart/conf.d/actions_runner_services.conf

log "Installing the daily prune job"
install -o root -g root -m 0755 "${HERE}/cron/vp-ci-prune" /etc/cron.daily/vp-ci-prune

log "Pre-pulling the helper image used for workspace reclaim"
docker pull -q busybox:1.36 >/dev/null || echo "WARNING: could not pull busybox:1.36"

register_runner() {
  local name="$1" labels="$2" role="$3"
  local dir="${RUNNER_ROOT}/${name}"

  if [[ -z "${RUNNER_VERSION}" ]]; then
    RUNNER_VERSION="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name)"
    RUNNER_VERSION="${RUNNER_VERSION#v}"
  fi
  log "Setting up runner ${name} (actions/runner ${RUNNER_VERSION}, labels ${labels})"
  install -d -o "${RUNNER_USER}" -g "${RUNNER_USER}" -m 0755 "${RUNNER_ROOT}" "${dir}"

  if [[ ! -x "${dir}/config.sh" ]]; then
    local tgz="actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
    local url="https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/${tgz}"
    curl -fsSL -o "/tmp/${tgz}" "${url}"
    # The release notes carry the expected checksum between markers.
    local expected
    expected="$(curl -fsSL "https://api.github.com/repos/actions/runner/releases/tags/v${RUNNER_VERSION}" \
      | jq -r .body | sed -n 's/.*<!-- BEGIN SHA linux-x64 -->\([0-9a-f]\{64\}\)<!-- END SHA linux-x64 -->.*/\1/p' | head -1)"
    if [[ -n "${expected}" ]]; then
      echo "${expected}  /tmp/${tgz}" | sha256sum -c - || die "runner tarball checksum mismatch"
    else
      echo "WARNING: could not read the expected checksum from the release notes"
    fi
    tar -xzf "/tmp/${tgz}" -C "${dir}"
    rm -f "/tmp/${tgz}"
    chown -R "${RUNNER_USER}:${RUNNER_USER}" "${dir}"
    "${dir}/bin/installdependencies.sh" || true
  fi

  if [[ "${SKIP_REGISTER}" == 0 && ! -f "${dir}/.runner" ]]; then
    sudo -u "${RUNNER_USER}" "${dir}/config.sh" --unattended \
      --url "https://github.com/${REPO}" --token "${TOKEN}" \
      --name "${name}" --labels "${labels}" --no-default-labels \
      --work "${dir}/_work" --replace
  fi

  # Root-owned .env: the runner reads it at start-up; jobs cannot rewrite it.
  cat >"${dir}/.env" <<EOF
ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/vp-hooks/job-started.sh
ACTIONS_RUNNER_HOOK_JOB_COMPLETED=/opt/vp-hooks/job-completed.sh
VP_RUNNER_ROLE=${role}
VP_ROOT=${VP_ROOT}
LANG=C.UTF-8
EOF
  chown root:root "${dir}/.env"
  chmod 0644 "${dir}/.env"

  if [[ -f "${dir}/.runner" ]]; then
    pushd "${dir}" >/dev/null
    # svc.sh records the unit name in .service once it has installed it.
    if [[ ! -f .service ]]; then
      ./svc.sh install "${RUNNER_USER}"
    fi
    ./svc.sh stop >/dev/null 2>&1 || true
    ./svc.sh start
    popd >/dev/null
  fi
}

register_runner "${NAME}" "vp-gpu" "gpu"
if [[ "${WITH_CPU_RUNNER}" == 1 ]]; then
  register_runner "${NAME/gpu/cpu}" "vp-cpu" "cpu"
fi

log "Done"
cat <<EOF
Runner user:      ${RUNNER_USER} (groups: $(id -nG "${RUNNER_USER}"))
Work roots:       ${RUNNER_ROOT}/*
CI state:         ${VP_ROOT}/{cache,data,runs}
Hooks:            /opt/vp-hooks (config /etc/vp-ci/hooks.conf)

Next steps (see runner/README.md):
  1. Confirm the runner shows as Idle under repo Settings -> Actions -> Runners.
  2. Optionally set the repo variable EXPECTED_GFX (e.g. gfx1201) to pin the GPU.
  3. Run the nightly workflow once with workflow_dispatch (tier=quick).
EOF
