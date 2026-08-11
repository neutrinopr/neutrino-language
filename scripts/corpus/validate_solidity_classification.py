#!/usr/bin/env python3
"""M5 () — neutrino-solidity-samples `classification.json` validation.

`neutrino-solidity-samples/classification.json` labels each reference contract across
controlled coordination dimensions and pins each to a stable `profileId` / `profileVersion`.
The samples repo README states this file is validated by the **translator-side checker, not
that repo** — this is that checker. It is the source of truth for the classification *shape*,
so  target-profile matching and the  failure taxonomy can rely on a stable contract
rather than prose.

The normative shape is `docs/schemas/solidity-classification.schema.json`; this validator
**mirrors** it (CI runs this script, not a JSON-Schema library) AND enforces the
cross-references JSON Schema cannot express — dimension-value vocabulary membership, the
`profileId` `.vN` == `profileVersion` equality, `source` basename == `contract`, and
uniqueness. A self-test asserts the field sets / pattern / const below stay aligned with the
schema, so the two cannot drift.

The contract (schemaVersion 2):

  - top level: `schemaVersion` (==2), `description`, `dimensions`, optional `dimensionDocs`,
    `samples`; no other keys;
  - `dimensions`: exactly the governed dimension names, each a non-empty array of unique
    controlled-vocabulary strings;
  - `dimensionDocs` (optional): keys are a subset of the dimension names; values non-empty;
  - each `samples[i]`: `contract`, `profileId`, `profileVersion`, `source`, one value per
    scalar dimension, a `characteristics` list, `strength`, `whenToUse`; no other keys;
      - `profileId` matches `<family>.<name>.v<major>`, is unique, and its `v<major>` equals
        `profileVersion` (a positive integer);
      - `source` ends in `.sol` and its basename equals `contract` (also unique);
      - every scalar dimension value is drawn from that dimension's vocabulary; every
        `characteristics` entry likewise, unique and non-empty.

Fail-closed: any unknown field, missing required field, unknown dimension value, malformed
`profileId`, or `profileId`/`profileVersion` mismatch is an error diagnostic. Diagnostics are
machine-readable `{code, severity, message}` under the `classification.*` code family and are
stable (sorted), compatible with the shared failure-taxonomy direction ().

Emits a deterministic `classification.report.json` + `diagnostics.json` when `--out DIR` is
given, and prints `{ok, diagnostics}` to stdout. `ok` is true iff there are no error
diagnostics. Exit 0 ok / 1 violations / 2 usage.

  validate_solidity_classification.py FILE [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = 2

# The governed classification dimensions. Scalar dimensions carry exactly one value per
# sample; the sole list dimension (characteristics) carries a set. This split IS the
# contract  matches against — a new dimension is a schemaVersion change, not an ad-hoc
# field, so the set is fixed here and unknown/missing dimensions fail closed.
SCALAR_DIMENSIONS = ["partyModel", "timeBound", "oracleDependency", "accessControl",
                     "identityBinding", "orderingModel", "evidenceStyle"]
LIST_DIMENSIONS = ["characteristics"]
DIMENSIONS = SCALAR_DIMENSIONS + LIST_DIMENSIONS

TOP_FIELDS = {"schemaVersion", "description", "dimensions", "dimensionDocs", "samples"}
SAMPLE_FIELDS = {"contract", "profileId", "profileVersion", "source", "strength",
                 "whenToUse"} | set(DIMENSIONS)

# `<family>.<name>[...].v<major>` — lowercase dotted segments, at least a family and a name
# before the trailing version. The captured group is the version, cross-checked against
# `profileVersion` so the two identity fields cannot drift apart.
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\.v([0-9]+)$")


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v != ""


def validate(doc) -> list:
    out: list = []

    if not isinstance(doc, dict):
        return [diag("classification.schema", "top-level must be a JSON object")]

    for k in sorted(set(doc) - TOP_FIELDS):
        out.append(diag("classification.unknown_field", f"top-level: unknown field '{k}'"))
    for k in sorted(TOP_FIELDS - set(doc)):
        # dimensionDocs is the only optional top-level field.
        if k != "dimensionDocs":
            out.append(diag("classification.missing_field", f"top-level: missing '{k}'"))

    if doc.get("schemaVersion") != SCHEMA_VERSION:
        out.append(diag("classification.schema_version",
                        f"schemaVersion must be {SCHEMA_VERSION}, got {doc.get('schemaVersion')!r}"))
    if "description" in doc and not _nonempty_str(doc.get("description")):
        out.append(diag("classification.schema", "description must be a non-empty string"))

    # dimensions: exactly the governed names, each a non-empty array of unique non-empty
    # strings. `vocab[dim]` is then the controlled vocabulary each sample value must be in.
    vocab: dict = {}
    dims = doc.get("dimensions")
    if not isinstance(dims, dict):
        out.append(diag("classification.schema", "dimensions must be an object"))
    else:
        for k in sorted(set(dims) - set(DIMENSIONS)):
            out.append(diag("classification.unknown_dimension", f"dimensions: unknown dimension '{k}'"))
        for k in sorted(set(DIMENSIONS) - set(dims)):
            out.append(diag("classification.missing_dimension", f"dimensions: missing dimension '{k}'"))
        for name, values in dims.items():
            if name not in DIMENSIONS:
                continue
            if (not isinstance(values, list) or not values
                    or any(not _nonempty_str(v) for v in values)):
                out.append(diag("classification.schema",
                                f"dimensions.{name} must be a non-empty array of non-empty strings"))
                continue
            if len(set(values)) != len(values):
                out.append(diag("classification.schema",
                                f"dimensions.{name} has duplicate values"))
            vocab[name] = set(values)

    # dimensionDocs (optional): keys subset of dimension names, values non-empty strings.
    docs = doc.get("dimensionDocs")
    if docs is not None:
        if not isinstance(docs, dict):
            out.append(diag("classification.schema", "dimensionDocs must be an object"))
        else:
            for k in sorted(set(docs) - set(DIMENSIONS)):
                out.append(diag("classification.unknown_dimension",
                                f"dimensionDocs: '{k}' is not a governed dimension"))
            for k, v in docs.items():
                if k in DIMENSIONS and not _nonempty_str(v):
                    out.append(diag("classification.schema",
                                    f"dimensionDocs.{k} must be a non-empty string"))

    samples = doc.get("samples")
    if not isinstance(samples, list) or not samples:
        out.append(diag("classification.schema", "samples must be a non-empty array"))
        samples = []

    seen_profile_ids: dict = {}
    seen_contracts: dict = {}
    for i, s in enumerate(samples):
        # Prefer a stable, human-locating label: the profileId if it is a string, else index.
        label = s.get("profileId") if isinstance(s, dict) and _nonempty_str(s.get("profileId")) \
            else f"samples[{i}]"
        where = f"samples[{i}] ({label})"
        if not isinstance(s, dict):
            out.append(diag("classification.schema", f"samples[{i}] must be an object"))
            continue

        for k in sorted(set(s) - SAMPLE_FIELDS):
            out.append(diag("classification.unknown_field", f"{where}: unknown field '{k}'"))
        for k in sorted(SAMPLE_FIELDS - set(s)):
            out.append(diag("classification.missing_field", f"{where}: missing '{k}'"))

        contract = s.get("contract")
        if _nonempty_str(contract):
            if contract in seen_contracts:
                out.append(diag("classification.duplicate_contract",
                                f"{where}: duplicate contract '{contract}'"))
            seen_contracts[contract] = i
        elif "contract" in s:
            out.append(diag("classification.schema", f"{where}: contract must be a non-empty string"))

        # profileId: format + uniqueness, and its version must equal profileVersion.
        pid = s.get("profileId")
        pid_version = None
        if _nonempty_str(pid):
            m = PROFILE_ID_RE.match(pid)
            if not m:
                out.append(diag("classification.bad_profile_id",
                                f"{where}: profileId '{pid}' must match <family>.<name>.v<major>"))
            else:
                pid_version = int(m.group(1))
            if pid in seen_profile_ids:
                out.append(diag("classification.duplicate_profile_id",
                                f"{where}: duplicate profileId '{pid}'"))
            seen_profile_ids[pid] = i
        elif "profileId" in s:
            out.append(diag("classification.bad_profile_id", f"{where}: profileId must be a non-empty string"))

        pv = s.get("profileVersion")
        if not (isinstance(pv, int) and not isinstance(pv, bool) and pv >= 1):
            if "profileVersion" in s:
                out.append(diag("classification.schema",
                                f"{where}: profileVersion must be a positive integer"))
        elif pid_version is not None and pid_version != pv:
            out.append(diag("classification.profile_version_mismatch",
                            f"{where}: profileVersion {pv} != profileId version v{pid_version}"))

        # source: a .sol path whose basename matches the contract.
        src = s.get("source")
        if _nonempty_str(src):
            if not src.endswith(".sol"):
                out.append(diag("classification.schema", f"{where}: source '{src}' must end in .sol"))
            elif _nonempty_str(contract):
                stem = os.path.basename(src)[:-len(".sol")]
                if stem != contract:
                    out.append(diag("classification.source_contract_mismatch",
                                    f"{where}: source basename '{stem}' != contract '{contract}'"))
        elif "source" in s:
            out.append(diag("classification.schema", f"{where}: source must be a non-empty string"))

        for k in ("strength", "whenToUse"):
            if k in s and not _nonempty_str(s.get(k)):
                out.append(diag("classification.schema", f"{where}: {k} must be a non-empty string"))

        # Every scalar dimension value must be drawn from that dimension's vocabulary.
        for dim in SCALAR_DIMENSIONS:
            if dim not in s:
                continue
            val = s.get(dim)
            allowed = vocab.get(dim)
            if allowed is None:
                continue  # dimension itself was malformed; already reported
            if not _nonempty_str(val):
                out.append(diag("classification.schema", f"{where}: {dim} must be a string"))
            elif val not in allowed:
                out.append(diag("classification.unknown_dimension_value",
                                f"{where}: {dim}='{val}' not in dimensions.{dim}"))

        # characteristics: a non-empty, unique list drawn from its vocabulary.
        for dim in LIST_DIMENSIONS:
            if dim not in s:
                continue
            vals = s.get(dim)
            allowed = vocab.get(dim)
            if not isinstance(vals, list) or not vals or any(not _nonempty_str(v) for v in vals):
                out.append(diag("classification.schema",
                                f"{where}: {dim} must be a non-empty array of non-empty strings"))
                continue
            if len(set(vals)) != len(vals):
                out.append(diag("classification.schema", f"{where}: {dim} has duplicate values"))
            if allowed is not None:
                for v in vals:
                    if v not in allowed:
                        out.append(diag("classification.unknown_dimension_value",
                                        f"{where}: {dim} entry '{v}' not in dimensions.{dim}"))

    return sorted(out, key=lambda d: (d["code"], d["message"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate neutrino-solidity-samples classification.json")
    ap.add_argument("file", help="path to classification.json")
    ap.add_argument("--out", help="output dir for classification.report.json + diagnostics.json")
    args = ap.parse_args()

    doc = None
    try:
        doc = json.load(open(args.file, encoding="utf-8"))
        diagnostics = validate(doc)
    except (OSError, ValueError) as exc:
        diagnostics = [diag("classification.io", f"cannot read classification.json: {exc}")]

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    n_samples = len(doc.get("samples", [])) if isinstance(doc, dict) else 0
    report = {"ok": ok, "file": os.path.basename(args.file), "samples": n_samples,
              "diagnostics": diagnostics}

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(report, open(os.path.join(args.out, "classification.report.json"), "w"),
                  indent=2, sort_keys=True)
        json.dump({"ok": ok, "diagnostics": diagnostics},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)

    json.dump({"ok": ok, "diagnostics": diagnostics}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
