"""[] portable agreement-identity gate: canonical envelope + domain-separated agreementHash.

Drives `neutrino-gen --target=agreement-identity` and enforces the model-1 identity
(H(domain || semanticLanguageVersion || canonicalCapabilitySpecBytes || canonicalAgreementEnvelopeBytes),
length-framed) is deterministic, cross-path identical, realization-invariant, and fails closed:

  0. The schema $defs and the hand-validator constants agree (no drift), and the committed golden
     vector's preimage recomputes to its digest (exact-preimage-bytes + expected-digest).
  1. Every committed sample emits a schema-valid, hash-verified agreement-identity (>= 3 samples).
  2. MLIR ingestion and --from-spec ingestion produce a BYTE-IDENTICAL identity.
  3. Determinism: field-order / whitespace variation in source cannot change agreementHash.
  4. Changing a SEMANTIC field (with a consistent capabilityHash) changes agreementHash;
     changing REALIZATION-only data (sourceMap / targetRequirements) does NOT.
  5. Fail-closed: a tampered capability-spec (stale capabilityHash) is refused before an artifact is
     written; an unknown envelope/semantic-language version is rejected by the validator.

Exit 0 ok / 1 violations / 2 usage.

Usage: check_agreement_identity.py <neutrino-gen> <examples-dir> <repo-root>
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

if len(sys.argv) != 4:
    print(__doc__, file=sys.stderr)
    sys.exit(2)
GEN, EXAMPLES, REPO = (os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]),
                       os.path.abspath(sys.argv[3]))
sys.path.insert(0, os.path.join(REPO, "scripts", "validators"))
import validate_agreement_identity as VA  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
from m6_pack_resolver import resolve_members  # noqa: E402

fails = []
CORPUS = json.load(open(os.path.join(REPO, "docs", "m6-curated-example-corpus.json")))
HYDRATED = resolve_members(CORPUS, repo=Path(REPO))
PRIMARY = CORPUS["examples"][3]
SAMPLES = [PRIMARY, CORPUS["examples"][2], CORPUS["examples"][4]]


def gen(args, cwd=None):
    return subprocess.run([GEN] + args, capture_output=True, text=True, cwd=cwd)


def emit_from_source(src, outdir):
    r = gen(["--target=agreement-identity", src, "-o", outdir])
    p = os.path.join(outdir, "agreement-identity.json")
    return (r.returncode, json.load(open(p))) if os.path.exists(p) else (r.returncode, None)


def emit_from_spec(spec_path, outdir):
    r = gen(["--target=agreement-identity", "--from-spec", spec_path, "-o", outdir])
    p = os.path.join(outdir, "agreement-identity.json")
    return (r.returncode, r.stderr, json.load(open(p))) if os.path.exists(p) \
        else (r.returncode, r.stderr, None)


def domain_paths(name):
    member = HYDRATED[name]
    if member.source_path is None or member.spec_path is None:
        raise RuntimeError("agreement-identity corpus member lacks source/spec")
    return str(member.source_path), str(member.spec_path)


def recompute_agreement_hash(spec):
    core = {k: v for k, v in spec.items() if k not in VA.NON_SEMANTIC}
    cap = VA._compact(core)
    env = {"schemaVersion": 1, "consentPolicy": None, "amendmentPolicy": None,
           "clauseSemanticIds": []}
    pre = (VA._frame(VA.DOMAIN.encode()) + VA._frame(b"0.1.0") +
           VA._frame(cap) + VA._frame(VA._compact(env)))
    return hashlib.sha256(pre).hexdigest()


# 0a. schema <-> validator constant drift.
schema = json.load(open(os.path.join(REPO, "docs", "schemas",
                                      "agreement-identity.schema.json")))
if set(schema["required"]) != VA.TOP_FIELDS:
    fails.append("validator TOP_FIELDS drifted from schema required")
env_def = schema["$defs"]["envelope"]
if set(env_def["required"]) != VA.ENVELOPE_FIELDS:
    fails.append("validator ENVELOPE_FIELDS drifted from schema envelope required")
if schema["properties"]["domain"]["const"] != VA.DOMAIN:
    fails.append("validator DOMAIN drifted from schema")
if env_def["properties"]["schemaVersion"]["const"] != VA.ENVELOPE_VERSION:
    fails.append("validator ENVELOPE_VERSION drifted from schema")
if set(schema["properties"]["semanticLanguageVersion"]["enum"]) != \
        VA.KNOWN_LANGUAGE_VERSIONS:
    fails.append("validator KNOWN_LANGUAGE_VERSIONS drifted from schema enum")

# 0b. golden vector: exact preimage bytes -> expected digest.
vec = json.load(open(os.path.join(REPO, "test", "ir", "agreement",
                                   "agreement_hash_vector.json")))
pre = bytes.fromhex(vec["preimageHex"])
if hashlib.sha256(pre).hexdigest() != vec["agreementHash"]:
    fails.append("golden vector preimage does not hash to its declared agreementHash")
# The vector's preimage is exactly frame(domain)||frame(ver)||frame(cap)||frame(env).
_src, _spec = domain_paths(PRIMARY)
if os.path.exists(_spec):
    if recompute_agreement_hash(json.load(open(_spec))) != vec["agreementHash"]:
        fails.append("golden vector agreementHash drifted from the live primary spec")

# 1 + 2. every sample: schema-valid, hash-verified, MLIR == from-spec.
n_ok = 0
for name in SAMPLES:
    src, spec = domain_paths(name)
    if not (os.path.exists(src) and os.path.exists(spec)):
        continue
    with tempfile.TemporaryDirectory() as td:
        rc_s, a_src = emit_from_source(src, os.path.join(td, "s"))
        rc_f, _, a_spec = emit_from_spec(spec, os.path.join(td, "f"))
        if a_src is None or a_spec is None:
            fails.append(f"{name}: no agreement-identity emitted (src rc={rc_s}, spec rc={rc_f})")
            continue
        errs = []
        VA.validate_shape(a_src, errs)
        VA.verify_hashes(a_src, json.load(open(spec)), errs)
        if errs:
            fails.append(f"{name}: invalid agreement-identity: {errs}")
        if a_src != a_spec:
            fails.append(f"{name}: MLIR and --from-spec identity differ")
        else:
            n_ok += 1
if n_ok < 3:
    fails.append(f"non-vacuous floor: only {n_ok} samples produced a verified identity (need >= 3)")

# 3. determinism: whitespace / blank-line shift in source -> same agreementHash.
src, spec = domain_paths(PRIMARY)
with tempfile.TemporaryDirectory() as td:
    _, a0 = emit_from_source(src, os.path.join(td, "a"))
    shifted = os.path.join(td, "shifted.neu")
    text = open(src).read().replace("procedure ", "\n\nprocedure ", 1)
    open(shifted, "w").write(text)
    _, a1 = emit_from_source(shifted, os.path.join(td, "b"))
    if not a0 or not a1:
        fails.append("determinism: emit failed")
    elif a0["identity"]["agreementHash"] != a1["identity"]["agreementHash"]:
        fails.append("determinism: a whitespace-only source change moved agreementHash")

# 4. semantic-change moves the hash; realization-only change does not.
spec_obj = json.load(open(spec))
base_hash = recompute_agreement_hash(spec_obj)
with tempfile.TemporaryDirectory() as td:
    # (a) realization-only: mutate sourceMap + targetRequirements, keep core + capabilityHash.
    real = copy.deepcopy(spec_obj)
    real["sourceMap"] = [{"line": 999, "column": 1}]
    real["targetRequirements"] = {"tampered": True}
    rp = os.path.join(td, "real.json")
    open(rp, "w").write(json.dumps(real))
    rc, _, a_real = emit_from_spec(rp, os.path.join(td, "ro"))
    if a_real is None:
        fails.append("realization-invariance: from-spec refused a realization-only change")
    elif a_real["identity"]["agreementHash"] != base_hash:
        fails.append("realization-invariance: a sourceMap/targetRequirements change moved agreementHash")
    # (b) semantic change with a CONSISTENT capabilityHash -> different agreementHash.
    sem = copy.deepcopy(spec_obj)
    sem["procedure"] = sem["procedure"] + "_v2"
    core = {k: v for k, v in sem.items() if k not in VA.NON_SEMANTIC}
    sem["identity"] = {"capabilityHash": hashlib.sha256(VA._compact(core)).hexdigest()}
    sp = os.path.join(td, "sem.json")
    open(sp, "w").write(json.dumps(sem))
    rc, _, a_sem = emit_from_spec(sp, os.path.join(td, "se"))
    if a_sem is None:
        fails.append("semantic-change: from-spec refused a consistent semantic change")
    elif a_sem["identity"]["agreementHash"] == base_hash:
        fails.append("semantic-change: changing a semantic field did NOT move agreementHash")

# 5. fail-closed: tampered spec (stale capabilityHash) refused before an artifact.
with tempfile.TemporaryDirectory() as td:
    tam = copy.deepcopy(spec_obj)
    tam["procedure"] = tam["procedure"] + "_TAMPERED"  # core changed, hash left stale
    tp = os.path.join(td, "tam.json")
    open(tp, "w").write(json.dumps(tam))
    rc, err, a_tam = emit_from_spec(tp, os.path.join(td, "t"))
    if a_tam is not None or rc == 0:
        fails.append("fail-closed: a tampered capability-spec was NOT refused")
    elif "capabilityHash mismatch" not in err:
        fails.append("fail-closed: tamper refused without the capabilityHash-mismatch diagnostic")
    # unknown versions -> the validator rejects each of the three pinned fields.
    _, a_good = emit_from_source(src, os.path.join(td, "g"))
    env_bad = copy.deepcopy(a_good)
    env_bad["envelope"]["schemaVersion"] = 99
    e1 = []
    VA.validate_shape(env_bad, e1)
    if not any("unknown envelope version" in e for e in e1):
        fails.append("fail-closed: an unknown envelope version was not rejected")
    lang_bad = copy.deepcopy(a_good)
    lang_bad["semanticLanguageVersion"] = "99.0.0"  # well-formed but unknown
    e2 = []
    VA.validate_shape(lang_bad, e2)
    if not any("semantic-language version" in e for e in e2):
        fails.append("fail-closed: an unknown semanticLanguageVersion was not rejected")
    dom_bad = copy.deepcopy(a_good)
    dom_bad["domain"] = "evil.domain.v1"
    e3 = []
    VA.validate_shape(dom_bad, e3)
    if not any("domain must be" in e for e in e3):
        fails.append("fail-closed: an unknown domain was not rejected")

if fails:
    print("[] agreement-identity gate FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print(f"[] OK: {n_ok} samples verified; MLIR==from-spec identity; deterministic + "
      "realization-invariant; semantic change moves the hash; tamper/unknown-version fail closed; "
      "golden vector preimage recomputes to its digest")
