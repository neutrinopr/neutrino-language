"""[97] Built-in targets come from TargetRegistry.def; package profiles stay owned.

The C++ registry is expanded from the declarative
include/Neutrino/TargetRegistry.def. `--list-targets` without package inputs
matches that built-in order. A target profile belongs either to a
scenario-bearing built-in row or to an exact extracted-package manifest; the
same target cannot occupy both authorities. Each profile's `target` field must
name its own file's target. Orphan, missing, mis-attached, and mismatched-field
profiles fail closed. Both ordinary and driver-serialized rows participate in
the order, and an unknown future target-row macro fails closed instead of
disappearing from the parsed registry.

Usage: check_target_registry_def.py <neutrino-gen> <examples-dir>
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

GEN, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
DEF = os.path.join(REPO, "include", "Neutrino", "TargetRegistry.def")
REGC = os.path.join(REPO, "lib", "emit", "TargetRegistry.cpp")
PROFILES = os.path.join(EXAMPLES, "target-profiles")
EXTERNAL_PROFILE_MANIFESTS = {
    "solidity": os.path.join(
        REPO, "packaging", "solidity", "extraction-manifest.json"
    ),
}

TARGET_MACRO = re.compile(
    r'^(NEUTRINO_TARGET(?:_[A-Z0-9_]+)?)\s*\(\s*"'
)
ROWS = {
    "NEUTRINO_TARGET": re.compile(
        r'^NEUTRINO_TARGET\(\s*"([^"]+)"\s*,\s*\w+\s*,'
        r'\s*/\*gated=\*/\s*(true|false)\s*,'
        r'\s*/\*scenarioFree=\*/\s*(true|false)\s*\)$'
    ),
    "NEUTRINO_TARGET_DRIVER": re.compile(
        r'^NEUTRINO_TARGET_DRIVER\(\s*"([^"]+)"\s*,'
        r'\s*/\*gated=\*/\s*(true|false)\s*,'
        r'\s*/\*scenarioFree=\*/\s*(true|false)\s*\)$'
    ),
}


class RegistryParseError(RuntimeError):
    pass


def parse_rows(path):
    """Return (name, gated, scenarioFree) rows, rejecting unknown row macros."""
    parsed = []
    for lineno, line in enumerate(open(path), 1):
        stripped = line.strip()
        call = TARGET_MACRO.match(stripped)
        if not call:
            continue
        macro = call.group(1)
        row_parser = ROWS.get(macro)
        if row_parser is None:
            raise RegistryParseError(
                f"{path}:{lineno}: unknown target row macro {macro}"
            )
        row = row_parser.match(stripped)
        if row is None:
            raise RegistryParseError(
                f"{path}:{lineno}: malformed {macro} row"
            )
        parsed.append(
            (row.group(1), row.group(2) == "true", row.group(3) == "true")
        )
    return parsed

if not os.path.isfile(DEF):
    print("[97] FAIL: the declarative target source (TargetRegistry.def) is missing", file=sys.stderr)
    sys.exit(1)

# anti-backslide: the C++ registry EXPANDS the .def, not a hand-coded table.
regc = open(REGC).read()
if '#include "Neutrino/TargetRegistry.def"' not in regc:
    fails.append("TargetRegistry.cpp does not expand the declarative source (TargetRegistry.def)")
if re.search(r'\{"(solidity|postgres|slot|views)",', regc):
    fails.append("TargetRegistry.cpp still hand-codes a target table row instead of expanding the .def")

try:
    defs = parse_rows(DEF)
except RegistryParseError as error:
    fails.append(str(error))
    defs = []
if len(defs) < 12:
    fails.append(
        f"parsed only {len(defs)} known target rows from the .def (need >=12)"
    )
def_names = [d[0] for d in defs]


def reconcile(prof_dir):
    """Return an error, or None if built-in and package profiles reconcile."""
    profiled = {os.path.basename(p).replace(".target-profile.json", "")
                for p in glob.glob(os.path.join(prof_dir, "*.target-profile.json"))}
    builtins = {n for (n, gated, sf) in defs if gated and not sf}
    external = set(EXTERNAL_PROFILE_MANIFESTS)
    overlap = builtins & external
    if overlap:
        return f"target profile has built-in and package authority: {sorted(overlap)}"
    for target, manifest_path in EXTERNAL_PROFILE_MANIFESTS.items():
        try:
            manifest = json.load(open(manifest_path))
        except (OSError, ValueError) as error:
            return f"cannot read package profile manifest for {target}: {error}"
        profile_path = f"examples/target-profiles/{target}.target-profile.json"
        paths = {
            row.get("path")
            for group in manifest.get("groups", {}).values()
            for row in group
            if isinstance(row, dict)
        }
        if profile_path not in paths:
            return f"package manifest for {target} does not own {profile_path}"
    expected = builtins | external
    if profiled - expected:
        return f"target-profile(s) without built-in/package authority: {sorted(profiled - expected)}"
    if profiled != expected:
        return f"profile/authority drift — profiles={sorted(profiled)} vs owned={sorted(expected)}"
    for p in glob.glob(os.path.join(prof_dir, "*.target-profile.json")):
        want = os.path.basename(p).replace(".target-profile.json", "")
        if json.load(open(p)).get("target") != want:
            return f"{os.path.basename(p)} declares a target != '{want}' (profile/registry drift)"
    return None


# (a) --list-targets == .def order, then any externally discovered package targets.
# Since  retired core Solidity dispatch, the catalog is core registry PLUS
# verified packages found by discovery (M7_BACKEND_PACKAGE_BOUNDARY_ADR). The .def
# contract is still asserted exactly -- the core prefix must match .def order
# element for element -- and discovered targets may only APPEND, never reorder or
# displace a core entry.
r = subprocess.run([GEN, "--list-targets"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
listed = [t.strip() for t in r.stdout.decode().splitlines() if t.strip()]
if r.returncode != 0:
    fails.append("--list-targets failed")
else:
    core_prefix = listed[:len(def_names)]
    discovered = listed[len(def_names):]
    if core_prefix != def_names:
        fails.append(
            f"--list-targets core prefix {core_prefix} != TargetRegistry.def order {def_names}")
    if set(discovered) & set(def_names):
        fails.append(
            f"externally discovered target(s) duplicate a core registry entry: {discovered}")

# (b) profile <-> registry reconciliation on the committed profiles.
err = reconcile(PROFILES)
if err:
    fails.append("TargetRegistry.def reconciliation: " + err)

# negative: a profile whose `target` field is mutated to a DIFFERENT registered target must be rejected.
tmp = tempfile.mkdtemp(prefix="def97.")

# Negative: a future target-row macro must fail closed. Silently ignoring it
# would let --list-targets and the checker's registry order diverge again.
future_def = os.path.join(tmp, "TargetRegistry.future.def")
with open(future_def, "w") as out:
    out.write(open(DEF).read())
    out.write(
        '\nNEUTRINO_TARGET_FUTURE("future-target", '
        "/*gated=*/false, /*scenarioFree=*/true)\n"
    )
try:
    parse_rows(future_def)
except RegistryParseError as error:
    if "unknown target row macro NEUTRINO_TARGET_FUTURE" not in str(error):
        fails.append(f"unknown target-row macro emitted the wrong diagnostic: {error}")
else:
    fails.append("an unknown future target-row macro was silently ignored")

badprof = os.path.join(tmp, "badprof")
shutil.copytree(PROFILES, badprof)
solp = os.path.join(badprof, "solidity.target-profile.json")
d = json.load(open(solp))
d["target"] = "postgres"
json.dump(d, open(solp, "w"))
if reconcile(badprof) is None:
    fails.append("a profile with a mismatched 'target' field (solidity claiming postgres) was not caught")

if fails:
    print("[97] target-registry-def contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[97] OK: TargetRegistry.cpp expands the built-in .def; --list-targets matches its order; "
      "profiles have one exact built-in or extracted-package authority and matching target fields; "
      "orphan/missing/mis-attached/mismatched-field profiles and unknown future row macros fail closed")
