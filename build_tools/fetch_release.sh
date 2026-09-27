#!/usr/bin/env bash
# Download and verify one vision-pack nightly release.
#
#   fetch_release.sh --tag nightly-20260926 --dest <dir> [--repo kiritigowda/vision-pack]
#       [--sha <expected commit>] [--expect-deb 16] [--expect-rpm 16] [--expect-tarball 1]
#       [--pack <artifact-dir>] [--github]
#
# Layout written to <dest>: deb/*.deb, rpm/*.rpm, tarball/vision-pack-dist-*.tar.gz,
# release.json (GitHub API), manifest.json (from the tarball), SHA256SUMS and
# fetch.json. Every asset must match the sha256 `digest` the release API
# reports, the asset counts must match, and the tarball manifest's sha must be
# the tagged commit (the third leg of the SHA triple; resolve_release.py checks
# the other two). --pack writes vision-pack-{deb,rpm,tarball}-<ver>-<date>.tar
# (upstream's artifact names) so symlinks and exec bits survive
# upload-artifact. Any mismatch exits non-zero: an unverified release is never
# tested.
set -euo pipefail

repo=kiritigowda/vision-pack tag="" dest="" sha="" pack="" github=0
expect_deb=16 expect_rpm=16 expect_tarball=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo="$2"; shift 2 ;;
    --tag) tag="$2"; shift 2 ;;
    --dest) dest="$2"; shift 2 ;;
    --sha) sha="$2"; shift 2 ;;
    --expect-deb) expect_deb="$2"; shift 2 ;;
    --expect-rpm) expect_rpm="$2"; shift 2 ;;
    --expect-tarball) expect_tarball="$2"; shift 2 ;;
    --pack) pack="$2"; shift 2 ;;
    --github) github=1; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ -n "${tag}" && -n "${dest}" ]] || { echo "--tag and --dest are required" >&2; exit 2; }

log() { printf '[fetch-release] %s\n' "$*" >&2; }
die() { printf '::error::fetch-release: %s\n' "$*" >&2; exit 1; }

token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
auth=()
[[ -n "${token}" ]] && auth=(-H "Authorization: Bearer ${token}")

mkdir -p "${dest}"/{deb,rpm,tarball}
dest="$(cd "${dest}" && pwd)"
curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors --max-time 120 \
  -H "Accept: application/vnd.github+json" ${auth[@]+"${auth[@]}"} \
  "https://api.github.com/repos/${repo}/releases/tags/${tag}" -o "${dest}/release.json" \
  || die "could not read release ${tag} of ${repo}"
[[ -n "${sha}" ]] || sha="$(jq -r '.target_commitish' "${dest}/release.json")"

# kind \t name \t digest \t size \t browser url \t api url
mapfile -t assets < <(jq -r '.assets[]
  | (if (.name | test("^amdrocm-.*\\.deb$")) then "deb"
     elif (.name | test("^amdrocm-.*\\.rpm$")) then "rpm"
     elif (.name | test("^vision-pack-dist-linux-multiarch-.*\\.tar\\.gz$")) then "tarball"
     else empty end) as $kind
  | [$kind, .name, (.digest // ""), (.size | tostring), .browser_download_url, .url] | @tsv' "${dest}/release.json")

declare -A count=([deb]=0 [rpm]=0 [tarball]=0)
total=0
for row in "${assets[@]}"; do
  IFS=$'\t' read -r kind name digest size url api_url <<<"${row}"
  want="${digest#sha256:}"
  [[ "${digest}" == sha256:* && ${#want} -eq 64 ]] || die "${name}: the release API reports no sha256 digest"
  out="${dest}/${kind}/${name}"
  if [[ -f "${out}" && "$(sha256sum "${out}" | cut -d' ' -f1)" == "${want}" ]]; then
    log "${name}: already present and verified"
  else
    log "downloading ${name} (${size} bytes)"
    rm -f "${out}.part"
    if ! curl -fsSL --retry 5 --retry-delay 10 --retry-all-errors --max-time 1800 -o "${out}.part" "${url}"; then
      # Private repositories only serve assets through the API.
      [[ -n "${token}" ]] || die "download of ${name} failed"
      curl -fsSL --retry 5 --retry-delay 10 --retry-all-errors --max-time 1800 -o "${out}.part" \
        -H "Accept: application/octet-stream" "${auth[@]}" "${api_url}" || die "download of ${name} failed"
    fi
    got="$(sha256sum "${out}.part" | cut -d' ' -f1)"
    [[ "${got}" == "${want}" ]] || { rm -f "${out}.part"; die "${name}: sha256 ${got} != release digest ${want}"; }
    mv "${out}.part" "${out}"
  fi
  count[${kind}]=$((count[${kind}] + 1))
  total=$((total + size))
done

problems=()
[[ "${count[deb]}" == "${expect_deb}" ]] || problems+=("expected ${expect_deb} DEBs, found ${count[deb]}")
[[ "${count[rpm]}" == "${expect_rpm}" ]] || problems+=("expected ${expect_rpm} RPMs, found ${count[rpm]}")
[[ "${count[tarball]}" == "${expect_tarball}" ]] || problems+=("expected ${expect_tarball} tarball, found ${count[tarball]}")

shopt -s nullglob
tarballs=("${dest}"/tarball/vision-pack-dist-linux-multiarch-*.tar.gz)
shopt -u nullglob
[[ ${#tarballs[@]} -ge 1 ]] || die "no dist tarball in ${tag}"
tarball="${tarballs[0]}"
version="$(basename "${tarball}" | sed -E 's/^vision-pack-dist-linux-multiarch-(.+)\.tar\.gz$/\1/')"
date="${tag#nightly-}"
tar -xzOf "${tarball}" ./share/vision-pack/vision-pack-manifest.json >"${dest}/manifest.json" 2>/dev/null \
  || tar -xzOf "${tarball}" share/vision-pack/vision-pack-manifest.json >"${dest}/manifest.json" \
  || die "the tarball has no share/vision-pack/vision-pack-manifest.json"
manifest_sha="$(jq -r '.sha // empty' "${dest}/manifest.json")"
[[ "${manifest_sha}" == "${sha}" ]] || problems+=("tarball manifest sha ${manifest_sha:-missing} != tag commit ${sha}")

(cd "${dest}" && find deb rpm tarball -type f ! -name '*.part' -print0 | sort -z | xargs -0 sha256sum) >"${dest}/SHA256SUMS"
jq -n --arg tag "${tag}" --arg version "${version}" --arg date "${date}" --arg sha "${sha}" \
  --argjson deb "${count[deb]}" --argjson rpm "${count[rpm]}" --argjson tarball "${count[tarball]}" \
  --argjson bytes "${total}" --arg sdk "$(jq -r '.rocm_sdk // ""' "${dest}/manifest.json")" \
  '{tag:$tag, version:$version, date:$date, sha:$sha, assets:{deb:$deb, rpm:$rpm, tarball:$tarball},
    total_bytes:$bytes, build_sdk:$sdk}' >"${dest}/fetch.json"

for p in ${problems[@]+"${problems[@]}"}; do echo "::error::fetch-release: ${p}" >&2; done
[[ ${#problems[@]} -eq 0 ]] || exit 1
log "${tag}: ${count[deb]} DEB + ${count[rpm]} RPM + ${count[tarball]} tarball verified (${version}, ${sha:0:12})"

names=()
if [[ -n "${pack}" ]]; then
  mkdir -p "${pack}"
  for kind in deb rpm tarball; do
    name="vision-pack-${kind}-${version}-${date}"
    extra=()
    [[ "${kind}" == tarball ]] && extra=(release.json manifest.json SHA256SUMS fetch.json)
    tar -cf "${pack}/${name}.tar" -C "${dest}" "${kind}" ${extra[@]+"${extra[@]}"}
    names+=("${name}")
  done
fi

if [[ "${github}" == 1 && -n "${GITHUB_OUTPUT:-}" ]]; then
  {
    echo "version=${version}"
    echo "date=${date}"
    echo "sha=${sha}"
    if [[ ${#names[@]} -eq 3 ]]; then
      echo "deb_artifact=${names[0]}"
      echo "rpm_artifact=${names[1]}"
      echo "tarball_artifact=${names[2]}"
    fi
  } >>"${GITHUB_OUTPUT}"
  {
    echo "### Release assets"
    echo "${count[deb]} DEB, ${count[rpm]} RPM and ${count[tarball]} tarball verified against the release digests"
    echo "($((total / 1048576)) MiB; vision-pack \`${version}\`, commit \`${sha:0:12}\`)."
  } >>"${GITHUB_STEP_SUMMARY:-/dev/null}"
fi
