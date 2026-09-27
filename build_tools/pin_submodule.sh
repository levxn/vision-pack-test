#!/usr/bin/env bash
# Check out the vision-pack submodule at the tested commit.
#
#   pin_submodule.sh <sha> [--recursive]
#
# Release mode needs only vision-pack's top level (build_tools/, packaging/);
# --recursive also initialises the nested library submodules (build mode).
# The gitlink in this repository keeps tracking main; the pin is per job.
set -euo pipefail

sha="${1:?usage: pin_submodule.sh <sha> [--recursive]}"
recursive="${2:-}"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

retry() {
  local i
  for i in 1 2 3 4; do
    "$@" && return 0
    echo "retrying ($i): $*" >&2
    sleep $((i * 10))
  done
  return 1
}

git submodule sync --quiet vision-pack
retry git submodule update --init --depth 1 vision-pack || retry git submodule update --init vision-pack
if [[ "$(git -C vision-pack rev-parse HEAD)" != "${sha}" ]]; then
  retry git -C vision-pack fetch --quiet --depth 1 origin "${sha}"
  git -C vision-pack checkout --quiet --detach "${sha}"
fi
if [[ "${recursive}" == --recursive ]]; then
  retry git -C vision-pack submodule update --init --recursive --depth 1
fi
echo "vision-pack pinned at $(git -C vision-pack rev-parse HEAD)"
