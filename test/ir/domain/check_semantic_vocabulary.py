""" slice 2: the closed semantic-feature vocabulary is COMPILER-OWNED and
published as ONE artifact. Regenerating `--semantic-feature-vocabulary`
byte-matches the committed docs/semantic-feature-vocabulary.json; the artifact's
shape holds (schemaVersion/kind, a positive semanticProfileVersion equal to the
compiler's --version-json, and a non-empty, sorted, unique, well-formed feature
set); and the Python target-profile validator's closed registry EQUALS the
artifact (no hand-maintained parallel table drifts from the C++).

Usage: check_semantic_vocabulary.py <neutrino-translate> <committed-vocab.json> <scripts-dir>
"""
import json
import os
import re
import subprocess
import sys

TRANSLATE, COMMITTED, SCRIPTS = sys.argv[1:4]
FEATURE_RE = re.compile(r"^[a-z][a-z_]*:[a-z][a-z0-9_]*$")
fails = []


def run(*cmd):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


# (a) compiler-owned: regenerating byte-matches the committed artifact.
r = run(TRANSLATE, "--semantic-feature-vocabulary")
if r.returncode != 0:
    fails.append("--semantic-feature-vocabulary command failed")
elif open(COMMITTED, "rb").read() != r.stdout:
    fails.append("docs/semantic-feature-vocabulary.json drifted from the compiler (regenerate it)")

# (b) shape + invariants.
vocab = {}
try:
    vocab = json.loads(r.stdout)
except ValueError:
    fails.append("vocabulary is not valid JSON")

feats = vocab.get("features")
ver = vocab.get("semanticProfileVersion")
if vocab.get("schemaVersion") != 1 or vocab.get("kind") != "neutrino.semantic-feature-vocabulary":
    fails.append("vocabulary schemaVersion/kind is wrong")
if not (isinstance(ver, int) and not isinstance(ver, bool) and ver >= 1):
    fails.append("semanticProfileVersion must be a positive integer")
if not (isinstance(feats, list) and feats):
    fails.append("features must be a non-empty array")
else:
    if feats != sorted(feats):
        fails.append("features must be sorted")
    if len(feats) != len(set(feats)):
        fails.append("features must be unique")
    for f in feats:
        if not (isinstance(f, str) and FEATURE_RE.match(f)):
            fails.append(f"feature {f!r} is not a <dimension>:<value> string")

# (c) the compiler's semanticProfileVersion equals the version envelope's (both
#     are kSemanticProfileVersion — a mismatch means the emitters diverged).
rv = run(TRANSLATE, "--version-json")
try:
    vj = json.loads(rv.stdout)
    if vj.get("semanticProfileVersion") != ver:
        fails.append(f"vocabulary semanticProfileVersion {ver} != --version-json {vj.get('semanticProfileVersion')}")
except ValueError:
    fails.append("--version-json is not valid JSON")

# (d) the Python target-profile validator consumes the SAME artifact — its closed
#     registry must equal the published features (the single-source guarantee: no
#     hand-copied table can silently drift from knownSemanticFeatures()).
sys.path.insert(0, os.path.join(SCRIPTS, "validators"))
try:
    import validate_target_profile as vtp  # noqa: E402
    if set(vtp.SEMANTIC_FEATURE_REGISTRY) != set(feats or []):
        fails.append("validate_target_profile.SEMANTIC_FEATURE_REGISTRY drifted from the published vocabulary")
    if vtp.SEMANTIC_PROFILE_VERSION != ver:
        fails.append("validate_target_profile.SEMANTIC_PROFILE_VERSION drifted from the published vocabulary")
except Exception as e:  # noqa: BLE001
    fails.append(f"could not load validate_target_profile: {e}")

if fails:
    print("semantic-vocabulary check FAILED:", file=sys.stderr)
    for f in fails:
        print(f"    {f}", file=sys.stderr)
    sys.exit(1)
print(f"semantic-vocabulary OK: {len(feats)} closed features, semanticProfileVersion {ver}, "
      "byte-matched to the compiler; Python registry in sync")
