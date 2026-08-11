"""[98] compiler-backed .neu LSP contract for scripts/generators/neutrino_lsp.py (M5  T2, ). Ported verbatim
from the retired run_cpp_tests.sh [98] block ( S5j). The LSP DELEGATES to the compiler and maps its
output — it never re-derives diagnostics or token roles — and fails closed when the compiler is absent
or emits garbage.

  (a) diagnostics: an invalid fixture -> a MAPPED LSP diagnostic carrying the compiler's stable code +
      a 0-based range (mapped, not re-derived);
  (b) semantic tokens: a valid fixture distinguishes input(parameter) vs compute(variable) — roles the
      COMPILER assigned via --kind=symbols — in the delta-encoded stream;
  (c) fail-closed: NO compiler binary -> explicit "not found" + non-zero exit;
  (c2) fail-closed: a neutrino-emit that exits 0 with non-JSON makes `symbols` ok:false -> the tokens
      path surfaces an explicit "symbols failed", not a silent empty stream;
  (d) the stdio server really speaks LSP: initialize -> didOpen(invalid) -> publishDiagnostics.

Usage: check_lsp.py <neutrino_lsp.py> <neutrino-translate> <neutrino-emit> <valid.neu> <invalid.neu>
"""
import json
import os
import subprocess
import sys
import tempfile

LSP, TRANSLATE, EMIT, VALID, INVALID = sys.argv[1:6]
fails = []
tmp = tempfile.mkdtemp(prefix="lsp98.")
BASE = dict(os.environ, NEUTRINO_TRANSLATE=TRANSLATE, NEUTRINO_EMIT=EMIT)


def run(args, env, want_zero=True):
    r = subprocess.run([sys.executable, LSP, *args], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r


# (a) diagnostics: invalid fixture -> mapped LSP diagnostics with the compiler's stable code.
r = run(["--diagnostics", INVALID], BASE)
try:
    diag = json.loads(r.stdout)
    good = (isinstance(diag, list) and len(diag) >= 1
            and all("code" in x and x.get("source") == "neutrino" and x["severity"] in (1, 2, 3, 4)
                    and "start" in x["range"] and x["range"]["start"]["line"] >= 0 for x in diag)
            and any(x["code"] for x in diag))
    if not good:
        fails.append("diagnostics shape (mapped code + 0-based range + severity)")
except ValueError:
    fails.append("diagnostics batch did not emit JSON")

# (b) semantic tokens: valid fixture -> both parameter (input) and variable (compute) token types.
r = run(["--semantic-tokens", VALID], BASE)
try:
    d = json.loads(r.stdout)
    tt = d["legend"]["tokenTypes"]
    data = d["data"]
    assert data and len(data) % 5 == 0, "empty/malformed token stream"
    used = {data[i + 3] for i in range(0, len(data), 5)}
    if not ({tt.index("parameter"), tt.index("variable")} <= used):
        fails.append("semantic tokens do not distinguish input(parameter) vs compute(variable)")
except (ValueError, KeyError, AssertionError, TypeError) as ex:
    fails.append(f"semantic tokens malformed: {ex}")

# (c) fail-closed: no compiler binary -> explicit "not found" + non-zero exit.
noenv = {k: v for k, v in os.environ.items() if k not in ("NEUTRINO_TRANSLATE", "NEUTRINO_EMIT")}
r = run(["--diagnostics", INVALID], noenv)
if r.returncode == 0 or b"not found" not in r.stderr.lower():
    fails.append("missing compiler binary was not fail-closed with a 'not found' error")

# (c2) fail-closed: an emit that exits 0 with non-JSON makes symbols ok:false -> tokens must surface
# an explicit "symbols failed", not a silent empty stream.
fake = os.path.join(tmp, "lsp_fake_emit.sh")
open(fake, "w").write('#!/bin/sh\necho "not json"\n')
os.chmod(fake, 0o755)
r = run(["--semantic-tokens", VALID, "--emit", fake],
        dict(os.environ, NEUTRINO_TRANSLATE=TRANSLATE))
if r.returncode == 0 or b"symbols failed" not in r.stderr.lower():
    fails.append("malformed token output (symbols ok:false) was not fail-closed")

# (d) the stdio server really speaks LSP: initialize -> didOpen(invalid) -> publishDiagnostics.
def frame(obj):
    b = json.dumps(obj).encode()
    return f"Content-Length: {len(b)}\r\n\r\n".encode() + b


text = open(INVALID).read()
msgs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"capabilities": {}}},
    {"jsonrpc": "2.0", "method": "initialized", "params": {}},
    {"jsonrpc": "2.0", "method": "textDocument/didOpen",
     "params": {"textDocument": {"uri": "file:///x.neu", "languageId": "neutrino", "version": 1, "text": text}}},
    {"jsonrpc": "2.0", "id": 2, "method": "shutdown"},
    {"jsonrpc": "2.0", "method": "exit"},
]
p = subprocess.run([sys.executable, LSP], input=b"".join(frame(m) for m in msgs),
                   capture_output=True, env=BASE)
out = p.stdout.decode("utf-8", "replace")
if not ("semanticTokensProvider" in out and "publishDiagnostics" in out and "parse.missing_field" in out):
    fails.append("stdio LSP round-trip did not answer initialize + publish diagnostics")

if fails:
    print("[98] LSP contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[98] OK: invalid .neu -> mapped LSP diagnostics with the compiler's stable code; valid .neu -> "
      "semantic tokens distinguishing input(parameter) vs compute(variable); missing compiler binary AND "
      "malformed token output both fail closed; the stdio server answers initialize + publishes diagnostics")
