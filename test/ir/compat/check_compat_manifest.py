"""[72] published compatibility manifest (). Ported verbatim from the retired run_cpp_tests.sh [72]
block ( S5m). COMPATIBILITY.json pins the M4 compatibility surface to VersionInfo.h + the committed
schemas + the language levels; and eight negatives each fail closed: a drifted toolVersion; a drifted
semanticProfileVersion (); an
unsupported declared schema version; a per-contract schema bump in VersionInfo.h; a future-only level
(L2) advertised as supported; a nested unknown field (additionalProperties:false); a malformed
featureFlags value; and a non-object consumers section. Negatives run against a copy of
include/ + docs/ + examples/ + COMPATIBILITY.json, mutated then restored between cases.

Usage: check_compat_manifest.py <validate_compatibility_manifest.py> <examples-dir>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

VCM, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []


def vcm(repo_root):
    return subprocess.run([sys.executable, VCM, "--repo-root", repo_root],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# positive: the committed COMPATIBILITY.json validates against its sources of truth.
if vcm(REPO) != 0:
    fails.append("COMPATIBILITY.json is invalid or drifted from VersionInfo.h / the committed schemas")

# negatives against a mutable copy.
root = tempfile.mkdtemp(prefix="vcm72.")
shutil.copytree(os.path.join(REPO, "include"), os.path.join(root, "include"))
shutil.copytree(os.path.join(REPO, "docs"), os.path.join(root, "docs"))
shutil.copytree(EXAMPLES, os.path.join(root, "examples"))
shutil.copyfile(os.path.join(REPO, "COMPATIBILITY.json"), os.path.join(root, "COMPATIBILITY.json"))
COMPAT = os.path.join(root, "COMPATIBILITY.json")
VINFO = os.path.join(root, "include", "Neutrino", "VersionInfo.h")


def restore_compat():
    shutil.copyfile(os.path.join(REPO, "COMPATIBILITY.json"), COMPAT)


def mutate(fn):
    d = json.load(open(COMPAT))
    fn(d)
    json.dump(d, open(COMPAT, "w"))


def expect_reject(label):
    if vcm(root) == 0:
        fails.append(f"compat validator accepted {label}")
    restore_compat()


mutate(lambda d: d["translator"].__setitem__("toolVersion", "9.9.9"))
expect_reject("a toolVersion drifted from VersionInfo.h")

mutate(lambda d: d.__setitem__("semanticProfileVersion", 99))
expect_reject("a semanticProfileVersion drifted from VersionInfo.h ()")

mutate(lambda d: d["artifactSchemas"].__setitem__("l2DomainSemantics", 99))
expect_reject("an unsupported L2 schema version")

# per-contract schema bump in VersionInfo.h (COMPATIBILITY.json restored to committed).
open(VINFO, "w").write(open(VINFO).read().replace('kSchemaBindingReceipt = "v1"',
                                                  'kSchemaBindingReceipt = "v2"'))
expect_reject("a per-contract schema drift from VersionInfo.h")
shutil.copyfile(os.path.join(REPO, "include", "Neutrino", "VersionInfo.h"), VINFO)


def _l2_supported(d):
    d["language"]["levels"]["supported"] = ["L1", "L2", "L3", "L4", "L5"]
    d["language"]["levels"]["future"] = []


mutate(_l2_supported)
expect_reject("L2 advertised as a supported language level")

mutate(lambda d: d["translator"].__setitem__("extra", "oops"))
expect_reject("an unknown nested field (translator.extra)")

mutate(lambda d: d["featureFlags"].__setitem__("l2TypedProofIntent", "yes"))
expect_reject("a non-boolean featureFlags value")

mutate(lambda d: d.__setitem__("consumers", "oops"))
expect_reject("a non-object consumers section")

if fails:
    print("[72] compat-manifest contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[72] OK: COMPATIBILITY.json pinned to VersionInfo.h + committed schemas + language levels; "
      "drifted toolVersion / drifted semanticProfileVersion / unsupported L2 schema / per-contract "
      "schema drift / L2-as-supported / nested unknown field / malformed featureFlags / non-object "
      "consumers each fail closed")
