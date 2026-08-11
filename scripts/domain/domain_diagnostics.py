#!/usr/bin/env python3
"""D3 / Phase 24 — domain-origin diagnostics.

Maps core `.neu` compiler diagnostics back to the originating domain term/template,
so a user working in dialect terms sees domain-relevant errors — WITHOUT moving trust
off the core `.neu`/MLIR semantics. Trust still centers on the translator: this tool
only *annotates* the translator's own diagnostics using the (reviewed, hash-pinned)
expansion manifest's per-construct source spans (D2/D3). No annotation invents an
error; an un-mapped diagnostic passes through unchanged.

Pipeline:
  1. run `neutrino_lang.py diagnostics <neu> --translate <bin>` (the D8 language-
     intelligence tool — the single source of structured diagnostics);
  2. verify the manifest actually describes this source — `generated.sourceHash` must
     equal sha256(--neu) — and only then trust its spans. A stale/mismatched sidecar
     (e.g. an edited generated file whose line spans have shifted) is fail-closed:
     `sourceMatches` is false and NO `domainOrigin` is attached, so a wrong origin can
     never be pinned to a real error; the raw diagnostics still pass through;
  3. for each diagnostic, find the manifest construct whose `sourceSpan` contains the
     diagnostic line, and attach `domainOrigin` = { dialect id/version/hash, construct,
     participantTerm, edges } from the expansion manifest.

The dialect id/version/hash and the generated-source hash from the manifest are echoed
at the top level, so the origin is auditable. Presentation-only (the .neu comments / the
manifest) never affects IR or capability hashes — those come from the translator.

Exit 0 if the core diagnostics report ok, 1 otherwise, 2 on usage/IO error.

  domain_diagnostics.py --neu FILE --manifest FILE --translate PATH
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neu", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--translate", required=True)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    # neutrino_lang moved to scripts/generators/ in the  role layout (domain/ -> scripts -> generators/).
    lang = os.path.join(os.path.dirname(here), "generators", "neutrino_lang.py")
    try:
        proc = subprocess.run(
            [sys.executable, lang, "diagnostics", args.neu, "--translate", args.translate],
            capture_output=True, text=True)
        core = json.loads(proc.stdout)
    except (OSError, ValueError) as exc:
        print(f"error: could not obtain core diagnostics: {exc}")
        return 2
    try:
        manifest = json.load(open(args.manifest, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read expansion manifest: {exc}")
        return 2

    if manifest.get("kind") != "neutrino.dialect-expansion-manifest":
        print("error: --manifest is not a neutrino.dialect-expansion-manifest")
        return 2

    dialect = manifest.get("dialect")
    # Verify the manifest actually describes THIS source before trusting its spans:
    # compare the manifest's generated.sourceHash to the hash of --neu. A stale or
    # mismatched sidecar (e.g. an edited generated file) must NOT attach domain origins,
    # since its line spans no longer correspond to the source — fail closed by skipping
    # all mapping (the raw core diagnostics still pass through, flagged unverified).
    try:
        neu_bytes = open(args.neu, "rb").read()
    except OSError as exc:
        print(f"error: cannot read --neu: {exc}")
        return 2
    gen = manifest.get("generated") or {}
    source_matches = gen.get("sourceHash") == hashlib.sha256(neu_bytes).hexdigest()

    # (startLine, endLine, construct) spans, longest-span-last so the most specific
    # (smallest) construct wins when spans nest. Empty when the source doesn't match,
    # so nothing is mapped.
    spans = sorted(
        ((c["sourceSpan"]["startLine"], c["sourceSpan"]["endLine"], c)
         for c in manifest.get("constructs", []) if "sourceSpan" in c),
        key=lambda t: t[1] - t[0], reverse=True) if source_matches else []

    diagnostics = core.get("diagnostics", [])
    mapped = 0
    for d in diagnostics:
        line = d.get("range", {}).get("start", {}).get("line")
        hit = next((c for s, e, c in spans if isinstance(line, int) and s <= line <= e), None)
        if hit is not None:
            d["domainOrigin"] = {
                "dialect": dialect,
                "construct": hit["construct"],
                "participantTerm": hit.get("participantTerm"),
                "edges": hit.get("edges", []),
            }
            mapped += 1

    out = {
        "schemaVersion": 1,
        "kind": "neutrino.domain-diagnostics",
        "file": args.neu,
        "ok": bool(core.get("ok")),
        "dialect": dialect,
        "generated": manifest.get("generated"),
        "sourceMatches": source_matches,
        "mappedCount": mapped,
        "diagnostics": diagnostics,
    }
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
