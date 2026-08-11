"""[48] dialect registry contract for neutrino_lang.py `dialect`. Ported verbatim from the retired
run_cpp_tests.sh [48] block ( S5j). The wrapper surfaces a domain-dialect registry (terms +
templates with rolled-up status + resolved provenance) from a VALIDATOR-verified artifact; a stale
(hash-mismatched) or missing artifact fails closed; and a YAML-authored dialect renders via the
validator's normalized output (not the raw source), where PyYAML is available.

Usage: check_dialect.py <neutrino_lang.py> <dialect.json> <hash_mismatch.json>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

LANG, DIA, STALE = sys.argv[1:4]
fails = []
tmp = tempfile.mkdtemp(prefix="dialect48.")


def dialect(path):
    r = subprocess.run([sys.executable, LANG, "dialect", path],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return json.loads(r.stdout) if r.stdout.strip() else None


# registry shape: versioned, ok, 64-hex hash, domain, non-empty terms+templates, each entry with a
# valid rolled-up status and >=1 resolved provenance record.
d = dialect(DIA)
ok = (d and d.get("schemaVersion") == 1 and d.get("ok") is True
      and re.fullmatch(r"[0-9a-f]{64}", d.get("domainDialectHash") or "")
      and d.get("domain") and d["registry"]["terms"] and d["registry"]["templates"])
valid = {"accepted", "proposed", "rejected", "unknown"}
if ok:
    for e in d["registry"]["terms"] + d["registry"]["templates"]:
        ok = ok and e.get("status") in valid and len(e.get("provenance", [])) >= 1
        for p in e.get("provenance", []):
            ok = ok and p.get("status") in {"accepted", "proposed", "rejected"} and p.get("source")
if not ok:
    fails.append("dialect registry shape (hash/domain/terms/templates/status/provenance)")

# fail closed: a hash-mismatched (stale) artifact -> ok:false, empty registry, diagnostics.
b = dialect(STALE)
if not (b and b["ok"] is False and b["registry"] == {"terms": [], "templates": []}
        and len(b.get("diagnostics", [])) >= 1):
    fails.append("stale (hash-mismatched) dialect not fail-closed")

# fail closed: a missing artifact -> ok:false with a setup diagnostic.
m = dialect(os.path.join(tmp, "does_not_exist.json"))
if not (m and m["ok"] is False and m["diagnostics"][0]["code"] == "dialect.no_dialect"):
    fails.append("missing dialect not fail-closed with dialect.no_dialect")

# YAML-authored dialect: the validator accepts YAML and the wrapper reads its normalized output, so a
# valid .yaml renders rather than being rejected as malformed. Only where PyYAML is available.
try:
    import yaml
    yp = os.path.join(tmp, "dialect.yaml")
    yaml.safe_dump(json.load(open(DIA)), open(yp, "w"))
    y = dialect(yp)
    if not (y and y["ok"] is True and y["registry"]["terms"]):
        fails.append("valid YAML dialect rejected by the wrapper")
except ImportError:
    pass  # PyYAML unavailable — the shell block skips this case too.

if fails:
    print("[48] dialect contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[48] OK: registry surfaces terms/templates with rolled-up status + resolved provenance from the "
      "validator-verified artifact; stale/missing fail closed; YAML dialect rendered via the validator's "
      "normalized output")
