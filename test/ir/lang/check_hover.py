"""[46] hover contract for neutrino_lang.py `hover`. Ported verbatim from the retired run_cpp_tests.sh
[46] block ( S5j). Hover resolves the ENCLOSING front-end symbol (translator-owned ranges, not
regex): it reads a participant's start line from the front-end outline, hovers there, and expects that
participant resolved with a non-empty doc. A non-lowering source fails closed.

Usage: check_hover.py <neutrino_lang.py> <neutrino-emit> <src.neu> <non-lowering-src.neu>
"""
import json
import os
import subprocess
import sys

LANG, EMIT, SRC, NEG = sys.argv[1:5]
fails = []


def lang(*args):
    e = dict(os.environ, NEUTRINO_EMIT=EMIT)
    r = subprocess.run([sys.executable, LANG, *args], env=e,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return json.loads(r.stdout) if r.stdout.strip() else None


# take a participant's start line from the front-end outline (range-driven, robust to edits).
sym = lang("symbols", SRC)
try:
    pline = next(c for c in sym["symbols"][0]["children"]
                 if c["kind"] == "participant")["range"]["start"]["line"]
except (TypeError, KeyError, StopIteration, IndexError):
    print("[46] FAIL: could not read a participant line from symbols", file=sys.stderr)
    sys.exit(1)

# hover there -> the enclosing participant resolved with a non-empty construct doc.
h = lang("hover", SRC, "--line", str(pline))
hv = (h or {}).get("hover") or {}
if not (h and h.get("schemaVersion") == 1 and h.get("ok") is True
        and hv.get("kind") == "participant" and hv.get("name") == "Sponsor" and hv.get("contents")):
    fails.append("hover did not resolve the enclosing participant with a doc")

# a non-lowering source -> ok:false, hover null, structured diagnostics.
b = lang("hover", NEG, "--line", "1")
if not (b and b["ok"] is False and b.get("hover") is None and len(b.get("diagnostics", [])) >= 1):
    fails.append("non-lowering hover not fail-closed (ok:false, hover null)")

if fails:
    print("[46] hover contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[46] OK: hover resolves the enclosing front-end symbol + static construct doc; non-lowering "
      "source -> ok:false, hover null")
