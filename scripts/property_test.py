#!/usr/bin/env python3
"""Phase 16 — property-based testing.

Goes past happy-path scenarios: generates seeded-random valid scenarios within
value-model bounds and asserts coordination *properties* on the deterministic
reference that `neutrino-equiv` computes from IR + scenario.

Properties (domain-general for a balanced procedure):

  P1 balance conservation — the net ledger sums to zero for every input. This is
     a real invariant: a balanced procedure's debit and credit legs move the same
     (amount, currency), so the net position is zero regardless of input values.
  P2 reference well-formed — equiv reports reference.ok for every input.
  P3 determinism — the same input yields a byte-identical reference (run twice
     with SOURCE_DATE_EPOCH pinned).

equiv is run reference-only: the subprocess PATH is restricted so the Solidity /
PostgreSQL backend toolchains are not found and skip (`--allow-skips`); only the
in-process reference is computed, keeping the harness fast and deterministic.

Seeded (default 1337) so runs are reproducible. Emits property-report.json +
diagnostics.json. Exit 0 ok / 1 a property failed / 2 usage.

  property_test.py --source FILE --scenario BASE.json --equiv BIN --out DIR [--n N] [--seed S]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import subprocess
import sys
import tempfile

# Reference-only: hide unrelated tools and explicitly select the core-owned
# reference trace.
REF_ONLY_ENV = {**os.environ, "PATH": "/usr/bin:/bin"}


def run_equiv(equiv, source, scenario_path, report_dir, extra_env=None) -> dict:
    env = dict(REF_ONLY_ENV)
    if extra_env:
        env.update(extra_env)
    subprocess.run([equiv, "--reference-only", f"--scenario={scenario_path}",
                    source, f"--report={report_dir}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    return json.load(open(os.path.join(report_dir, "equivalence.json")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--scenario", required=True, help="base scenario (shape + names)")
    ap.add_argument("--equiv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    base = json.load(open(args.scenario))
    inputs = base.get("inputs", {})
    numeric_keys = sorted(k for k, v in inputs.items() if isinstance(v, int))
    rng = random.Random(args.seed)
    tmp = tempfile.mkdtemp(prefix="neutrino_prop_")

    failures = []
    checked = 0
    for i in range(args.n):
        scen = {"scenario": f"prop_{i}", "procedure": base["procedure"],
                "inputs": copy.deepcopy(inputs)}
        for k in numeric_keys:
            scen["inputs"][k] = rng.randint(0, 10_000_000)
        spath = os.path.join(tmp, f"prop_{i}.json")
        json.dump(scen, open(spath, "w"))
        rep = run_equiv(args.equiv, args.source, spath, os.path.join(tmp, f"r{i}"))
        ref = rep.get("reference", {})
        checked += 1
        if not ref.get("ok"):
            failures.append({"code": "property.reference_not_ok", "case": i,
                             "message": f"case {i}: reference not ok"})
            continue
        net = sum(ref.get("ledger", {}).values())
        if net != 0:
            failures.append({"code": "property.balance_violation", "case": i,
                             "message": f"case {i}: net ledger {net} != 0 for inputs "
                                        f"{ {k: scen['inputs'][k] for k in numeric_keys} }"})

    # P3 determinism: first case, run twice with a pinned epoch, compare references.
    det_ok = True
    if numeric_keys or inputs:
        scen0 = {"scenario": "prop_det", "procedure": base["procedure"],
                 "inputs": copy.deepcopy(inputs)}
        sp = os.path.join(tmp, "det.json")
        json.dump(scen0, open(sp, "w"))
        env = {"SOURCE_DATE_EPOCH": "1700000000"}
        r1 = run_equiv(args.equiv, args.source, sp, os.path.join(tmp, "d1"), env)
        r2 = run_equiv(args.equiv, args.source, sp, os.path.join(tmp, "d2"), env)
        if r1.get("reference") != r2.get("reference"):
            det_ok = False
            failures.append({"code": "property.nondeterministic",
                             "message": "reference differs across identical runs"})

    ok = len(failures) == 0
    properties = [
        {"name": "balance_conservation", "cases": checked, "passed":
         not any(f["code"] == "property.balance_violation" for f in failures)},
        {"name": "reference_well_formed", "cases": checked, "passed":
         not any(f["code"] == "property.reference_not_ok" for f in failures)},
        {"name": "determinism", "cases": 1, "passed": det_ok},
    ]
    report = {"kind": "neutrino.property-report", "ok": ok,
              "source": os.path.basename(args.source), "n": args.n, "seed": args.seed,
              "properties": properties, "failures": failures,
              "resultCode": 0 if ok else 1}
    with open(os.path.join(args.out, "property-report.json"), "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(args.out, "diagnostics.json"), "w") as f:
        json.dump({"ok": ok, "diagnostics": [
            {"severity": "error", "code": x["code"], "message": x["message"]} for x in failures
        ]}, f, indent=2, sort_keys=True)
        f.write("\n")

    if not ok:
        for x in failures:
            print(f"  - [{x['code']}] {x['message']}", file=sys.stderr)
        return 1
    print(f"property: ok (n={args.n}, seed={args.seed}; balance conservation + "
          f"reference well-formed over {checked} cases; determinism)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
