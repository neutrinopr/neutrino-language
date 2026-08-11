"""[55] M2 release: portable tarball + SHA256SUMS + release-manifest; smoke tests on INSTALLED binaries
(). Ported verbatim from the retired run_cpp_tests.sh [55] block ( S5m). make_release.sh builds
a portable tarball (and a .deb where dpkg-deb exists); the release-manifest lists the 6 tools + an
artifact hash AND embeds the full  --version-json surface under translatorVersion; SHA256SUMS
verifies against the produced artifacts; and the tarball extracts to a bin dir whose INSTALLED binaries
(not the source tree) pass the smoke tests.

Usage: check_release.py <make_release.sh> <smoke_test.sh> <neutrino-gen-path>
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

MAKE_RELEASE, SMOKE, GEN = sys.argv[1:4]
# the cmake tools build dir: .../tools/neutrino-gen/neutrino-gen -> .../tools
TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(GEN)))
fails = []
tmp = tempfile.mkdtemp(prefix="rel55.")
dist = os.path.join(tmp, "dist")


def sh(*args, **kw):
    return subprocess.run(["bash", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


have_deb = shutil.which("dpkg-deb") is not None
rel_cmd = [MAKE_RELEASE, "--tools", TOOLS, "--out", dist]
if have_deb:
    rel_cmd.append("--deb")
if sh(*rel_cmd).returncode != 0:
    print("[55] FAIL: make_release", file=sys.stderr)
    sys.exit(1)

tarballs = [f for f in os.listdir(dist) if f.startswith("neutrino-translator-") and f.endswith(".tar.gz")]
if not tarballs:
    print("[55] FAIL: no tarball produced", file=sys.stderr)
    sys.exit(1)
tarball = os.path.join(dist, sorted(tarballs)[0])

manifest = json.load(open(os.path.join(dist, "release-manifest.json")))

# when the .deb was built, it must be a real package AND recorded in the manifest.
if have_deb:
    debs = [f for f in os.listdir(dist) if f.startswith("neutrino-translator_") and f.endswith(".deb")]
    if not debs:
        fails.append("--deb produced no .deb")
    else:
        if sh("-c", f"dpkg-deb -I {os.path.join(dist, debs[0])}").returncode != 0:
            fails.append("produced .deb is not a valid package")
        if not any(a["type"] == "debian-package" for a in manifest["artifacts"]):
            fails.append(".deb not recorded in release-manifest artifacts")

# release-manifest lists the 6 tools + artifact hash AND embeds the full --version-json surface.
tv = manifest.get("translatorVersion", {})
if not (manifest["kind"] == "neutrino.release-manifest" and manifest["version"] and manifest["gitSha"]
        and len(manifest["tools"]) == 6 and manifest["artifacts"] and manifest["artifacts"][0]["sha256"]
        and tv.get("kind") == "neutrino.translator-version"
        and tv.get("toolVersion") == manifest["version"] and tv.get("gitSha") == manifest["gitSha"]
        and tv.get("languageLevels", {}).get("max") == "L5"
        and {"bindingPolicy", "bindingReceipt", "runtimeEvidence"} <= set(tv.get("schemas", {}))
        and tv.get("mlirDialectVersion") and tv.get("schemaBundleVersion")
        and tv.get("conformanceVectorVersion") and tv.get("compatibilityManifestVersion")):
    fails.append("release-manifest.json shape / translatorVersion surface")

# SHA256SUMS verifies against the produced artifacts.
sums = os.path.join(dist, "SHA256SUMS")
for line in open(sums):
    line = line.strip()
    if not line:
        continue
    digest, name = line.split()[0], line.split()[-1]
    actual = hashlib.sha256(open(os.path.join(dist, name), "rb").read()).hexdigest()
    if actual != digest:
        fails.append(f"SHA256SUMS does not verify for {name}")

# extract into a clean dir and smoke-test the INSTALLED binaries (not the source tree).
extract = os.path.join(tmp, "rel_extract")
os.makedirs(extract)
if sh("-c", f"tar -C {extract} -xzf {tarball}").returncode != 0:
    fails.append("tarball did not extract")
else:
    found = subprocess.run(["find", extract, "-name", "neutrino-gen", "-type", "f"],
                           stdout=subprocess.PIPE).stdout.decode().splitlines()
    if not found:
        fails.append("extracted bin dir not found")
    else:
        bindir = os.path.dirname(found[0])
        if sh(SMOKE, env=dict(os.environ, NEUTRINO_TOOLS_DIR=bindir)).returncode != 0:
            fails.append("smoke tests on installed binaries failed")

if fails:
    print("[55] release contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[55] OK: tarball + SHA256SUMS verify; release-manifest pinned to --version-json; installed-binary "
      "smoke tests pass")
