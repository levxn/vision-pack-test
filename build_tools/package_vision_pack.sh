#!/usr/bin/env bash
# Build mode, step 2: turn the staged tree into the release assets, exactly
# as upstream's package.yml does (CPack DEB and RPM, the meta packages, the
# dist tarball), then lay them out and pack them like fetch_release.sh, so
# test.yml cannot tell a build from a published nightly.
#
#   package_vision_pack.sh --staging <vision-pack-staging.tar.gz> --version <ver> \
#       --build-id <id> --out <dir> [--rocm-version 10.2.0]
#
# Run from the repository root (vision-pack submodule checked out) inside
# ubuntu:24.04 as root. Writes <out>/vision-pack-{deb,rpm,tarball}-<ver>-<id>.tar
# and deb_artifact/rpm_artifact/tarball_artifact to $GITHUB_OUTPUT.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
staging_tar="" version="" build_id="" out="" rocm_version=10.2.0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --staging) staging_tar="$2"; shift 2 ;;
    --version) version="$2"; shift 2 ;;
    --build-id) build_id="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --rocm-version) rocm_version="$2"; shift 2 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -f "${staging_tar}" && -n "${version}" && -n "${build_id}" && -n "${out}" ]] \
  || { echo "--staging, --version, --build-id and --out are required" >&2; exit 2; }
mkdir -p "${out}"
out="$(cd "${out}" && pwd)"
staging_tar="$(readlink -f "${staging_tar}")"

echo "::group::packaging tools"
apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates cmake dpkg-dev debhelper equivs rpm \
  createrepo-c patchelf python3 curl jq git >/dev/null
git config --global --add safe.directory '*'
echo "::endgroup::"

work="$(mktemp -d)"
mkdir -p "${work}/staging"
tar -xzf "${staging_tar}" -C "${work}/staging"
cd "${REPO}/vision-pack"

cmake -B "${work}/pkg-build" -S packaging/ -DVISION_PACK_STAGING_DIR="${work}/staging" \
  -DVISION_PACK_VERSION="${version}" -DVISION_PACK_ROCM_VERSION="${rocm_version}" \
  -DVISION_PACK_BUILD_ID="${build_id}"
(cd "${work}/pkg-build" && cpack -G DEB && cpack -G RPM)
(cd "${work}/pkg-build" && cmake --build . --target package-meta-vision)
cp "${work}"/pkg-build/meta/*.deb "${work}/pkg-build/" 2>/dev/null || true
find "${work}/pkg-build/meta/rpms" -name '*.rpm' -exec cp {} "${work}/pkg-build/" \; 2>/dev/null || true

# Upstream's structural gates on what customers get.
fail=0
for deb in "${work}"/pkg-build/*.deb; do
  pkg="$(dpkg-deb --field "${deb}" Package)"
  files="$(dpkg-deb --contents "${deb}" | awk '$1 !~ /^d/' | wc -l)"
  ((files > 0)) || { echo "::error::${pkg} contains no files"; fail=1; }
  stray="$(dpkg-deb --contents "${deb}" | awk '$1 !~ /^d/ {print $6}' \
    | grep -v '^\./opt/rocm/' | grep -v '^\./usr/lib/python3/dist-packages/' || true)"
  [[ -z "${stray}" ]] || { echo "::error::${pkg} ships paths outside /opt/rocm: ${stray}"; fail=1; }
done
for m in amdrocm-vision amdrocm-vision-sdk amdrocm-vision-tests; do
  compgen -G "${work}/pkg-build/${m}_*.deb" >/dev/null || { echo "::error::meta package ${m} (deb) missing"; fail=1; }
  compgen -G "${work}/pkg-build/${m}-[0-9]*.rpm" >/dev/null || { echo "::error::meta package ${m} (rpm) missing"; fail=1; }
done

dest="${work}/assets"
mkdir -p "${dest}"/{deb,rpm,tarball}
cp "${work}"/pkg-build/*.deb "${dest}/deb/"
cp "${work}"/pkg-build/*.rpm "${dest}/rpm/"
tarball="${dest}/tarball/vision-pack-dist-linux-multiarch-${version}.tar.gz"
tar -czf "${tarball}" -C "${work}/staging" .
[[ "$(tar -tvzf "${tarball}" | grep -c '^l.*lib/libvx_rpp\.so' || true)" -ge 2 ]] \
  || { echo "::error::libvx_rpp SONAME chain is not symlinked in the tarball"; fail=1; }
tar -tvzf "${tarball}" | awk '/bin\/runvx$/ {print $1}' | grep -q x \
  || { echo "::error::runvx is missing or not executable in the tarball"; fail=1; }
((fail == 0)) || exit 1

cp "${work}/staging/share/vision-pack/vision-pack-manifest.json" "${dest}/manifest.json"
(cd "${dest}" && find deb rpm tarball -type f -print0 | sort -z | xargs -0 sha256sum) >"${dest}/SHA256SUMS"
jq -n --arg version "${version}" --arg id "${build_id}" \
  --arg sha "$(jq -r .sha "${dest}/manifest.json")" \
  --argjson deb "$(find "${dest}/deb" -name '*.deb' | wc -l)" \
  --argjson rpm "$(find "${dest}/rpm" -name '*.rpm' | wc -l)" \
  '{tag:"", mode:"build", version:$version, date:$id, sha:$sha, assets:{deb:$deb, rpm:$rpm, tarball:1}}' \
  >"${dest}/fetch.json"

names=()
for kind in deb rpm tarball; do
  name="vision-pack-${kind}-${version}-${build_id}"
  extra=()
  [[ "${kind}" == tarball ]] && extra=(manifest.json SHA256SUMS fetch.json)
  tar -cf "${out}/${name}.tar" -C "${dest}" "${kind}" ${extra[@]+"${extra[@]}"}
  names+=("${name}")
done
echo "packaged $(find "${dest}/deb" -name '*.deb' | wc -l) DEB, $(find "${dest}/rpm" -name '*.rpm' | wc -l) RPM and the dist tarball"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "deb_artifact=${names[0]}"
    echo "rpm_artifact=${names[1]}"
    echo "tarball_artifact=${names[2]}"
  } >>"${GITHUB_OUTPUT}"
fi
rm -rf "${work}"
