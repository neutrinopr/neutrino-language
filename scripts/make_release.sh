#!/usr/bin/env bash
# Assemble the installable translator toolchain release artifacts () from an
# already-built tree: a portable tarball of the six tools, SHA256SUMS, and a
# machine-readable release-manifest.json. Version/identity come from the tools'
# own `--version-json` () — no parallel version story.
#
#   scripts/make_release.sh [--tools <dir>] [--out <dir>] [--label <platform-label>]
#
# Defaults: --tools out/tools (the cmake build layout), --out dist.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_BUILD="$HERE/out/tools"
OUT="$HERE/dist"
LABEL=""
BUILD_DEB=0

while [ $# -gt 0 ]; do
  case "$1" in
    --tools) TOOLS_BUILD="$2"; shift 2 ;;
    --out)   OUT="$2"; shift 2 ;;
    --label) LABEL="$2"; shift 2 ;;
    --deb)   BUILD_DEB=1; shift ;;
    *) echo "usage: make_release.sh [--tools <dir>] [--out <dir>] [--label <platform-label>] [--deb]" >&2; exit 2 ;;
  esac
done

TOOLS="neutrino-opt neutrino-translate neutrino-emit neutrino-gen neutrino-equiv neutrino-bundle"

# Locate each tool: accept either the cmake layout (<dir>/<tool>/<tool>) or a flat
# bin dir (<dir>/<tool>).
tool_path() {
  if [ -x "$TOOLS_BUILD/$1/$1" ]; then echo "$TOOLS_BUILD/$1/$1"
  elif [ -x "$TOOLS_BUILD/$1" ]; then echo "$TOOLS_BUILD/$1"
  else echo ""; fi
}

for t in $TOOLS; do
  [ -n "$(tool_path "$t")" ] || { echo "error: missing built tool '$t' under $TOOLS_BUILD (run 'make build')" >&2; exit 1; }
done

# Version identity from the toolchain itself ().
TRANSLATE="$(tool_path neutrino-translate)"
VER_JSON="$("$TRANSLATE" --version-json)"
ver()  { printf '%s' "$VER_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }
VERSION="$(ver toolVersion)"
GITSHA="$(ver gitSha)"
BUILD_TARGET="$(ver buildTarget)"   # e.g. Linux-x86_64 / Darwin-arm64
PLATFORM="$(printf '%s' "$BUILD_TARGET" | tr 'A-Z' 'a-z' | sed 's/^darwin/macos/')"
[ -n "$LABEL" ] && PLATFORM="$LABEL"

NAME="neutrino-translator-${PLATFORM}-${VERSION}"
STAGE="$OUT/$NAME"
rm -rf "$STAGE"; mkdir -p "$STAGE/bin"

for t in $TOOLS; do
  install -m 0755 "$(tool_path "$t")" "$STAGE/bin/$t"
done
cat > "$STAGE/README.txt" <<TXT
neutrino-translator toolchain ${VERSION} (${GITSHA}, ${BUILD_TARGET})

Tools (add bin/ to PATH, or point NEUTRINO_TOOLS_DIR at it):
  ${TOOLS}

Query the compatibility surface:  bin/neutrino-translate --version-json
Runtime: requires the matching LLVM/MLIR 15 runtime libraries (the .deb declares
this as a dependency; see docs/process/RELEASE.md).

External domain-pack conformance:  conformance/README.txt
TXT

# --- Core contract bundle conformance boundary () ---
# Ship the published bundle, its pinned contract schemas, the diagnostic
# taxonomy, and the stdlib verifier, so an external domain pack validates from
# the PACKAGE ALONE — no translator headers/modules/source.
CONF="$STAGE/conformance"
mkdir -p "$CONF/docs/schemas"
cp "$HERE/docs/core-contract-bundle.json" "$CONF/core-contract-bundle.json"
cp "$HERE/docs/diagnostic-taxonomy.json"  "$CONF/docs/diagnostic-taxonomy.json"
cp "$HERE/docs/semantic-feature-vocabulary.json" "$CONF/docs/semantic-feature-vocabulary.json"
cp "$HERE/docs/semantic-capability-registry.json" "$CONF/docs/semantic-capability-registry.json"
cp "$HERE/scripts/validators/verify_domain_pack.py" "$CONF/verify_domain_pack.py"
python3 - "$HERE" "$CONF" <<'PY'
import json, os, shutil, sys
root, conf = sys.argv[1:3]
b = json.load(open(os.path.join(root, "docs/core-contract-bundle.json")))
for c in b["contracts"]:
    dst = os.path.join(conf, c["path"])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(os.path.join(root, c["path"]), dst)
PY
cat > "$CONF/README.txt" <<'TXT'
Core contract bundle — external domain-pack conformance ().

Validate a domain pack with ONLY python3 (standard library) and this directory
(no translator headers/modules/source checkout):

  python3 verify_domain_pack.py --bundle core-contract-bundle.json \
      --bundle-root . --pack <your-pack.json> --pack-root <your-pack-dir>

The pack pins the exact bundle via targetsBundle.bundleDigest. Domain-pack v2
also binds the complete ordered payload inventory through packDigest and per-file
SHA-256 values. Verification is fail-closed with stable pack.* diagnostics.
TXT

# Portable tarball.
mkdir -p "$OUT"
TARBALL="$OUT/${NAME}.tar.gz"
tar -C "$OUT" -czf "$TARBALL" "$NAME"

# --- Conformance smoke from the EXTRACTED package (no source checkout in scope) ---
SMOKE="$(mktemp -d)"
tar -C "$SMOKE" -xzf "$TARBALL"
PKG="$SMOKE/$NAME/conformance"
python3 - "$SMOKE/pack" "$HERE/test/ir/bundle/Inputs/pack-v2" <<'PY'
import shutil, sys
packdir, fixture = sys.argv[1:3]
shutil.copytree(fixture, packdir)
PY
( cd "$SMOKE" && python3 "$PKG/verify_domain_pack.py" --bundle "$PKG/core-contract-bundle.json" \
    --bundle-root "$PKG" --pack pack/pack.json --pack-root pack ) \
  || { echo "release: core-contract-bundle conformance smoke FAILED (extracted package is not self-contained)" >&2; rm -rf "$SMOKE"; exit 1; }
rm -rf "$SMOKE"

# sha256 helper (Linux sha256sum / macOS shasum).
sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

# Artifacts so far: the portable tarball. Each entry is "<basename>:<type>".
ARTIFACTS=("$(basename "$TARBALL"):portable-tarball")

# Debian package (--deb; needs dpkg-deb, i.e. a Linux build host). Installs the six
# tools to /usr/bin and declares the LLVM/MLIR 15 runtime as a dependency so a clean
# host resolves it via apt.
if [ "$BUILD_DEB" = "1" ]; then
  command -v dpkg-deb >/dev/null 2>&1 || { echo "error: --deb needs dpkg-deb (run on a Debian/Ubuntu host)" >&2; exit 1; }
  ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
  DEBROOT="$OUT/deb/neutrino-translator_${VERSION}_${ARCH}"
  rm -rf "$DEBROOT"; mkdir -p "$DEBROOT/DEBIAN" "$DEBROOT/usr/bin"
  for t in $TOOLS; do install -m 0755 "$(tool_path "$t")" "$DEBROOT/usr/bin/$t"; done
  cat > "$DEBROOT/DEBIAN/control" <<CTL
Package: neutrino-translator
Version: ${VERSION}
Architecture: ${ARCH}
Maintainer: Neutrino <noreply@neutrino.dev>
Section: devel
Priority: optional
Depends: libllvm15
Description: Neutrino translator toolchain (compiler + backend artifact generators).
 Deterministic .neu -> Neutrino MLIR compiler and target generators
 (neutrino-opt/translate/emit/gen/equiv/bundle). Build ${GITSHA}, ${BUILD_TARGET}.
CTL
  DEB="$OUT/neutrino-translator_${VERSION}_${ARCH}.deb"
  dpkg-deb --root-owner-group --build "$DEBROOT" "$DEB" >/dev/null
  rm -rf "$OUT/deb"
  ARTIFACTS+=("$(basename "$DEB"):debian-package")
fi

# SHA256SUMS over every produced artifact.
( cd "$OUT" && : > SHA256SUMS && for e in "${ARTIFACTS[@]}"; do f="${e%%:*}"; echo "$(sha256 "$OUT/$f")  $f" >> SHA256SUMS; done )

# Machine-readable release manifest. Embeds the FULL  --version-json surface
# (under translatorVersion) so a consumer can reconstruct/validate the whole
# language/artifact compatibility contract from the manifest alone.
ARTIFACTS_JSON=""
for e in "${ARTIFACTS[@]}"; do
  f="${e%%:*}"; ty="${e##*:}"
  ARTIFACTS_JSON="${ARTIFACTS_JSON}${f}|${ty}|$(sha256 "$OUT/$f")
"
done
NEUTRINO_VER_JSON="$VER_JSON" NEUTRINO_ARTIFACTS="$ARTIFACTS_JSON" NEUTRINO_CONF="$CONF" \
python3 - "$OUT/release-manifest.json" "$PLATFORM" <<'PY'
import hashlib, json, os, sys
out, platform = sys.argv[1:3]
surface = json.loads(os.environ["NEUTRINO_VER_JSON"])  # the --version-json envelope
arts = []
for line in os.environ["NEUTRINO_ARTIFACTS"].splitlines():
    if not line.strip():
        continue
    name, ty, sha = line.split("|")
    arts.append({"name": name, "sha256": sha, "type": ty})
tools = ["neutrino-opt", "neutrino-translate", "neutrino-emit",
         "neutrino-gen", "neutrino-equiv", "neutrino-bundle"]

def _sha(p):
    return "sha256:" + hashlib.sha256(open(p, "rb").read()).hexdigest()

# The packaged core contract bundle conformance boundary (): its digest,
# self-declared identity/version + internal bundleDigest, and the shipped
# verifier — release-visible so a consumer can pin the exact boundary.
conf = os.environ["NEUTRINO_CONF"]
bundle = json.load(open(os.path.join(conf, "core-contract-bundle.json")))
core_bundle = {
    "path": "conformance/core-contract-bundle.json",
    "sha256": _sha(os.path.join(conf, "core-contract-bundle.json")),
    "bundleId": bundle["bundleId"],
    "bundleVersion": bundle["bundleVersion"],
    "bundleDigest": bundle["bundleDigest"],
    "contractCount": len(bundle["contracts"]),
    "verifier": {"path": "conformance/verify_domain_pack.py",
                 "sha256": _sha(os.path.join(conf, "verify_domain_pack.py"))},
}
json.dump({
    "kind": "neutrino.release-manifest",
    "schemaVersion": 1,
    "version": surface["toolVersion"],
    "gitSha": surface["gitSha"],
    "buildTarget": surface["buildTarget"],
    "platform": platform,
    # the complete  compatibility surface, verbatim
    "translatorVersion": surface,
    "tools": tools,
    "artifacts": arts,
    "coreContractBundle": core_bundle,
}, open(out, "w"), indent=2)
open(out, "a").write("\n")
PY

echo "release: $TARBALL"
echo "         $OUT/SHA256SUMS"
echo "         $OUT/release-manifest.json (version $VERSION, $BUILD_TARGET)"
