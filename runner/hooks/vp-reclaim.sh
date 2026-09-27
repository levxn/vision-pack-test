#!/usr/bin/env bash
# Return root-owned files under a directory to the runner user.
#
# Container jobs run as root (--user 0:0, as TheRock does), so files they write
# into bind-mounted directories end up root-owned. The runner user is in the
# docker group (which is root-equivalent anyway), so a throwaway container can
# chown them back without any sudo rule on the host.
#
# Usage: vp-reclaim.sh <dir>   (only paths under the allowed roots are accepted)
set -euo pipefail

target="${1:?usage: vp-reclaim.sh <dir>}"
target="$(readlink -f -- "${target}")"

allowed=0
for root in /srv/actions-runner /srv/vp-ci /home/ci-runner; do
  case "${target}/" in "${root}"/*) allowed=1 ;; esac
done
[[ "${allowed}" == 1 ]] || { echo "vp-reclaim: refusing ${target}" >&2; exit 2; }
[[ -d "${target}" ]] || exit 0

uid="$(id -u)"; gid="$(id -g)"
# Fast path: nothing to do if everything already belongs to us.
if [[ -z "$(find "${target}" -xdev ! -user "${uid}" -print -quit 2>/dev/null)" ]]; then
  exit 0
fi

image="${VP_RECLAIM_IMAGE:-busybox:1.36}"
docker run --rm --network none -v "${target}:/w" "${image}" \
  chown -R "${uid}:${gid}" /w >/dev/null
