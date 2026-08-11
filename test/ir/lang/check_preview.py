"""[44] capability preview contract for neutrino_lang.py `preview`. Ported verbatim from the retired
run_cpp_tests.sh [44] block ( S5j). The preview COMPOSES a capability card from real compiler
artifacts (hash + IR + security verdict + backends + assurance) and must FAIL CLOSED — never a silent
empty card, never ok:true with a null security verdict or a null capabilityHash.

Usage: check_preview.py <neutrino_lang.py> <neutrino-gen> <src.neu> <scenario.json> <non-lowering-src.neu>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

LANG, GEN, SRC, SCEN, NEG = sys.argv[1:6]
fails = []
tmp = tempfile.mkdtemp(prefix="preview44.")


def preview(*args, env_gen=GEN):
    e = dict(os.environ, NEUTRINO_GEN=env_gen)
    r = subprocess.run([sys.executable, LANG, "preview", *args], env=e,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return json.loads(r.stdout) if r.stdout.strip() else None


def shim(name, body):
    p = os.path.join(tmp, name)
    open(p, "w").write(body)
    os.chmod(p, 0o755)
    return p


# shape: composes hash(64-hex) + ir.legs(int>=1) + security.status +
# backends(exactly empty) + downstream assurance requirements (no static claim).
d = preview(SRC, "--scenario", SCEN)
c = (d or {}).get("capability", {})
if not (d and d.get("ok") is True and d.get("schemaVersion") == 1
        and re.fullmatch(r"[0-9a-f]{64}", c.get("capabilityHash") or "")
        and isinstance(c.get("ir", {}).get("legs"), int) and c["ir"]["legs"] >= 1
        and c.get("security", {}).get("status") in {"pass", "advisory", "violation"}
        # : the hashed capability descriptor is TARGET-NEUTRAL. `backends`
        # is intentionally EMPTY here and must not be reconstructed from package
        # discovery. Assert exact-emptiness rather than a non-empty count, so a
        # reappearing overlay fails closed instead of silently satisfying it.
        and c.get("backends", None) == []
        and set(c.get("assurance", {})) == {"labels"}):
    fails.append("preview shape (hash/ir/security/backends/assurance)")

# NEGATIVE WITNESS (/): a non-empty `backends` is the retired overlay
# reappearing in a target-neutral descriptor. Assert it explicitly so the
# exact-empty check above can never be relaxed back into a non-empty count.
if c.get("backends"):
    fails.append(
        "preview backends must stay empty — the target-neutral capability "
        f"descriptor carries no backend availability, got {c.get('backends')!r}")

# the preview hash is COMPOSED from the slot artifact, never recomputed: it must equal the
# capability.lock the gated slot target writes.
slot = os.path.join(tmp, "pv_slot")
subprocess.run([GEN, "--target=slot", "--allow-insecure", "--scenario", SCEN, SRC, "-o", slot],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    lock = json.load(open(os.path.join(slot, "capability.lock")))["capabilityHash"]
    if c.get("capabilityHash") != lock:
        fails.append("preview hash != slot capability.lock (recomputed instead of composed)")
except (OSError, ValueError, KeyError):
    fails.append("could not read slot capability.lock for hash comparison")

# a source that does not lower -> ok:false + non-empty diagnostics (never a silent empty preview).
b = preview(NEG, "--scenario", SCEN)
if not (b and b["ok"] is False and len(b.get("diagnostics", [])) >= 1):
    fails.append("non-lowering source did not yield ok:false + diagnostics")

# FAIL CLOSED on the trust verdict: security target fails but slot artifacts still produced ->
# preview must NOT return ok:true with security:null.
secfail = shim("fake_gen_secfail.sh",
               '#!/usr/bin/env bash\nfor a in "$@"; do case "$a" in --target=security) exit 7;; esac; '
               f'done\nexec {GEN} "$@"\n')
sf = preview(SRC, "--scenario", SCEN, env_gen=secfail)
if not (sf and sf["ok"] is False and len(sf.get("diagnostics", [])) >= 1):
    fails.append("missing security verdict returned ok:true (fail-open trust preview)")

# FAIL CLOSED on capability identity: slot writes capability.json but capability.lock (the schema-hash
# bridge) is missing -> preview must NOT return ok:true with capabilityHash:null.
nolock = shim("fake_gen_nolock.sh",
              '#!/usr/bin/env bash\nout=""; prev=""; slot=""\n'
              'for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; [ "$a" = "--target=slot" ] && slot=1; prev="$a"; done\n'
              f'{GEN} "$@"; rc=$?\n'
              '[ -n "$slot" ] && [ -n "$out" ] && rm -f "$out/capability.lock"\nexit $rc\n')
nl = preview(SRC, "--scenario", SCEN, env_gen=nolock)
if not (nl and nl["ok"] is False and len(nl.get("diagnostics", [])) >= 1):
    fails.append("missing capability.lock returned ok:true (fail-open identity)")

# setup failures are versioned ok:false + a coded diagnostic, not an unversioned {error}.
ns = preview(SRC)  # no --scenario
if not (ns and ns.get("schemaVersion") == 1 and ns["ok"] is False
        and ns["diagnostics"][0]["code"] == "preview.no_scenario"):
    fails.append("missing-scenario not a versioned ok:false + preview.no_scenario")

if fails:
    print("[44] preview contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[44] OK: composes hash+IR+security+backends+assurance from real artifacts; hash matches slot "
      "capability.lock; non-lowering / missing security verdict / missing capability.lock all fail "
      "closed; setup errors are versioned ok:false")
