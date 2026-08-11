"""[305] Declared expect.computed must match evaluation in validateScenario.

A scenario that declares a wrong-but-plausible non-negative computed value
(e.g. subsidy: 999 when the inputs evaluate to 10000) must fail closed with
exit 3 + scenario.invalid before any backend renders. Extra compute keys are
already refused; this covers the mis-declared-value hole  left open (the
negative-money gate only refused evaluated negatives, not lies about positive
results).

Usage: check_computed_expect.py <neutrino-gen> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline_inputs import PipelineInputError, resolve_pipeline_inputs

GEN, EXAMPLES = sys.argv[1:3]
fails = []
tmp = tempfile.mkdtemp(prefix="computed305.")
try:
    MSI_FIXTURE = resolve_pipeline_inputs(Path(EXAMPLES).resolve().parent)[
        "merchant_sponsored_installment"
    ]
except PipelineInputError as error:
    print(f"[305] computed-expect contract FAILED:\n    FAIL: {error}", file=sys.stderr)
    raise SystemExit(1)
SRC = str(MSI_FIXTURE.source)
POS = str(MSI_FIXTURE.scenario)


def gen(target, scenario, sub):
    out = os.path.join(tmp, sub)
    rc = subprocess.run(
        [GEN, "--target=" + target, "--scenario=" + scenario, SRC, "-o", out],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    dj = os.path.join(out, "diagnostics.json")
    return rc, out, (open(dj).read() if os.path.isfile(dj) else "")


def variant(name, mutate):
    p = os.path.join(tmp, name + ".json")
    d = json.load(open(POS))
    mutate(d)
    json.dump(d, open(p, "w"))
    return p


# Happy path still renders — the oracle is targeted.
rc, out, _ = gen("solidity", POS, "d305pos")
if rc != 0:
    fails.append(f"valid happy-path exit={rc} (want 0)")
if not os.path.isdir(os.path.join(out, "src")):
    fails.append("valid happy-path did not emit Solidity src")

# A non-negative LIE about subsidy (true value is 10000 for principal=100000,
# subsidy_pct=10) must fail closed — this is the  acceptance.
lie = variant(
    "d305lie",
    lambda d: d["expect"].__setitem__("computed", {"subsidy": 999}),
)
rc, out, diag = gen("solidity", lie, "d305lie")
if rc != 3:
    fails.append(f"lying subsidy=999 exit={rc} (want 3)")
if '"scenario.invalid"' not in diag:
    fails.append("lying subsidy missing scenario.invalid")
want = ("declared computed value 'subsidy' = 999 does not match the value "
        "10000 evaluated from the scenario inputs")
if want not in diag:
    fails.append(f"lying subsidy diagnostic wrong (want {want!r}, got {diag!r})")
if os.path.isdir(os.path.join(out, "src")):
    fails.append("emitted Solidity src despite mis-declared subsidy")

# Postgres path fails closed too (no artifact).
rc, out, _ = gen("postgres", lie, "d305liepg")
if rc != 3:
    fails.append(f"lying subsidy postgres exit={rc} (want 3)")
if os.path.isfile(os.path.join(out, "procedure.sql")):
    fails.append("emitted procedure.sql despite mis-declared subsidy")

# Extra compute key still refused (existing contract).
extra = variant(
    "d305extra",
    lambda d: d["expect"].__setitem__("computed",
                                      {"subsidy": 10000, "ghost": 1}),
)
rc, out, diag = gen("solidity", extra, "d305extra")
if rc != 3:
    fails.append(f"extra compute key exit={rc} (want 3)")
if "expected computed value 'ghost'" not in diag:
    fails.append("extra compute key not named in diagnostics")

# Omitting expect.computed remains allowed (existing contract — not every
# compute must be echoed).
omit = variant("d305omit", lambda d: d["expect"].__setitem__("computed", {}))
rc, out, _ = gen("solidity", omit, "d305omit")
if rc != 0:
    fails.append(f"omitted expect.computed exit={rc} (want 0)")

if fails:
    print("[305] computed-expect contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[305] OK: mis-declared non-negative expect.computed refused on both "
      "backends with scenario.invalid + no artifact; extra key refused; omit "
      "still allowed; valid happy-path still renders")
