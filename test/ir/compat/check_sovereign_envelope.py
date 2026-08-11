"""[73] sovereign-lowering envelope (). Ported verbatim from the retired run_cpp_tests.sh [73] block
( S5m). The official-translator envelope validates (shape + consumer compatibility + real artifact
hashes) and is consumable by check_compatibility.py directly (no parallel manifest); an incompatible IR
dialect, a missing source language version, an absolute or traversal artifact path (POSIX & Windows), and
a malformed sourceHash / capabilityVersion each fail closed; and the PUBLISHED schema path pattern (the
downstream contract) rejects the same paths as the reference validator, so a schema-only consumer does
not fail open.

Usage: check_sovereign_envelope.py <validate_sovereign_envelope.py> <check_compatibility.py> <examples-dir> <schema-path>
"""
import json
import os
import re
import subprocess
import sys

VSE, CHK, EXAMPLES, SCHEMA = sys.argv[1:5]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
SLE = os.path.join(EXAMPLES, "sovereign-lowering")
fails = []


def ok(*args):
    return subprocess.run([sys.executable, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


env = os.path.join(SLE, "core_promo_campaign.envelope.json")
req = os.path.join(SLE, "consumer-requirement.json")

# positive: the official envelope validates (shape + compat + hashes).
if not ok(VSE, "--envelope", env, "--require", req, "--verify-hashes", "--repo-root", REPO):
    fails.append("the official sovereign-lowering envelope did not validate (shape/compat/hashes)")
# the console consumes the SAME envelope via check_compatibility.py (no parallel manifest).
if not ok(CHK, "--have", env, "--require", req):
    fails.append("check_compatibility.py could not consume the sovereign envelope as --have")


def neg(label, args):
    if ok(VSE, *args):
        fails.append(f"consumer accepted {label}")


def n(name):
    return os.path.join(SLE, "negatives", name + ".envelope.json")


# incompatible dialect / missing language version.
neg("an envelope with an incompatible mlirDialectVersion",
    ["--envelope", n("incompatible-dialect"), "--require", req, "--repo-root", REPO])
neg("an envelope missing source.languageVersion",
    ["--envelope", n("missing-language-version"), "--repo-root", REPO])
# artifact path escaping the import root (absolute / traversal), even with --verify-hashes.
for bad in ("absolute-artifact-path", "traversal-artifact-path"):
    neg(f"an artifact path escaping the import root ({bad})",
        ["--envelope", n(bad), "--verify-hashes", "--artifact-root", "/tmp/nonexistent-root"])
# malformed sourceHash / capabilityVersion.
for bad in ("malformed-source-hash", "malformed-capability-version"):
    neg(f"a malformed envelope ({bad})", ["--envelope", n(bad), "--repo-root", REPO])

# schema-pattern self-check: the published path pattern rejects POSIX + Windows absolute paths and
# '/' or '\\' traversal, matching the reference validator.
sch = json.load(open(SCHEMA))
pat = sch["properties"]["artifacts"]["items"]["properties"]["path"]["pattern"]
ref = sch["properties"]["diagnostics"]["properties"]["ref"]["pattern"]
if pat != ref:
    fails.append("artifacts[].path and diagnostics.ref patterns diverged")
reject = ["/tmp/x", "C:\\tmp\\x.json", "..\\secret.json", "../../etc/passwd", "a/../b", "a\\..\\b"]
accept = ["a/b.json", "test/ir/samples/Inputs/core_promo_campaign/generated/slot/capability.json"]
bad = [s for s in reject if re.match(pat, s)] + [s for s in accept if not re.match(pat, s)]
if bad:
    fails.append(f"schema path pattern not aligned with the validator: {bad}")

if fails:
    print("[73] sovereign-envelope contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[73] OK: official output wraps + validates shape/compat/hashes and is consumable by "
      "check_compatibility.py directly; incompatible-dialect / missing-language-version / "
      "absolute+traversal artifact paths / malformed sourceHash+capabilityVersion each fail closed; "
      "the published schema path pattern matches the validator")
