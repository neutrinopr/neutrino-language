#!/usr/bin/env python3
""": repeated fail-closed CLI coverage for shared coordination normalization."""

import json
import pathlib
import shutil
import subprocess
import sys


gen, equiv, invalid, scenario, valid, scratch = [
    str(pathlib.Path(arg).resolve()) for arg in sys.argv[1:]
]
scratch = pathlib.Path(scratch)
artifacts = {
    "capability-spec": "capability-spec.json",
    "coordination-plan": "coordination-plan.json",
}
message = (
    "coordination plan: [attest.policy.unbound] attestation policy "
    "'beta_proof' is declared but no effect gates on accepted(beta_proof) "
    "— a per-policy coordination must bind every declared quorum"
)
diagnostic = {
    "code": "attest.policy.unbound",
    "message": message,
    "severity": "error",
}


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)

for target, artifact in artifacts.items():
    for attempt in range(8):
        out = scratch / f"invalid-{target}-{attempt}"
        shutil.rmtree(out, ignore_errors=True)
        run = subprocess.run(
            [gen, f"--target={target}", invalid, "-o", str(out)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if run.returncode != 4:
            raise SystemExit(
                f"{target} attempt {attempt}: expected governed exit 4, "
                f"got {run.returncode}\n{run.stderr}"
            )
        if run.stderr.strip() != f"error: {message}":
            raise SystemExit(
                f"{target} attempt {attempt}: unexpected stderr diagnostic\n"
                f"{run.stderr}"
            )
        diagnostics = read_json(out / "diagnostics.json")
        if diagnostics != {"diagnostics": [diagnostic], "ok": False}:
            raise SystemExit(
                f"{target} attempt {attempt}: diagnostics.json mismatch: "
                f"{diagnostics!r}"
            )
        manifest = read_json(out / "manifest.json")
        if manifest.get("ok") is not False or manifest.get("artifacts") != []:
            raise SystemExit(
                f"{target} attempt {attempt}: failure manifest is not "
                f"ok:false with no artifacts: {manifest!r}"
            )
        if (out / artifact).exists():
            raise SystemExit(
                f"{target} attempt {attempt}: rejected target wrote {artifact}"
            )

# Preserve the valid multi-policy boundary for both normalized-contract emitters.
for target, artifact in artifacts.items():
    out = scratch / f"valid-{target}"
    shutil.rmtree(out, ignore_errors=True)
    run = subprocess.run(
        [gen, f"--target={target}", valid, "-o", str(out)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if run.returncode != 0 or not (out / artifact).is_file():
        raise SystemExit(
            f"valid multi-policy {target}: expected exit 0 and {artifact}, "
            f"got {run.returncode}\n{run.stderr}"
        )

# The second executable caller must consume the same fallible boundary before
# backend/spec emission; this used to continue after normalization failed and
# reach the same cantFail through its explicit emitter calls.
equiv_run = scratch / "equiv-run"
equiv_report = scratch / "equiv-report"
shutil.rmtree(equiv_run, ignore_errors=True)
shutil.rmtree(equiv_report, ignore_errors=True)
equiv_run.mkdir(parents=True)
run = subprocess.run(
    [
        equiv,
        f"--scenario={scenario}",
        invalid,
        f"--report={equiv_report}",
        "--reference-only",
    ],
    cwd=equiv_run,
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
if run.returncode != 1:
    raise SystemExit(
        f"neutrino-equiv: expected governed exit 1, got {run.returncode}\n"
        f"{run.stderr}"
    )
if read_json(equiv_report / "diagnostics.json") != {
    "diagnostics": [diagnostic],
    "ok": False,
}:
    raise SystemExit("neutrino-equiv: diagnostics.json mismatch")
equivalence = read_json(equiv_report / "equivalence.json")
if equivalence.get("ok") is not False or equivalence.get("resultCode") != 1:
    raise SystemExit("neutrino-equiv: failure report is not ok:false/resultCode:1")
if (equiv_run / "build").exists():
    raise SystemExit("neutrino-equiv: rejected input reached backend emission")
