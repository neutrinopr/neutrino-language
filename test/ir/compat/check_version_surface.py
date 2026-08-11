"""[52] M2 tool version/compatibility surface (). Ported verbatim from the retired run_cpp_tests.sh
[52] block ( S5m). Every shipped tool answers --version-json with a stable, versioned envelope; the
surface is consistent across all tools (same toolVersion/gitSha/mlirDialectVersion — no per-binary
drift); human --version names the tool; the toolVersion pin matches; the agent-facing bundle
--capabilities reports the same version; and a generated artifact's manifest.json pins the same surface.

Usage: check_version_surface.py <translate> <opt> <emit> <gen> <bundle> <equiv> <src.neu> <scenario.json>
"""
import json
import os
import subprocess
import sys
import tempfile

TRANSLATE, OPT, EMIT, GEN, BUNDLE, EQUIV, SRC, SCEN = sys.argv[1:9]
fails = []
tmp = tempfile.mkdtemp(prefix="ver52.")


def version_json(tool):
    r = subprocess.run([tool, "--version-json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None)


rc, v = version_json(TRANSLATE)
if rc != 0 or v is None:
    print("[52] FAIL: neutrino-translate --version-json exited non-zero", file=sys.stderr)
    sys.exit(1)

req = ["schemaVersion", "kind", "tool", "toolVersion", "gitSha", "buildTarget", "languageLevels",
       "mlirDialectVersion", "schemaBundleVersion", "capabilitySpecVersion", "semanticProfileVersion",
       "semanticLanguageVersion", "schemas", "conformanceVectorVersion", "compatibilityManifestVersion"]
if not (v.get("schemaVersion") == 1 and v.get("kind") == "neutrino.translator-version"
        and all(k in v for k in req) and v["toolVersion"] and v["gitSha"] and v["buildTarget"]
        and {"bindingPolicy", "bindingReceipt", "runtimeEvidence"} <= set(v["schemas"])
        and v["capabilitySpecVersion"] and v["languageLevels"]["max"] == "L5"
        and isinstance(v["semanticProfileVersion"], int) and v["semanticProfileVersion"] >= 1
        and isinstance(v["semanticLanguageVersion"], str) and v["semanticLanguageVersion"]
        and "L1" in v["languageLevels"]["supported"]):
    fails.append("--version-json envelope missing required/stable fields")

# consistent across every tool (same toolVersion + gitSha + mlirDialectVersion).
for t in (OPT, EMIT, GEN, BUNDLE, EQUIV):
    rc, b = version_json(t)
    if rc != 0 or b is None:
        fails.append(f"{os.path.basename(t)} --version-json exited non-zero")
        continue
    if not (b["toolVersion"] == v["toolVersion"] and b["gitSha"] == v["gitSha"]
            and b["mlirDialectVersion"] == v["mlirDialectVersion"]):
        fails.append(f"version surface drifts across tools ({os.path.basename(t)})")

# human --version names the tool.
h = subprocess.run([TRANSLATE, "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout.decode()
if "neutrino-translate " not in h:
    fails.append("--version human output missing/not named")

# the toolVersion pin (single source of truth).
if v["toolVersion"] != "0.2.0":
    fails.append(f"toolVersion pin drifted (got {v['toolVersion']})")

# the agent-facing bundle --capabilities reports the SAME version.
rc = subprocess.run([BUNDLE, "--capabilities"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
caps = json.loads(rc.stdout) if rc.stdout.strip() else {}
if caps.get("version") != v["toolVersion"]:
    fails.append("neutrino-bundle --capabilities version != --version-json toolVersion")

# a generated artifact's manifest.json pins the same surface.
vc = os.path.join(tmp, "vercheck")
subprocess.run([GEN, "--target=coverage", "--scenario=" + SCEN, SRC, "-o", vc],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    m = json.load(open(os.path.join(vc, "manifest.json")))
    tv = m.get("translatorVersion", {})
    if not (tv.get("toolVersion") == v["toolVersion"] and tv.get("gitSha") == v["gitSha"]
            and tv.get("mlirDialectVersion") == v["mlirDialectVersion"]
            and tv.get("schemaBundleVersion") == v["schemaBundleVersion"]):
        fails.append("manifest.json translatorVersion pin != --version-json")
except (OSError, ValueError):
    fails.append("gen for manifest version-pin check produced no manifest.json")

if fails:
    print("[52] version-surface contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[52] OK: stable --version-json envelope on every tool; consistent toolVersion/gitSha/dialect; "
      "human --version; --capabilities matches; manifest pins the surface; single-source tool version")
