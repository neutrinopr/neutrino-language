"""[7] generators escape unsafe DSL string literals. Ported verbatim from the retired run_cpp_tests.sh
[7] block ( S5n). A ledger name containing a quote must be SQL-escaped in the Postgres output
(acq''s.balance) and kept intact (dot-normalized, not injected) in the Solidity ledger literal.

Usage: check_escaping.py <neutrino-gen> <quoted_names.neu> <quoted_names.json>
"""
import os
import subprocess
import sys
import tempfile

GEN, NEU, SCEN = sys.argv[1:4]
fails = []
tmp = tempfile.mkdtemp(prefix="esc7.")


def gen(target, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN, "--target=" + target, "--scenario=" + SCEN, NEU, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    return rc, out


rc, out = gen("postgres", "q_pg")
if rc != 0:
    fails.append("postgres gen failed")
else:
    sql = open(os.path.join(out, "procedure.sql")).read()
    # The ledger name leaf is SQL-escaped through the postgres.string.escape hook.
    if "acq''s.balance" not in sql:
        fails.append("SQL ledger not '-escaped")
    # The memo leaf (WithMemo posting variant) flows through the SAME hook, so a
    # quoted memo is doubled too — proving the memo escape path, not just ledger.
    if "note''s" not in sql:
        fails.append("SQL memo not '-escaped")

rc, out = gen("solidity", "q_sol")
if rc != 0:
    fails.append("solidity gen failed")
# the apostrophe is a valid character inside a Solidity string key, so the ledger name stays intact
# (unlike SQL, where it must be doubled) — no injection, no truncation.
elif 'net[_k]["acq\'s.balance"]' not in open(os.path.join(out, "src", "QuotedNames.sol")).read():
    fails.append("Solidity ledger literal not intact")

if fails:
    print("[7] escaping contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[7] OK: SQL '-escaped; Solidity literal intact")
