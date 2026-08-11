""" slice 1: the authoritative capability registry is COMPILER-OWNED and
published as ONE artifact. Regenerating `--capability-registry` byte-matches the
committed docs/semantic-capability-registry.json; the artifact's shape holds
(schemaVersion/kind, a positive semanticProfileVersion equal to the compiler's
--version-json); every record is well-formed and internally consistent (id
pattern, dimension/value split matches the id, category obeys the authoritative
primitive/obligation rule); and the registry's capability-id SET EQUALS the
published closed vocabulary (the single-source guarantee: the registry projects
knownSemanticFeatures() and cannot introduce or drop a capability, so the M7
intake seam anchors against exactly the closed namespace).

Usage: check_capability_registry.py <neutrino-translate> <committed-registry.json> <committed-vocab.json>
"""
import json
import re
import subprocess
import sys

TRANSLATE, REGISTRY, VOCAB = sys.argv[1:4]
ID_RE = re.compile(r"^[a-z][a-z_]*:[a-z][a-z0-9_]*$")
fails = []


def run(*cmd):
    return subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def expected_category(cap_id):
    # The ONE rule semanticFeatureCategory encodes (obligations are the
    # constraint dimensions a coordination must uphold).
    return "obligation" if cap_id.startswith(("invariant:", "replay:")) else "primitive"


# (a) compiler-owned: regenerating byte-matches the committed artifact.
r = run(TRANSLATE, "--capability-registry")
if r.returncode != 0:
    fails.append("--capability-registry command failed")
elif open(REGISTRY, "rb").read() != r.stdout:
    fails.append("docs/semantic-capability-registry.json drifted from the compiler (regenerate it)")

# (b) shape + per-record invariants.
reg = {}
try:
    reg = json.loads(r.stdout)
except ValueError:
    fails.append("registry is not valid JSON")

caps = reg.get("capabilities")
ver = reg.get("semanticProfileVersion")
if reg.get("schemaVersion") != 1 or reg.get("kind") != "neutrino.semantic-capability-registry":
    fails.append("registry schemaVersion/kind is wrong")
if not (isinstance(ver, int) and not isinstance(ver, bool) and ver >= 1):
    fails.append("semanticProfileVersion must be a positive integer")

ids = []
if not (isinstance(caps, list) and caps):
    fails.append("capabilities must be a non-empty array")
else:
    ids = [c.get("id") for c in caps]
    if ids != sorted(ids):
        fails.append("capabilities must be sorted by id")
    if len(ids) != len(set(ids)):
        fails.append("capability ids must be unique")
    for c in caps:
        cid = c.get("id")
        if set(c) != {"id", "dimension", "value", "category"}:
            fails.append(f"capability {cid!r} has unexpected keys {sorted(c)}")
            continue
        if not (isinstance(cid, str) and ID_RE.match(cid)):
            fails.append(f"capability id {cid!r} is not a <dimension>:<value> string")
            continue
        dim, _, val = cid.partition(":")
        if c["dimension"] != dim or c["value"] != val:
            fails.append(f"capability {cid!r} dimension/value does not match its id")
        if c["category"] != expected_category(cid):
            fails.append(f"capability {cid!r} category {c['category']!r} != {expected_category(cid)!r}")

# (c) the compiler's semanticProfileVersion equals the version envelope's.
rv = run(TRANSLATE, "--version-json")
try:
    vj = json.loads(rv.stdout)
    if vj.get("semanticProfileVersion") != ver:
        fails.append(f"registry semanticProfileVersion {ver} != --version-json {vj.get('semanticProfileVersion')}")
except ValueError:
    fails.append("--version-json is not valid JSON")

# (d) single-source guarantee: the registry's capability-id set EQUALS the
#     published closed vocabulary, at the same semanticProfileVersion. The
#     registry is a pure projection of knownSemanticFeatures(); it can neither
#     add nor drop a capability the vocabulary does not carry.
try:
    vocab = json.loads(open(VOCAB, "rb").read())
    if set(ids) != set(vocab.get("features") or []):
        only_reg = sorted(set(ids) - set(vocab.get("features") or []))
        only_voc = sorted(set(vocab.get("features") or []) - set(ids))
        fails.append(f"registry ids drifted from the closed vocabulary: registry-only {only_reg}, vocabulary-only {only_voc}")
    if vocab.get("semanticProfileVersion") != ver:
        fails.append("registry semanticProfileVersion != vocabulary semanticProfileVersion")
except (ValueError, OSError) as e:
    fails.append(f"could not load the committed vocabulary: {e}")

if fails:
    print("capability-registry check FAILED:", file=sys.stderr)
    for f in fails:
        print(f"    {f}", file=sys.stderr)
    sys.exit(1)
print(f"capability-registry OK: {len(ids)} closed capabilities, semanticProfileVersion {ver}, "
      "byte-matched to the compiler; id set equals the published vocabulary")
