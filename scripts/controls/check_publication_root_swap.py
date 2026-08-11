#!/usr/bin/env python3
"""Control: swapping the output root during admission must not redirect publication.

The publication path in lib/spec-contract/ArtifactPublication.cpp opens the
caller-spelled output root exactly once with
``O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`` and keeps that descriptor as *the*
publication root; every descendant operation is fd-relative from it. There is
deliberately no lstat/realpath pre-check, because any check performed on a PATH
and then re-resolved is a check/use race: an attacker who replaces the root
between the check and the write redirects the artifacts.

This control attacks exactly that window. It races a swap of the FINAL root
component -- ``rm -rf root && ln -s victim root`` -- against a live
``neutrino-gen`` publication, many times, and asserts that no published artifact
ever lands in the victim. It is a race, so a single green trial proves little;
the trial count is what gives it teeth.

NOT wired into the lit suite on purpose. It is timing-dependent, and a
timing-dependent test in the terminal acceptance surface trades a real property
for intermittent red. Run it directly as a control and record the output.

KNOWN RESIDUAL (reported, not asserted; tracked as , deferred past M6):
manifest.json and diagnostics.json are written by a separate path-based writer
in tools/neutrino-gen (and shared with neutrino-bundle / neutrino-equiv via
include/Neutrino/{Manifest,Diagnostics}.h), which re-resolves the output path at
write time and CAN be redirected by this same swap.

These sidecars ARE consumed as M6 release-gate evidence. An earlier revision of
this docstring claimed nothing downstream admits them; that was wrong.
scripts/gates/check_m6_release_gate.py loads diagnostics.json through
read_diagnostics() and reasons over its contents, and asserts that a refused
render emits EXACTLY {diagnostics.json, manifest.json} -- so the pair is
load-bearing for the refusal shape as well. check_capability_claims.py,
check_spec_legality.py and test/curated/check_postgres_goldens.py read them too.
They still carry no receipt and no immutability, but "not a receipt" is not the
same as "not evidence", and only the first of those is true here.

Why deferral is nonetheless acceptable for M6:  runs in an ISOLATED output
tree with no adversarial concurrent writer. The redirection requires an attacker
able to replace the output root mid-run; under the terminal run's conditions
there is no such writer, so the evidence the release gate reads cannot be
diverted. That argument is about the RUN's conditions, not about the artifacts'
importance -- outside an isolated tree these are exactly the files an attacker
would want to plant, which is why  must not be closed as cosmetic.

Fixing it means threading the retained root fd through two shared public headers
and three tools, which is why it is tracked separately rather than folded in
here. This control prints the sidecar count so the residual stays visible
instead of being quietly absorbed.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time


def swap(root: Path, victim: Path, delay: float) -> None:
    """Replace the final root component with a symlink to the victim."""
    time.sleep(delay)
    try:
        shutil.rmtree(root)
        root.symlink_to(victim, target_is_directory=True)
    except OSError:
        # Losing the race is a normal outcome; the assertion is about where the
        # artifacts landed, never about whether the swap won.
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--target", default="solidity")
    parser.add_argument("--trials", type=int, default=60)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="publication-root-swap.") as raw:
        base = Path(raw)
        victim = base / "victim"
        victim.mkdir()

        for trial in range(args.trials):
            root = base / f"root{trial}"
            root.mkdir()
            # Spread the swap across the admission window; a fixed delay would
            # only ever probe one instant of it.
            delay = 0.001 + (trial % 9) * 0.001
            racer = threading.Thread(target=swap, args=(root, victim, delay))
            racer.start()
            subprocess.run(
                [
                    str(args.gen),
                    f"--target={args.target}",
                    "--scenario",
                    str(args.scenario),
                    str(args.source),
                    "-o",
                    str(root),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            racer.join()

        landed = sorted(p for p in victim.rglob("*") if p.is_file())
        sidecars = [
            p for p in landed
            if p.name in ("manifest.json", "diagnostics.json")
        ]
        artifacts = [p for p in landed if p not in set(sidecars)]

        print(f"trials:            {args.trials}")
        print(f"published leaked:  {len(artifacts)}  (must be 0)")
        print(f"sidecars leaked:   {len(sidecars)}  (known residual, reported)")
        for path in artifacts:
            print(f"  LEAKED ARTIFACT: {path.relative_to(victim)}")

        if artifacts:
            print(
                "FAIL: the output root was swapped during admission and "
                "publication followed it",
                file=sys.stderr,
            )
            return 1

    print("OK: publication never followed a swapped output root")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
