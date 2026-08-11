"""[47] completions contract for neutrino_lang.py `completions`. Ported verbatim from the retired
run_cpp_tests.sh [47] block ( S5j). Static (no file): scope=static grammar affordances drawn from
metadata (keywords + value types + snippets). With a file: static PLUS source-specific %references
pulled from the front-end outline. A non-lowering source fails closed.

Usage: check_completions.py <neutrino_lang.py> <neutrino-emit> <src.neu> <non-lowering-src.neu>
"""
import json
import os
import subprocess
import sys

LANG, EMIT, SRC, NEG = sys.argv[1:5]
fails = []


def lang(*args, with_emit=True):
    e = dict(os.environ)
    if with_emit:
        e["NEUTRINO_EMIT"] = EMIT
    r = subprocess.run([sys.executable, LANG, *args], env=e,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return json.loads(r.stdout) if r.stdout.strip() else None


# static (no file): scope=static, drawn from metadata (keyword + type + snippet kinds).
s = lang("completions", with_emit=False)
labs = {c["label"] for c in (s or {}).get("completions", [])}
kinds = {c["kind"] for c in (s or {}).get("completions", [])}
if not (s and s["ok"] and s.get("scope") == "static" and "procedure" in labs and "money" in labs
        and {"keyword", "type", "snippet"} <= kinds):
    fails.append("static completions content (scope/keywords/types/snippets)")

# source-specific (with a file): static + in-scope %references from the front-end outline.
src = lang("completions", SRC)
refs = [c["label"] for c in (src or {}).get("completions", []) if c["kind"] == "reference"]
if not (src and src["ok"] is True and src.get("file")
        and any(r.startswith("%") for r in refs) and len(refs) >= 1):
    fails.append("source-specific %references missing")

# a non-lowering source -> ok:false, empty completions, diagnostics.
b = lang("completions", NEG)
if not (b and b["ok"] is False and b["completions"] == [] and len(b.get("diagnostics", [])) >= 1):
    fails.append("non-lowering completions not fail-closed")

if fails:
    print("[47] completions contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[47] OK: static grammar affordances from metadata; with a file, in-scope %references from the "
      "front-end outline; non-lowering source -> ok:false")
