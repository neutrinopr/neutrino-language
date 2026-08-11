"""[54] M2 compatibility checker (). Ported verbatim from the retired run_cpp_tests.sh [54] block
( S5m). The current tool surface (from --version-json AND a generated manifest.json's
translatorVersion) satisfies the example component-compatibility-manifest; and dialect / schema /
tool-major drift, plus a truncated or typoed (additionalProperties:false, incl. nested agents/network)
requirement manifest, each fail closed — never read as compatible.

Usage: check_compat_checker.py <check_compatibility.py> <neutrino-translate> <neutrino-gen> <component-compat-manifest> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

CHK, TRANSLATE, GEN, CCM, EXAMPLES = sys.argv[1:6]
fails = []
tmp = tempfile.mkdtemp(prefix="compat54.")


def check_ok(have, require):
    return subprocess.run([sys.executable, CHK, "--have", have, "--require", require],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# the --version-json surface.
have = os.path.join(tmp, "have.json")
with open(have, "w") as f:
    if subprocess.run([TRANSLATE, "--version-json"], stdout=f, stderr=subprocess.DEVNULL).returncode != 0:
        fails.append("--version-json for compat check failed")

# a generated manifest.json also carries a valid translatorVersion --have surface.
msi = os.path.join(EXAMPLES, "domains", "core_sample_installment")
slot = os.path.join(tmp, "vercheck")
subprocess.run([GEN, "--target=slot",
                "--scenario=" + os.path.join(msi, "scenario", "core_sample_installment_happy_path.json"),
                os.path.join(msi, "source", "core_sample_installment.neu"), "-o", slot],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
manifest = os.path.join(slot, "manifest.json")

# positives.
if not check_ok(have, CCM):
    fails.append("checker rejected a compatible surface")
if not check_ok(manifest, CCM):
    fails.append("checker rejected the manifest.json translatorVersion surface")


def reject_require(mutate, label, base=CCM):
    p = os.path.join(tmp, "ccm_" + label + ".json")
    if isinstance(mutate, str):  # raw text override
        open(p, "w").write(mutate)
    else:
        d = json.load(open(base))
        mutate(d)
        json.dump(d, open(p, "w"))
    if check_ok(have, p):
        fails.append(f"checker accepted {label}")


# dialect / schema / tool-major drift.
reject_require(lambda d: d.__setitem__("mlirDialectVersion", "9.9.9"), "dialect")
reject_require(lambda d: d["schemas"].__setitem__("runtimeEvidence", "v2"), "schema")
reject_require(lambda d: d["translator"].__setitem__("toolVersion", "1.0.0"), "tool_major")
# malformed: truncated, typoed top-level, typoed nested network / agents.
reject_require('{"kind":"neutrino.component-compatibility-manifest"}\n', "truncated")


def _typo_top(d):
    del d["mlirDialectVersion"]
    d["mlirDialectVerzion"] = "9.9.9"


reject_require(_typo_top, "typo_top")
reject_require(lambda d: d.__setitem__("network", {"wasmCoreDigset": "sha256:bad"}), "typo_network")
reject_require(lambda d: d.__setitem__("agents", {"sdkVerzion": "9.9.9"}), "typo_agents")

if fails:
    print("[54] compat-checker contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[54] OK: compatible surface accepted from --version-json + manifest.json; dialect/schema/"
      "tool-major drift + truncated/typoed top-level & nested agents/network requirement fail closed")
