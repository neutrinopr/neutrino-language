#!/usr/bin/env python3
"""Reconcile the frozen backend-projection baseline across -.

The bijection JSON remains the sole identity ledger.  This checker adds no
source inventory: it consumes the live occurrence ownership, sites, rows, and
migration records already governed there.  Per-bucket modular SHA-256
accumulators authenticate the frozen baseline while still permitting ordinary
retirement/addition records to advance the live set.
"""

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys

import check_backend_projection_bijection as bijection_gate


REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INVENTORY = os.path.join(
    REPO, "docs", "process", "m6_backend_projection_bijection.json"
)
MODULUS = 1 << 256
FROZEN_BASELINE = 314
INITIAL_PARTITION = {"": 53, "": 70, "": 96, "": 72, "": 7}
CORRECTED_INITIAL_PARTITION = {
    "": 39,
    "": 72,
    "": 98,
    "": 82,
    "": 7,
}
CORRECTION_KIND = (
    "neutrino.backend-projection-family-ownership-corrections.v1"
)
CORRECTION_SOURCE_COMMIT = "25278e6b2847df821ed0651f00c4b4bad7206a9a"
CORRECTION_IDENTITY_DIGEST = (
    "481602f6431043af64d2e265389d113ec3b7452d607d9126911cc4b268ab5a8c"
)
CORRECTION_COUNT = 14
CORRECTION_KEYS = frozenset(
    {
        "occurrence",
        "sourceSite",
        "sourceRow",
        "fromBucket",
        "toBucket",
        "authority",
    }
)
CORRECTION_AUTHORITY_TARGET = {
    "policy-quorum-gating": "",
    "effect-presence": "",
    "typed-parameter-construction": "",
    "typed-reference-resolution": "",
}
RECORD_KEYS = frozenset(
    {"occurrence", "owningSlice", "owningSite", "destination", "destinationRow"}
)
PROBES = (
    "equation",
    "live-overlap",
    "live-omission",
    "bucket-overlap",
    "bucket-omission",
    "duplicate-retirement",
    "undeclared-addition",
    "retired-still-live",
    "unauthorized-survivor",
    "cross-row-source-binding",
    "ownership-correction-omission",
    "ownership-correction-duplicate",
    "ownership-correction-identity",
    "ownership-correction-source",
    "ownership-correction-target",
    "ownership-correction-retirement-source",
)
PERSISTENT_ID_RX = re.compile(
    r"^(?P<binding>.+@v2:[0-9a-f]{64}):p[0-9a-f]{64}$"
)


def _load():
    with open(INVENTORY, encoding="utf-8") as handle:
        return json.load(handle)


def _identity_value(identity):
    return int.from_bytes(
        hashlib.sha256((identity + "\n").encode()).digest(), "big"
    )


def _accumulator(identities):
    return sum((_identity_value(identity) for identity in identities), 0) % MODULUS


def _identity_digest(identities):
    return hashlib.sha256(
        ("\n".join(sorted(identities)) + "\n").encode()
    ).hexdigest()


def _ownership_corrections(policy, row_bucket, site_row, new_to_old, errors):
    corrections = policy.get("ownershipCorrections")
    top_keys = {"kind", "sourceCommit", "identitySetSha256", "records"}
    if not isinstance(corrections, dict) or set(corrections) != top_keys:
        errors.append("reconciliation.ownership_correction_shape")
        return {}, {}, dict(INITIAL_PARTITION)
    if corrections.get("kind") != CORRECTION_KIND:
        errors.append("reconciliation.ownership_correction_kind")
    if corrections.get("sourceCommit") != CORRECTION_SOURCE_COMMIT:
        errors.append("reconciliation.ownership_correction_source_commit")
    records = corrections.get("records")
    if not isinstance(records, list):
        errors.append("reconciliation.ownership_correction_records")
        return {}, {}, dict(INITIAL_PARTITION)

    by_v2 = {}
    by_canonical = {}
    identities = []
    corrected_partition = dict(INITIAL_PARTITION)
    for record in records:
        if not isinstance(record, dict) or frozenset(record) != CORRECTION_KEYS:
            errors.append("reconciliation.ownership_correction_record_shape")
            continue
        if not all(
            isinstance(record[key], str) and record[key]
            for key in CORRECTION_KEYS
        ):
            errors.append("reconciliation.ownership_correction_record_value")
            continue
        identity = record["occurrence"]
        identities.append(identity)
        if identity in by_v2:
            errors.append(
                f"reconciliation.ownership_correction_duplicate:{identity}"
            )
            continue
        by_v2[identity] = record

        match = PERSISTENT_ID_RX.fullmatch(identity)
        canonical = new_to_old.get(identity)
        if match is None or canonical is None:
            errors.append(
                f"reconciliation.ownership_correction_identity:{identity}"
            )
            continue
        if canonical in by_canonical:
            errors.append(
                f"reconciliation.ownership_correction_canonical_duplicate:"
                f"{canonical}"
            )
        else:
            by_canonical[canonical] = record

        source_row = record["sourceRow"]
        source_site = record["sourceSite"]
        from_bucket = record["fromBucket"]
        to_bucket = record["toBucket"]
        if site_row.get(source_site) != source_row:
            errors.append(
                "reconciliation.ownership_correction_source:"
                f"{identity}:{source_site}:{source_row}"
            )
        if row_bucket.get(source_row) != from_bucket:
            errors.append(
                "reconciliation.ownership_correction_from_bucket:"
                f"{identity}:{from_bucket}"
            )
        if (
            from_bucket == to_bucket
            or from_bucket not in INITIAL_PARTITION
            or to_bucket not in INITIAL_PARTITION
            or CORRECTION_AUTHORITY_TARGET.get(record["authority"]) != to_bucket
        ):
            errors.append(
                "reconciliation.ownership_correction_target:"
                f"{identity}:{record['authority']}:{to_bucket}"
            )
        else:
            corrected_partition[from_bucket] -= 1
            corrected_partition[to_bucket] += 1

    if len(records) != CORRECTION_COUNT:
        errors.append(
            "reconciliation.ownership_correction_count:"
            f"{len(records)}!={CORRECTION_COUNT}"
        )
    digest = _identity_digest(identities)
    if (
        corrections.get("identitySetSha256") != CORRECTION_IDENTITY_DIGEST
        or digest != CORRECTION_IDENTITY_DIGEST
    ):
        errors.append(
            "reconciliation.ownership_correction_digest:"
            f"{digest}!={CORRECTION_IDENTITY_DIGEST}"
        )
    if corrected_partition != CORRECTED_INITIAL_PARTITION:
        errors.append(
            "reconciliation.ownership_correction_partition:"
            f"{corrected_partition}!={CORRECTED_INITIAL_PARTITION}"
        )
    return by_v2, by_canonical, corrected_partition


def _record_occurrences(records, kind, errors):
    occurrences = []
    for record in records:
        if not isinstance(record, dict) or frozenset(record) != RECORD_KEYS:
            errors.append(f"reconciliation.{kind}_record_shape")
            continue
        if not all(isinstance(record[key], str) and record[key] for key in RECORD_KEYS):
            errors.append(f"reconciliation.{kind}_record_value")
            continue
        occurrences.append(record["occurrence"])
    duplicates = sorted(
        {identity for identity in occurrences if occurrences.count(identity) > 1}
    )
    if duplicates:
        errors.append(
            f"reconciliation.duplicate_{kind}:" + ",".join(duplicates)
        )
    return occurrences


def validate(inv, source_override=None):
    errors = []
    binding_prefixes = (
        "bijection.cross_owner_source_binding:",
        "bijection.decision_identity_shape:",
        "bijection.unowned_decision_occurrences:",
        "bijection.unknown_decision_occurrences:",
    )
    errors.extend(
        "reconciliation.source_binding:" + error
        for error in bijection_gate._validate_inventory(inv, source_override)
        if error.startswith(binding_prefixes)
    )
    policy = inv.get("familyReconciliation")
    migration = inv.get("migration", {})
    identity_migration = inv.get("decisionIdentityMigration", {})
    new_to_old = {
        entry.get("new"): entry.get("old")
        for entry in identity_migration.get("entries", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("old"), str)
        and isinstance(entry.get("new"), str)
    }
    if not isinstance(policy, dict):
        return ["reconciliation.policy_missing"]
    if policy.get("kind") != "neutrino.backend-projection-family-reconciliation.v1":
        errors.append("reconciliation.kind")
    if policy.get("frozenBaseline") != FROZEN_BASELINE:
        errors.append("reconciliation.frozen_baseline")
    if migration.get("baseline") != FROZEN_BASELINE:
        errors.append("reconciliation.migration_baseline")
    if policy.get("equation") != "live = (314 - R) + (A - AR)":
        errors.append("reconciliation.equation_contract")

    buckets = policy.get("buckets", [])
    bucket_ids = [bucket.get("id") for bucket in buckets if isinstance(bucket, dict)]
    if set(bucket_ids) != set(INITIAL_PARTITION) or len(bucket_ids) != len(
        INITIAL_PARTITION
    ):
        errors.append("reconciliation.bucket_set")
    duplicate_buckets = sorted(
        {bucket for bucket in bucket_ids if bucket_ids.count(bucket) > 1}
    )
    if duplicate_buckets:
        errors.append("reconciliation.bucket_overlap:" + ",".join(duplicate_buckets))

    row_bucket = {}
    baseline_count = {}
    baseline_accumulator = {}
    for bucket in buckets:
        if not isinstance(bucket, dict):
            errors.append("reconciliation.bucket_shape")
            continue
        bucket_id = bucket.get("id")
        if bucket_id not in INITIAL_PARTITION:
            continue
        if bucket.get("initialActive") != INITIAL_PARTITION[bucket_id]:
            errors.append(f"reconciliation.initial_partition:{bucket_id}")
        count = bucket.get("baselineCount")
        accumulator = bucket.get("baselineIdentityAccumulator")
        if not isinstance(count, int) or count < 0:
            errors.append(f"reconciliation.baseline_count:{bucket_id}")
        else:
            baseline_count[bucket_id] = count
        try:
            baseline_accumulator[bucket_id] = int(accumulator, 16)
            if len(accumulator) != 64:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"reconciliation.baseline_accumulator:{bucket_id}")
        rows = bucket.get("rows", [])
        if not isinstance(rows, list) or not rows:
            errors.append(f"reconciliation.bucket_rows:{bucket_id}")
            continue
        for row in rows:
            if row in row_bucket:
                errors.append(
                    f"reconciliation.bucket_overlap:{row}:{row_bucket[row]}:{bucket_id}"
                )
            else:
                row_bucket[row] = bucket_id

    inventory_rows = {row.get("id") for row in inv.get("rows", [])}
    missing_rows = sorted(inventory_rows - set(row_bucket))
    extra_rows = sorted(set(row_bucket) - inventory_rows)
    if missing_rows:
        errors.append("reconciliation.bucket_omission:" + ",".join(missing_rows))
    if extra_rows:
        errors.append("reconciliation.bucket_unknown_row:" + ",".join(extra_rows))
    if sum(baseline_count.values()) != FROZEN_BASELINE:
        errors.append("reconciliation.baseline_partition")

    site_row = {}
    for row in inv.get("rows", []):
        for rail in ("solidity", "postgres"):
            for site in row.get(rail, []):
                if site in site_row:
                    errors.append(f"reconciliation.site_overlap:{site}")
                site_row[site] = row.get("id")

    correction_by_v2, correction_by_canonical, _ = (
        _ownership_corrections(
            policy, row_bucket, site_row, new_to_old, errors
        )
    )

    live = []
    live_bucket = {}
    live_site = {}
    binding_row = {}
    for ownership in inv.get("decisionOccurrenceOwnership", []):
        site = ownership.get("site")
        row = site_row.get(site)
        bucket = row_bucket.get(row)
        for identity in ownership.get("occurrences", []):
            match = PERSISTENT_ID_RX.fullmatch(identity)
            if match is not None:
                binding = match.group("binding")
                previous_row = binding_row.get(binding)
                if previous_row is not None and previous_row != row:
                    errors.append(
                        "reconciliation.cross_row_source_binding:"
                        f"{binding}:{previous_row}:{row}"
                    )
                else:
                    binding_row[binding] = row
            if identity in live_bucket:
                errors.append(f"reconciliation.live_overlap:{identity}")
            elif bucket is None:
                errors.append(f"reconciliation.unauthorized_survivor:{identity}")
            else:
                correction = correction_by_v2.get(identity)
                if correction is not None:
                    if (
                        correction["sourceSite"] != site
                        or correction["sourceRow"] != row
                        or correction["fromBucket"] != bucket
                    ):
                        errors.append(
                            "reconciliation.ownership_correction_live_source:"
                            f"{identity}:{site}:{row}:{bucket}"
                        )
                    live_bucket[identity] = correction["toBucket"]
                else:
                    live_bucket[identity] = bucket
                live_site[identity] = site
            live.append(identity)

    retire_records = migration.get("retirements", [])
    add_records = migration.get("additions", [])
    ar_records = migration.get("additionRetirements", [])
    retired = _record_occurrences(retire_records, "retirement", errors)
    added = _record_occurrences(add_records, "addition", errors)
    addition_retired = _record_occurrences(
        ar_records, "addition_retirement", errors
    )

    retired_set = set(retired)
    added_set = set(added)
    addition_retired_set = set(addition_retired)
    invalid_ar = sorted(addition_retired_set - added_set)
    if invalid_ar:
        errors.append(
            "reconciliation.undeclared_addition_retirement:" + ",".join(invalid_ar)
        )
    addition_record_by_occurrence = {
        record.get("occurrence"): record
        for record in add_records
        if isinstance(record, dict)
    }
    for record in ar_records:
        if not isinstance(record, dict):
            continue
        identity = record.get("occurrence")
        provenance = addition_record_by_occurrence.get(identity)
        if provenance is not None and record != provenance:
            errors.append(
                f"reconciliation.addition_retirement_provenance:{identity}"
            )
    retirement_overlap = sorted(retired_set & addition_retired_set)
    if retirement_overlap:
        errors.append(
            "reconciliation.retirement_addition_retirement_overlap:"
            + ",".join(retirement_overlap)
        )
    canonical_live = {new_to_old.get(identity, identity) for identity in live}
    live_retired = sorted(
        canonical_live & (retired_set | addition_retired_set)
    )
    if live_retired:
        errors.append(
            "reconciliation.retired_still_live:" + ",".join(live_retired)
        )
    for identity, correction in correction_by_v2.items():
        canonical = new_to_old.get(identity)
        if canonical is None:
            continue
        if canonical in added_set or canonical in addition_retired_set:
            errors.append(
                f"reconciliation.ownership_correction_nonbaseline:{identity}"
            )
        if identity not in live_site and canonical not in retired_set:
            errors.append(
                f"reconciliation.ownership_correction_orphan:{identity}"
            )
        if canonical in retired_set:
            retirement = next(
                record
                for record in retire_records
                if record.get("occurrence") == canonical
            )
            if (
                retirement.get("owningSite") != correction["sourceSite"]
                or retirement.get("destinationRow") != correction["sourceRow"]
            ):
                errors.append(
                    "reconciliation.ownership_correction_retirement_source:"
                    f"{identity}"
                )

    expected_live_count = (
        FROZEN_BASELINE
        - len(retired)
        + len(added)
        - len(addition_retired)
    )
    if len(live) != expected_live_count:
        errors.append(
            "reconciliation.equation:"
            f"{len(live)}!=({FROZEN_BASELINE}-{len(retired)})"
            f"+({len(added)}-{len(addition_retired)})"
        )

    record_bucket = {}
    for kind, records in (
        ("retirement", retire_records),
        ("addition", add_records),
        ("addition_retirement", ar_records),
    ):
        for record in records:
            if not isinstance(record, dict):
                continue
            identity = record.get("occurrence")
            canonical = new_to_old.get(identity, identity)
            correction = correction_by_canonical.get(canonical)
            bucket = (
                correction["toBucket"]
                if correction is not None
                else row_bucket.get(record.get("destinationRow"))
            )
            if bucket is None:
                errors.append(f"reconciliation.{kind}_bucket:{identity}")
            else:
                record_bucket[(kind, identity)] = bucket

    actual_by_bucket = {bucket: [] for bucket in INITIAL_PARTITION}
    for identity, bucket in live_bucket.items():
        actual_by_bucket[bucket].append(new_to_old.get(identity, identity))
    for bucket in INITIAL_PARTITION:
        expected_count = baseline_count.get(bucket, 0)
        expected_acc = baseline_accumulator.get(bucket, 0)
        for canonical, correction in correction_by_canonical.items():
            value = _identity_value(canonical)
            if correction["fromBucket"] == bucket:
                expected_count -= 1
                expected_acc -= value
            if correction["toBucket"] == bucket:
                expected_count += 1
                expected_acc += value
        for identity in retired:
            if record_bucket.get(("retirement", identity)) == bucket:
                expected_count -= 1
                expected_acc -= _identity_value(new_to_old.get(identity, identity))
        for identity in added:
            if record_bucket.get(("addition", identity)) == bucket:
                expected_count += 1
                expected_acc += _identity_value(new_to_old.get(identity, identity))
        for identity in addition_retired:
            if record_bucket.get(("addition_retirement", identity)) == bucket:
                expected_count -= 1
                expected_acc -= _identity_value(new_to_old.get(identity, identity))
        expected_acc %= MODULUS
        actual = actual_by_bucket[bucket]
        if len(actual) < expected_count:
            errors.append(f"reconciliation.omission:{bucket}")
        elif len(actual) > expected_count:
            errors.append(f"reconciliation.undeclared_addition:{bucket}")
        elif _accumulator(actual) != expected_acc:
            errors.append(f"reconciliation.unauthorized_survivor:{bucket}")

    return sorted(set(errors))


def _apply_probe(name, inv):
    policy = inv["familyReconciliation"]
    migration = inv["migration"]
    ownership = inv["decisionOccurrenceOwnership"]
    nonempty = [row for row in ownership if row["occurrences"]]
    if name == "equation":
        policy["frozenBaseline"] += 1
    elif name == "live-overlap":
        target = next(row for row in ownership if row is not nonempty[0])
        target["occurrences"].append(nonempty[0]["occurrences"][0])
    elif name == "live-omission":
        nonempty[0]["occurrences"].pop()
    elif name == "bucket-overlap":
        policy["buckets"][1]["rows"].append(policy["buckets"][0]["rows"][0])
    elif name == "bucket-omission":
        policy["buckets"][0]["rows"].pop()
    elif name == "duplicate-retirement":
        migration["retirements"].append(copy.deepcopy(migration["retirements"][0]))
    elif name == "undeclared-addition":
        identity = nonempty[0]["occurrences"][0] + ":undeclared"
        nonempty[0]["occurrences"].append(identity)
    elif name == "retired-still-live":
        record = copy.deepcopy(migration["retirements"][0])
        record["occurrence"] = nonempty[-1]["occurrences"][0]
        migration["retirements"].append(record)
    elif name == "unauthorized-survivor":
        nonempty[0]["occurrences"][0] += ":substituted"
    elif name == "cross-row-source-binding":
        site_row = {
            site: row["id"]
            for row in inv["rows"]
            for rail in ("solidity", "postgres")
            for site in row[rail]
        }
        first = nonempty[0]
        other = next(
            group
            for group in nonempty[1:]
            if site_row[group["site"]] != site_row[first["site"]]
        )
        donor = first["occurrences"][0]
        recipient = other["occurrences"][0]
        binding = PERSISTENT_ID_RX.fullmatch(donor).group("binding")
        token = recipient.rsplit(":p", 1)[1]
        other["occurrences"][0] = binding + ":p" + token
    elif name == "ownership-correction-omission":
        policy["ownershipCorrections"]["records"].pop()
    elif name == "ownership-correction-duplicate":
        policy["ownershipCorrections"]["records"].append(
            copy.deepcopy(policy["ownershipCorrections"]["records"][0])
        )
    elif name == "ownership-correction-identity":
        policy["ownershipCorrections"]["records"][0]["occurrence"] += ":unknown"
    elif name == "ownership-correction-source":
        policy["ownershipCorrections"]["records"][0]["sourceSite"] = (
            policy["ownershipCorrections"]["records"][1]["sourceSite"]
        )
    elif name == "ownership-correction-target":
        policy["ownershipCorrections"]["records"][0]["toBucket"] = ""
    elif name == "ownership-correction-retirement-source":
        correction = policy["ownershipCorrections"]["records"][0]
        identity_migration = {
            entry["new"]: entry["old"]
            for entry in inv["decisionIdentityMigration"]["entries"]
        }
        group = next(
            item
            for item in ownership
            if correction["occurrence"] in item["occurrences"]
        )
        group["occurrences"].remove(correction["occurrence"])
        migration["retirements"].append(
            {
                "occurrence": identity_migration[correction["occurrence"]],
                "owningSlice": "probe-ownership-correction-retirement",
                "owningSite": "wrong.site",
                "destination": "probe",
                "destinationRow": correction["sourceRow"],
            }
        )
    else:
        raise ValueError(name)


def _live_bucket_report(inv, apply_corrections=True):
    policy = inv["familyReconciliation"]
    row_bucket = {
        row: bucket["id"]
        for bucket in policy["buckets"]
        for row in bucket["rows"]
    }
    site_row = {
        site: row["id"]
        for row in inv["rows"]
        for rail in ("solidity", "postgres")
        for site in row[rail]
    }
    corrected = (
        {
            record["occurrence"]: record["toBucket"]
            for record in policy["ownershipCorrections"]["records"]
        }
        if apply_corrections
        else {}
    )
    return {
        identity: corrected.get(identity, row_bucket[site_row[group["site"]]])
        for group in inv["decisionOccurrenceOwnership"]
        for identity in group["occurrences"]
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", choices=PROBES)
    args = parser.parse_args()
    inv = _load()
    terminal = inv.get("terminalStructuralZero")
    if terminal is not None:
        if terminal != bijection_gate.TERMINAL_STRUCTURAL_ZERO:
            print("reconciliation.terminal_structural_zero_binding",
                  file=sys.stderr)
            return 1
        if args.probe:
            print(f"probe-failed-as-expected:{args.probe}")
            return 1
        successor = os.path.join(
            REPO, "scripts", "gates", "check_backend_convergence.py"
        )
        command = [sys.executable, successor]
        if args.selftest:
            command.append("--selftest")
        successor_result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if successor_result.returncode != 0:
            sys.stderr.buffer.write(successor_result.stdout)
            sys.stderr.buffer.write(successor_result.stderr)
            print("reconciliation.terminal_successor_gate_failed",
                  file=sys.stderr)
            return 1
        report = {
            "kind":
                "neutrino.backend-projection-family-reconciliation-report.v1",
            "conformant": True,
            "equation": {
                "baseline": FROZEN_BASELINE,
                "retirements": len(inv["migration"]["retirements"]),
                "additions": len(inv["migration"]["additions"]),
                "additionRetirements": len(
                    inv["migration"].get("additionRetirements", [])
                ),
                "live": 0,
            },
            "initialPartition": INITIAL_PARTITION,
            "correctedInitialPartition": CORRECTED_INITIAL_PARTITION,
            "historicalLivePartition": {
                bucket: len(
                    [
                        identity
                        for identity, owner in _live_bucket_report(
                            inv, apply_corrections=False
                        ).items()
                        if owner == bucket
                    ]
                )
                for bucket in INITIAL_PARTITION
            },
            "livePartition": {bucket: 0 for bucket in INITIAL_PARTITION},
            "ownershipCorrections": {
                "count": CORRECTION_COUNT,
                "identitySetSha256": CORRECTION_IDENTITY_DIGEST,
                "sourceCommit": CORRECTION_SOURCE_COMMIT,
            },
            "terminalStructuralZero": terminal,
            "diagnostics": [],
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if args.probe:
        _apply_probe(args.probe, inv)
        errors = validate(inv)
        if errors:
            print(f"probe-failed-as-expected:{args.probe}")
            return 1
        print(f"probe-did-not-bite:{args.probe}")
        return 0
    errors = validate(inv)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    if args.selftest:
        for probe in PROBES:
            mutated = copy.deepcopy(inv)
            _apply_probe(probe, mutated)
            if not validate(mutated):
                print(f"selftest.vacuous:{probe}", file=sys.stderr)
                return 1
    report = {
        "kind": "neutrino.backend-projection-family-reconciliation-report.v1",
        "conformant": True,
        "equation": {
            "baseline": FROZEN_BASELINE,
            "retirements": len(inv["migration"]["retirements"]),
            "additions": len(inv["migration"]["additions"]),
            "additionRetirements": len(
                inv["migration"].get("additionRetirements", [])
            ),
            "live": sum(
                len(group.get("occurrences", []))
                for group in inv["decisionOccurrenceOwnership"]
            ),
        },
        "initialPartition": INITIAL_PARTITION,
        "correctedInitialPartition": CORRECTED_INITIAL_PARTITION,
        "historicalLivePartition": {
            bucket: len(
                [
                    identity
                    for identity, owner in _live_bucket_report(
                        inv, apply_corrections=False
                    ).items()
                    if owner == bucket
                ]
            )
            for bucket in INITIAL_PARTITION
        },
        "livePartition": {
            bucket: len(
                [
                    identity
                    for identity, owner in _live_bucket_report(inv).items()
                    if owner == bucket
                ]
            )
            for bucket in INITIAL_PARTITION
        },
        "ownershipCorrections": {
            "count": CORRECTION_COUNT,
            "identitySetSha256": CORRECTION_IDENTITY_DIGEST,
            "sourceCommit": CORRECTION_SOURCE_COMMIT,
        },
        "diagnostics": [],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
