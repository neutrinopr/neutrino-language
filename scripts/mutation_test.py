#!/usr/bin/env python3
"""Phase 16 — IR-integrity mutation testing.

Validates that the frontend + C++ verifier actually *catch* broken coordination,
rather than only checking happy-path scenarios. Each mutation deliberately breaks
a coordination invariant in the `.neu` source; the mutant is "caught" if
`neutrino-translate` rejects it (frontend) or `neutrino-opt` rejects the lowered
IR (verifier). A surviving CRITICAL mutant means the verifier has a gap.

One mutation (`alter_compute_expr`) is an EXPECTED survivor: a compute
expression's template is opaque to the verifier (by design — it is lowered, not
evaluated, in the IR), so changing a constant inside it produces valid IR with
wrong values. It is caught downstream by `neutrino-equiv` / the backends, not by
static verification. Reporting it documents that boundary and proves the harness
distinguishes caught from survived (a negative control). It is not a failure.

Deterministic (fixed mutation set, no randomness). Emits mutation-report.json +
diagnostics.json. Exit 0 ok / 1 a critical mutant survived / 2 usage.

  mutation_test.py --source FILE --translate BIN --opt BIN --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile


def drop_credit(src: str):
    return re.subn(r"\n[ \t]*credit[ \t]+\w+[ \t]*\{.*?\n[ \t]*\}\n", "\n", src,
                   count=1, flags=re.DOTALL)


def undeclared_ref(src: str):
    # Point a leg operand at a value that was never declared -> invalid SSA / IR.
    return re.subn(r"=[ \t]*%\w+", "= %__undeclared_ref__", src, count=1)


def duplicate_input(src: str):
    m = re.search(r"\n([ \t]*input[ \t]+\w+[ \t]*:[ \t]*\w+)\n", src)
    if not m:
        return src, 0
    line = m.group(1)
    return src[:m.end()] + line + "\n" + src[m.end():], 1


def drop_assert_balanced(src: str):
    return re.subn(r"\n[ \t]*assert[ \t]+balanced[ \t]*\n", "\n", src, count=1)


def alter_compute_expr(src: str):
    # Bump the first integer literal inside the first compute expression. The
    # expr template is opaque to the verifier, so this yields valid-but-wrong IR.
    m = re.search(r"\n[ \t]*compute[ \t]+\w+[ \t]*=[ \t]*[^\n]*?(\d+)", src)
    if not m:
        return src, 0
    s, e = m.start(1), m.end(1)
    bumped = str(int(m.group(1)) + 1)
    return src[:s] + bumped + src[e:], 1


# (name, transform, critical). Critical mutants MUST be caught by the frontend or
# verifier. The one non-critical mutation is an expected survivor (caught only by
# equivalence/backends) — a negative control documenting the static boundary.
MUTATIONS = [
    ("drop_credit", drop_credit, True),
    ("undeclared_ref", undeclared_ref, True),
    ("duplicate_input", duplicate_input, True),
    ("drop_assert_balanced", drop_assert_balanced, True),
    ("alter_compute_expr", alter_compute_expr, False),
]


def run(cmd) -> int:
    return subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--translate", required=True)
    ap.add_argument("--opt", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    try:
        src = open(args.source).read()
    except OSError as e:
        print(f"error: cannot read source: {e}", file=sys.stderr)
        return 2

    tmp = tempfile.mkdtemp(prefix="neutrino_mut_")
    results = []
    diagnostics = []
    for name, fn, critical in MUTATIONS:
        mutated, n = fn(src)
        if n == 0:
            results.append({"mutation": name, "critical": critical,
                            "applied": False, "caught": None})
            continue
        msrc = os.path.join(tmp, f"{name}.neu")
        mir = os.path.join(tmp, f"{name}.mlir")
        open(msrc, "w").write(mutated)
        caught, by = False, None
        if run([args.translate, msrc, "-o", mir]) != 0:
            caught, by = True, "frontend"
        elif run([args.opt, mir]) != 0:
            caught, by = True, "verifier"
        results.append({"mutation": name, "critical": critical,
                        "applied": True, "caught": caught, "caughtBy": by})
        if critical and not caught:
            diagnostics.append({"severity": "error", "code": "mutation.survived",
                                "message": f"critical mutant '{name}' survived "
                                           f"(neither frontend nor verifier caught it)"})

    applied = [r for r in results if r.get("applied")]
    caught = [r for r in applied if r.get("caught")]
    crit_survivors = [r["mutation"] for r in applied
                      if r["critical"] and not r["caught"]]
    ok = len(crit_survivors) == 0
    report = {
        "kind": "neutrino.mutation-report",
        "ok": ok,
        "source": os.path.basename(args.source),
        "mutationScore": f"{len(caught)}/{len(applied)}",
        "criticalSurvivors": sorted(crit_survivors),
        "expectedSurvivors": ["alter_compute_expr"],
        "mutants": results,
        "resultCode": 0 if ok else 1,
    }
    with open(os.path.join(args.out, "mutation-report.json"), "w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(args.out, "diagnostics.json"), "w") as f:
        json.dump({"ok": ok, "diagnostics": diagnostics}, f, indent=2, sort_keys=True)
        f.write("\n")

    if not ok:
        for d in diagnostics:
            print(f"  - [{d['code']}] {d['message']}", file=sys.stderr)
        return 1
    print(f"mutation: ok (score {report['mutationScore']}; "
          f"critical caught; expected survivor: alter_compute_expr)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
