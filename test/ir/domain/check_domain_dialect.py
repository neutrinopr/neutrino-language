"""[35] D1: neutrino.domain-dialect validation. Ported verbatim from the retired run_cpp_tests.sh [35]
block ( S5k). The reviewed sponsored_finance dialect validates and its pinned domainDialectHash
matches the validator's canonical hash; the hash is canonicalization-stable (key reordering hashes
identically); eight schema/provenance/ref/hash negatives each fail closed with their specific code; and
a `version` bump must be RE-PINNED — a stale-hash bump is caught, a re-pinned bump validates.

Usage: check_domain_dialect.py <validate_domain_dialect.py> <domain-dialects-dir>
"""
import json
import os
import subprocess
import sys
import tempfile

DD, DDEX = sys.argv[1:3]
fails = []
tmp = tempfile.mkdtemp(prefix="dd35.")
DIALECT = os.path.join(DDEX, "sponsored_finance.dialect.json")


def validate(dialect, out):
    r = subprocess.run([sys.executable, DD, "--dialect", dialect, "--out", out],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode


def report(out):
    return json.load(open(os.path.join(out, "domain-dialect.report.json")))


def diags(out):
    return open(os.path.join(out, "diagnostics.json")).read()


# positive: reviewed dialect validates + pinned hash == computed canonical hash (64 hex).
ok_out = os.path.join(tmp, "dd_ok")
if validate(DIALECT, ok_out) != 0:
    fails.append("reviewed dialect did not validate")
else:
    r = report(ok_out)
    d = json.load(open(DIALECT))
    if not (r["ok"] and r["domainDialectHash"] == d["domainDialectHash"] and len(r["domainDialectHash"]) == 64):
        fails.append("pinned domainDialectHash != computed canonical hash")

# canonicalization-stable: re-serialized (reversed keys) input hashes identically.
reordered = os.path.join(tmp, "dd_reordered.json")
d = json.load(open(DIALECT))
json.dump(dict(reversed(list(d.items()))), open(reordered, "w"), indent=0)
re_out = os.path.join(tmp, "dd_re")
validate(reordered, re_out)
try:
    if report(ok_out)["domainDialectHash"] != report(re_out)["domainDialectHash"]:
        fails.append("domainDialectHash not stable under key reordering (canonicalization broken)")
except (OSError, KeyError):
    fails.append("reordered dialect did not produce a report")

# negatives: each fails closed (exit 1) with its specific diagnostic code.
for fixture, code in [
    ("unknown_field.dialect.json", "dialect.schema"),
    ("missing_provenance.dialect.json", "dialect.missing_provenance"),
    ("dangling_edge.dialect.json", "dialect.dangling_edge_ref"),
    ("hash_mismatch.dialect.json", "dialect.hash_mismatch"),
    ("terms_not_object.dialect.json", "dialect.schema"),
    ("unaccepted_provenance.dialect.json", "dialect.unaccepted_provenance"),
    ("redefines_core_concept.dialect.json", "dialect.redefines_core"),
    ("redefines_value_type.dialect.json", "dialect.redefines_core"),
]:
    out = os.path.join(tmp, "dd_neg")
    rc = validate(os.path.join(DDEX, "negatives", fixture), out)
    if rc != 1:
        fails.append(f"{fixture} exit={rc} (want 1)")
    elif ('"' + code + '"') not in diags(out):
        fails.append(f"{fixture} missing diagnostic {code}")

# version bump must be re-pinned: (a) bump version + keep old hash -> hash_mismatch.
stale = os.path.join(tmp, "dd_vbump_stale.json")
d = json.load(open(DIALECT))
d["version"] = "0.2.0"
json.dump(d, open(stale, "w"))
vbs = os.path.join(tmp, "dd_vbs")
if not (validate(stale, vbs) == 1 and '"dialect.hash_mismatch"' in diags(vbs)):
    fails.append("version bump with a stale hash was not caught")

# (b) re-pin: bump version, drop hash (validator computes), embed the computed digest -> validates.
nohash = os.path.join(tmp, "dd_vbump_nohash.json")
d = json.load(open(stale))
d.pop("domainDialectHash", None)
json.dump(d, open(nohash, "w"))
vbn = os.path.join(tmp, "dd_vbn")
if validate(nohash, vbn) != 0:
    fails.append("version bump (unpinned) did not validate")
else:
    repinned = os.path.join(tmp, "dd_vbump_repinned.json")
    d = json.load(open(nohash))
    d["domainDialectHash"] = report(vbn)["domainDialectHash"]
    json.dump(d, open(repinned, "w"))
    if validate(repinned, os.path.join(tmp, "dd_vbr")) != 0:
        fails.append("re-pinned version bump did not validate")

if fails:
    print("[35] domain-dialect contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[35] OK: reviewed dialect validates + hash-pinned + canonicalization-stable; unknown-field / "
      "missing-provenance / dangling-ref / hash-mismatch / non-object-container / unaccepted-provenance "
      "/ redefines-core [keyword + value-type] all fail closed; version bump must be re-pinned")
