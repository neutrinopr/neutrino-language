"""[10b] expression model: unsupported / ill-typed compute expressions rejected at generation (M5 WP1b,
). Ported verbatim from the retired run_cpp_tests.sh [10b] block ( S5n). Compute expressions are
parsed + typed once when the view is built, so an unsupported or ill-typed expression is caught at
generation (exit 4 + a specific code: expr.unsupported / expr.type / expr.invalid), not silently
rendered — and the same well-formedness gate binds the otherwise-ungated ANALYSIS targets (coverage)
too. Covers: an unsupported function; non-numeric arithmetic; bad round arity/scale; malformed syntax.

Usage: check_expression_model.py <neutrino-gen>
"""
import os
import subprocess
import sys
import tempfile

GEN = sys.argv[1]
fails = []
tmp = tempfile.mkdtemp(prefix="expr10b.")

# a procedure whose compute line we substitute per case. The procedure name is fixed (exprfn) to match
# the single scenario below, so scenario validation passes and the EXPRESSION gate is what fails.
NEU_TMPL = """procedure exprfn {{
    trigger t
    input amt  : money
    input acct : party
    input cur  : currency
    input k    : string
    compute {compute}
    debit d1 {{
        ledger          = "a"
        owner           = "o"
        party           = %acct
        amount          = %amt
        currency        = %cur
        idempotency_key = %k
    }}
    credit c1 {{
        ledger          = "b"
        owner           = "o"
        party           = %acct
        amount          = %amt
        currency        = %cur
        idempotency_key = %k
    }}
    assert balanced
}}
"""
SCEN = os.path.join(tmp, "expr.json")
open(SCEN, "w").write('{ "scenario":"e","procedure":"exprfn","inputs":'
                      '{"amt":100,"acct":"p","cur":"EUR","k":"w"} }\n')


def write_neu(name, compute):
    p = os.path.join(tmp, name + ".neu")
    open(p, "w").write(NEU_TMPL.format(compute=compute))
    return p


def gen(neu, target, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run([GEN, "--target=" + target, "--scenario=" + SCEN, neu, "-o", out],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    dj = os.path.join(out, "diagnostics.json")
    return rc, (open(dj).read() if os.path.isfile(dj) else ""), out


def expect(neu, target, sub, code, artifact, label):
    rc, diag, out = gen(neu, target, sub)
    if rc != 4:
        fails.append(f"{label}: exit={rc} (want 4)")
    if ('"' + code + '"') not in diag:
        fails.append(f"{label}: missing {code} code")
    if artifact and os.path.isfile(os.path.join(out, artifact)):
        fails.append(f"{label}: emitted {artifact} despite the error")


# (a) an unsupported function (only round is supported today) — on lowering AND analysis targets.
fn = write_neu("exprfn", "bogus = sqrt(amt)")
expect(fn, "postgres", "exprfn_out", "expr.unsupported", "procedure.sql", "unsupported function")
expect(fn, "coverage", "exprfn_cov", "expr.unsupported", "coverage.json", "analysis target (coverage) gated")

# (b) arithmetic over a governed non-numeric value (a party) is a type error.
ty = write_neu("exprty", "bad = acct + amt")
expect(ty, "postgres", "exprty_out", "expr.type", None, "non-numeric operand")

# (c) round is identity today but must not swallow bad call shapes.
for expr, code in [("round(amt, 2, amt)", "expr.unsupported"),  # too many arguments
                   ("round(amt, acct)", "expr.type"),           # non-literal scale
                   ("round(acct)", "expr.type"),                # governed non-numeric argument
                   ("round(acct, 2)", "expr.type")]:            # ...even with a valid scale
    neu = write_neu("exprrnd", "bogus = " + expr)
    expect(neu, "postgres", "exprrnd_out", code, "procedure.sql", f"round '{expr}'")

# (d) a syntactically malformed expression -> expr.invalid (fallback family), exit 4, no artifacts.
syn = write_neu("exprsyn", "bogus = round((amt)")
expect(syn, "postgres", "exprsyn_out", "expr.invalid", "procedure.sql", "malformed expr syntax")

if fails:
    print("[10b] expression-model contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[10b] OK: unsupported function + non-numeric arithmetic + bad round arity/scale + malformed "
      "syntax -> expr.unsupported/expr.type/expr.invalid; analysis targets gated too; exit 4, no artifacts")
