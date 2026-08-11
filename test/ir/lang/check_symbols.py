"""[45] full document-symbols contract. Ported from the retired run_cpp_tests.sh [45] block ( S5j).

Covers both layers:
  (raw)     neutrino-emit --kind=symbols emits front-end ranges that map to REAL source headers /
            closing braces (a procedure symbol whose end line is `}`, participant/input/leg children,
            each participant child's start line a `participant ` header and end line a `}`);
  (wrapper) neutrino_lang.py `symbols` renders that outline into the versioned file/ok/diagnostics
            envelope; a non-lowering source -> ok:false + empty symbols + a coded diagnostic; and a
            degenerate emitter response (exit 0 but a bare {"symbols":[]} with no envelope) FAILS
            CLOSED, not reported as a successful empty outline.

Usage: check_symbols.py <neutrino-emit> <neutrino_lang.py> <source.neu> <non-lowering-source.neu>
"""
import json
import os
import subprocess
import sys
import tempfile

EMIT, LANG, SRC, NEG = sys.argv[1:5]
fails = []


def run(*cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([str(c) for c in cmd], env=e,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


# ---- raw front-end ranges (neutrino-emit --kind=symbols) ----
d = json.loads(run(EMIT, "--kind=symbols", SRC).stdout)
src = open(SRC, encoding="utf-8", errors="replace").read().splitlines()
try:
    assert d.get("schemaVersion") == 1 and d.get("symbols"), "no symbols emitted"
    proc = d["symbols"][0]
    assert proc["kind"] == "procedure", proc["kind"]

    def rng(sym):
        r = sym["range"]
        s, e = r["start"]["line"], r["end"]["line"]
        assert 1 <= s <= e <= len(src), f"range {s}-{e} out of bounds for {sym['name']}"
        return s, e

    _, pe = rng(proc)
    assert src[pe - 1].strip() == "}", f"procedure end line {pe} is not a closing brace"
    kinds = {c["kind"] for c in proc.get("children", [])}
    assert {"participant", "input"} <= kinds, f"missing child kinds: {kinds}"
    assert ("debit" in kinds) or ("credit" in kinds), f"no ledger leg symbol: {kinds}"
    parts = [c for c in proc["children"] if c["kind"] == "participant"]
    assert parts, "no participant symbols"
    for p in parts:
        s, e = rng(p)
        assert src[s - 1].strip().startswith("participant "), f"start {s} not a participant header"
        assert src[e - 1].strip() == "}", f"end {e} not a closing brace"
except (AssertionError, KeyError, IndexError, TypeError) as ex:
    fails.append(f"raw symbol ranges: {ex}")


def lang_symbols(source, env=None):
    r = run(sys.executable, LANG, "symbols", source, env=env)
    return json.loads(r.stdout) if r.stdout.strip() else None


# ---- wrapper envelope (neutrino_lang.py symbols) ----
w = lang_symbols(SRC, env={"NEUTRINO_EMIT": EMIT})
if not (w and w["schemaVersion"] == 1 and w["ok"] is True and w["file"] == SRC
        and w["symbols"][0]["kind"] == "procedure" and len(w["symbols"][0]["children"]) >= 1):
    fails.append("symbols wrapper envelope (versioned file/ok/procedure/children)")

# a non-lowering source -> ok:false + empty outline + a coded diagnostic.
b = lang_symbols(NEG, env={"NEUTRINO_EMIT": EMIT})
if not (b and b["ok"] is False and b["symbols"] == []
        and b["diagnostics"][0]["code"] == "parse.missing_field"):
    fails.append("non-lowering source via the wrapper not ok:false + coded diagnostics")

# degenerate emitter (exit 0 + bare {"symbols":[]}, no envelope) must FAIL CLOSED.
tmp = tempfile.mkdtemp(prefix="sym45.")
fake = os.path.join(tmp, "fake_emit.sh")
open(fake, "w").write('#!/bin/sh\necho \'{"symbols":[]}\'\nexit 0\n')
os.chmod(fake, 0o755)
g = lang_symbols(SRC, env={"NEUTRINO_EMIT": fake})
if not (g and g["ok"] is False and g["symbols"] == [] and len(g.get("diagnostics", [])) >= 1):
    fails.append("degenerate emitter output accepted as ok:true (should fail closed)")

if fails:
    print("[45] document-symbols contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[45] OK: front-end ranges map to real source positions; wrapper adds the versioned envelope; "
      "non-lowering -> ok:false + diagnostics; degenerate emitter fails closed")
