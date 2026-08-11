#!/usr/bin/env python3
"""Deterministic, receipt-verified pack resolver for the M6 release gate.

The release corpus is hydrated exclusively from published domain packs, without
trusting the pack bytes on faith.

This module owns ONLY the resolution path; it REUSES the public conformance
verifier (`scripts/validators/verify_domain_pack.py`) unchanged — it does not
re-implement pack verification. Resolution is FAIL-CLOSED and deterministic: any
inconsistency between the release receipt, the pack manifest identity, and the
bundle-verified payload inventory raises `PackResolutionError`.

The receipt is the standard `neutrino.domain-pack-verification-receipt`
published with an external pack, NOT the runtime late-binding
`binding-receipt` — a different kind with a different trust role.

Resolution order (each step raises on failure):
  1. Load the receipt; assert kind ==
     neutrino.domain-pack-verification-receipt, outcome == VERIFIED,
     targetsBundle.bundleDigest == coords.bundleDigest, and
     pack.packDigest == coords.packDigest.
  2. Load packPath/pack.json; assert pack.packDigest == coords.packDigest ==
     canonical_pack_digest(pack) (manifest identity is self-consistent AND the
     receipt attests THIS manifest).
  2b. Bind coords/receipt/pack to one exact (bundleVersion, bundleDigest) row
     in the committed closed bundle registry. The selected current or historical
     bundle bytes must independently reproduce that exact tuple.
  3. Run the reused verifier against the selected bundle; any diagnostic fails
     closed (the released bundle rejects the pack -> untrusted).
  4. Map payload roles (capability-spec/source/scenario) to concrete paths and
     return a HydratedMember.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
from typing import Optional

REPO = Path(__file__).resolve().parents[2]

# Reuse the public conformance verifier unchanged (do NOT modify it).
sys.path.insert(0, str(REPO / "scripts" / "validators"))
import verify_domain_pack as verifier  # noqa: E402
sys.path.insert(0, str(REPO / "scripts"))
import verify_public_pack_receipt as public_receipts  # noqa: E402

RECEIPT_KIND = "neutrino.domain-pack-verification-receipt"


class PackResolutionError(RuntimeError):
    """A pack failed deterministic, receipt-verified resolution (fail-closed)."""


@dataclass(frozen=True)
class HydratedMember:
    """The concrete on-disk locations a hydrated curated member resolves to.

    `spec_path` is None when the pack carries no `capability-spec` payload."""

    root: Path
    spec_path: Optional[Path]
    source_path: Optional[Path]
    scenario_dir: Optional[Path]


@dataclass(frozen=True)
class ResolvedBundle:
    """One exact, locally committed current or historical bundle."""

    path: Path
    root: Path
    version: str
    digest: str
    status: str


def _load_json(path: Path, what: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as error:
        raise PackResolutionError(f"cannot read {what} {path}: {error}") from error
    except ValueError as error:
        raise PackResolutionError(f"{what} {path} is not valid JSON: {error}") from error


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PackResolutionError(message)


def _abs(value, repo: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo / path


def _canonical_bundle_digest(bundle: dict) -> str:
    body = {key: value for key, value in bundle.items() if key != "bundleDigest"}
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _select_bundle(
    version: str,
    digest: str,
    *,
    repo: Path,
    registry_path: Optional[Path] = None,
) -> ResolvedBundle:
    """Select an exact bundle tuple from the closed local registry.

    There is deliberately no fallback, compatible-version search, digest alias,
    or network lookup. Registry rows and selected bundle bytes are both checked
    before the public verifier sees a pack.
    """
    repo = repo.resolve()
    registry_path = registry_path or repo / "docs" / "core-contract-bundle-registry.json"
    registry = _load_json(registry_path, "core-contract bundle registry")
    _require(
        isinstance(registry, dict)
        and set(registry) == {"kind", "schemaVersion", "bundles"}
        and registry.get("kind") == "neutrino.core-contract-bundle-registry"
        and registry.get("schemaVersion") == 1
        and isinstance(registry.get("bundles"), list),
        "core-contract bundle registry has an invalid closed envelope",
    )

    rows = registry["bundles"]
    _require(rows, "core-contract bundle registry must not be empty")
    exact_keys = {
        "bundleVersion",
        "bundleDigest",
        "bundleFileSha256",
        "bundlePath",
        "status",
    }
    seen_versions: set[str] = set()
    seen_digests: set[str] = set()
    current_count = 0
    selected = None
    for index, row in enumerate(rows):
        _require(
            isinstance(row, dict) and set(row) == exact_keys,
            f"core-contract bundle registry row {index} has an invalid closed shape",
        )
        row_version = row["bundleVersion"]
        row_digest = row["bundleDigest"]
        row_file_sha = row["bundleFileSha256"]
        row_path = row["bundlePath"]
        row_status = row["status"]
        _require(
            isinstance(row_version, str)
            and isinstance(row_digest, str)
            and isinstance(row_file_sha, str)
            and isinstance(row_path, str)
            and row_status in ("current", "historical"),
            f"core-contract bundle registry row {index} has invalid field values",
        )
        _require(
            row_version not in seen_versions,
            f"core-contract bundle registry aliases version {row_version!r}",
        )
        _require(
            row_digest not in seen_digests,
            f"core-contract bundle registry aliases digest {row_digest!r}",
        )
        seen_versions.add(row_version)
        seen_digests.add(row_digest)
        current_count += row_status == "current"

        relative = Path(row_path)
        _require(
            not relative.is_absolute()
            and ".." not in relative.parts
            and relative.as_posix() == row_path,
            f"core-contract bundle registry row {index} has a non-normalized path",
        )
        unresolved_path = repo / relative
        _require(
            unresolved_path.is_file() and not unresolved_path.is_symlink(),
            f"core-contract bundle registry row {index} does not name a regular bundle",
        )
        candidate_path = unresolved_path.resolve()
        try:
            candidate_path.relative_to(repo)
        except ValueError as error:
            raise PackResolutionError(
                f"core-contract bundle registry row {index} escapes the repository"
            ) from error
        candidate = _load_json(candidate_path, f"registered bundle row {index}")
        _require(
            isinstance(candidate, dict),
            f"registered bundle row {index} is not a JSON object",
        )
        recomputed = _canonical_bundle_digest(candidate)
        raw_sha = "sha256:" + hashlib.sha256(candidate_path.read_bytes()).hexdigest()
        _require(
            candidate.get("bundleVersion") == row_version
            and candidate.get("bundleDigest") == row_digest
            and recomputed == row_digest,
            f"registered bundle row {index} tuple does not match its exact bytes",
        )
        _require(
            raw_sha == row_file_sha,
            f"registered bundle row {index} exact file bytes do not match their pin",
        )
        if row_version == version and row_digest == digest:
            selected = ResolvedBundle(
                path=candidate_path,
                root=repo,
                version=row_version,
                digest=row_digest,
                status=row_status,
            )

    _require(
        current_count == 1,
        f"core-contract bundle registry has {current_count} current rows; expected 1",
    )
    _require(
        selected is not None,
        f"no registered core-contract bundle for exact tuple ({version!r}, {digest!r})",
    )
    return selected


def resolve_member(
    member: str,
    coords: dict,
    *,
    repo: Path = REPO,
    bundle_registry_path: Optional[Path] = None,
) -> HydratedMember:
    """Resolve one curated member from a published, receipt-verified pack.

    `coords` carries {packPath, receiptPath, packDigest, bundleDigest}; packPath is
    the pack ROOT directory (its manifest is packPath/pack.json). Relative
    packPath/receiptPath resolve against `repo`. Fail-closed at every step."""
    for key in ("packPath", "receiptPath", "packDigest", "bundleDigest"):
        _require(key in coords, f"{member}: pack coords missing {key!r}")

    pack_root = _abs(coords["packPath"], repo)
    receipt_path = _abs(coords["receiptPath"], repo)
    want_pack_digest = coords["packDigest"]
    want_bundle_digest = coords["bundleDigest"]

    # (1) The release receipt attests THIS pack against THIS bundle with a GO.
    receipt = _load_json(receipt_path, f"{member} receipt")
    _require(
        isinstance(receipt, dict),
        f"{member}: receipt {receipt_path} is not a JSON object",
    )
    if receipt.get("kind") == public_receipts.KIND:
        try:
            verified = public_receipts.verify(repo, receipt_path)
        except (OSError, ValueError) as error:
            raise PackResolutionError(
                f"{member}: public receipt verification failed: {error}"
            ) from error
        _require(
            verified.get("packId") == member
            and verified.get("packPath") == coords["packPath"]
            and verified.get("declaredPackDigest") == want_pack_digest
            and verified.get("coreContractBundleDigest") == want_bundle_digest,
            f"{member}: public receipt does not match the curated coordinate",
        )
        pack = _load_json(pack_root / "pack.json", f"{member} pack manifest")
        targets_bundle = pack.get("targetsBundle")
        _require(
            isinstance(pack, dict)
            and pack.get("packId") == member
            and pack.get("packDigest") == want_pack_digest
            and isinstance(targets_bundle, dict)
            and targets_bundle.get("bundleDigest") == want_bundle_digest,
            f"{member}: public pack identity does not match its coordinate",
        )
        role_paths: dict[str, str] = {}
        for row in pack.get("payloads", []):
            if not isinstance(row, dict):
                continue
            role = row.get("role")
            path = row.get("path")
            if role in ("capability-spec", "source", "scenario") and isinstance(path, str):
                _require(role not in role_paths,
                         f"{member}: pack declares role {role!r} more than once")
                role_paths[role] = path

        def _public_payload(role: str) -> Optional[Path]:
            relative = role_paths.get(role)
            return None if relative is None else pack_root.joinpath(*relative.split("/"))

        scenario_payload = _public_payload("scenario")
        return HydratedMember(
            root=pack_root,
            spec_path=_public_payload("capability-spec"),
            source_path=_public_payload("source"),
            scenario_dir=(scenario_payload.parent
                          if scenario_payload is not None else None),
        )
    _require(
        receipt.get("kind") == RECEIPT_KIND,
        f"{member}: receipt kind {receipt.get('kind')!r} != {RECEIPT_KIND!r}",
    )
    _require(
        receipt.get("outcome") == "VERIFIED",
        f"{member}: receipt outcome {receipt.get('outcome')!r} != 'VERIFIED'",
    )
    release = receipt.get("targetsBundle")
    _require(
        isinstance(release, dict)
        and release.get("bundleDigest") == want_bundle_digest,
        f"{member}: receipt targetsBundle.bundleDigest "
        f"{(release or {}).get('bundleDigest') if isinstance(release, dict) else release!r} "
        f"!= coords bundleDigest {want_bundle_digest!r}",
    )
    candidate = receipt.get("pack")
    _require(
        isinstance(candidate, dict)
        and candidate.get("packDigest") == want_pack_digest,
        f"{member}: receipt pack.packDigest "
        f"{(candidate or {}).get('packDigest') if isinstance(candidate, dict) else candidate!r} "
        f"!= coords packDigest {want_pack_digest!r}",
    )

    # (2) The pack manifest identity is self-consistent AND the receipt attests it.
    pack_manifest = pack_root / "pack.json"
    pack = _load_json(pack_manifest, f"{member} pack manifest")
    _require(
        isinstance(pack, dict),
        f"{member}: pack manifest {pack_manifest} is not a JSON object",
    )
    recomputed = verifier.canonical_pack_digest(pack)
    _require(
        pack.get("packDigest") == want_pack_digest == recomputed,
        f"{member}: pack identity mismatch: manifest {pack.get('packDigest')!r}, "
        f"coords {want_pack_digest!r}, recomputed {recomputed!r}",
    )

    # (2b) Bind coords + receipt + pack to one exact row in the committed closed
    # registry. Existing immutable packs keep their historical tuple; current
    # packs select the current tuple. The registry selection independently checks
    # that the selected bundle bytes reproduce their registered identity.
    targets_bundle = pack.get("targetsBundle")
    _require(
        isinstance(targets_bundle, dict) and isinstance(release, dict),
        f"{member}: pack and receipt targetsBundle must both be objects",
    )
    release_tuple = (
        release.get("bundleVersion"),
        release.get("bundleDigest"),
    )
    pack_tuple = (
        targets_bundle.get("bundleVersion"),
        targets_bundle.get("bundleDigest"),
    )
    _require(
        release.get("bundleId") == targets_bundle.get("bundleId")
        and release_tuple == pack_tuple
        and pack_tuple[1] == want_bundle_digest,
        f"{member}: receipt/pack/coords bundle tuple mismatch: "
        f"receipt {release_tuple!r}, pack {pack_tuple!r}, "
        f"coords digest {want_bundle_digest!r}",
    )
    selected_bundle = _select_bundle(
        pack_tuple[0],
        pack_tuple[1],
        repo=repo,
        registry_path=bundle_registry_path,
    )
    _require(
        targets_bundle.get("bundleId") == "neutrino.core-contract-bundle",
        f"{member}: pack targets unexpected bundleId "
        f"{targets_bundle.get('bundleId')!r}",
    )

    # (2c) Bind the REQUESTED member to the pack + receipt identity (3-way). The
    # caller asked to hydrate `member`; the pack it resolves to (and the receipt
    # that attests it) must both name that same packId, or a valid receipt/pack
    # could be substituted for a different curated member. Missing packId -> closed.
    pack_id = pack.get("packId")
    receipt_pack_id = candidate.get("packId")
    _require(
        isinstance(pack_id, str) and isinstance(receipt_pack_id, str),
        f"{member}: pack.packId {pack_id!r} / receipt pack.packId "
        f"{receipt_pack_id!r} must both be strings",
    )
    _require(
        member == pack_id == receipt_pack_id,
        f"{member}: member/packId binding mismatch: requested member {member!r}, "
        f"pack.packId {pack_id!r}, receipt pack.packId {receipt_pack_id!r}",
    )

    # (3) The released bundle verifies the complete pack (reused verifier). Any
    # diagnostic -> the pack is not conformant against the pinned bundle.
    diags: list = []
    verifier.verify(
        selected_bundle.path,
        selected_bundle.root,
        pack_manifest,
        pack_root,
        diags,
    )
    if diags:
        raise PackResolutionError(
            f"{member}: pack failed bundle verification:\n  - "
            + "\n  - ".join(diags)
        )

    # (4) Map payload roles to concrete on-disk locations.
    role_paths: dict[str, str] = {}
    for row in pack.get("payloads", []):
        if not isinstance(row, dict):
            continue
        role = row.get("role")
        path = row.get("path")
        if role in ("capability-spec", "source", "scenario") and isinstance(path, str):
            if role in role_paths:
                raise PackResolutionError(
                    f"{member}: pack declares role {role!r} more than once"
                )
            role_paths[role] = path

    def _payload(role: str) -> Optional[Path]:
        rel = role_paths.get(role)
        if rel is None:
            return None
        return pack_root.joinpath(*rel.split("/"))

    spec_path = _payload("capability-spec")
    source_path = _payload("source")
    scenario_payload = _payload("scenario")
    scenario_dir = scenario_payload.parent if scenario_payload is not None else None

    return HydratedMember(
        root=pack_root,
        spec_path=spec_path,
        source_path=source_path,
        scenario_dir=scenario_dir,
    )


def resolve_members(
    manifest: dict,
    *,
    repo: Path = REPO,
    bundle_registry_path: Optional[Path] = None,
) -> dict[str, HydratedMember]:
    """Resolve the manifest's complete curated corpus through published packs."""
    members = manifest.get("examples")
    packs = manifest.get("packs")
    _require(isinstance(members, list), "curated manifest examples must be an array")
    _require(isinstance(packs, dict), "curated manifest packs must be an object")
    _require(
        set(packs) == set(members),
        "curated manifest packs must be an exact bijection with examples",
    )
    return {
        member: resolve_member(
            member,
            packs[member],
            repo=repo,
            bundle_registry_path=bundle_registry_path,
        )
        for member in members
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve and verify every member of the pack-only M6 corpus"
    )
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO / "docs" / "m6-curated-example-corpus.json",
    )
    args = parser.parse_args()
    try:
        manifest = _load_json(args.manifest, "curated manifest")
        members = resolve_members(manifest, repo=args.repo.resolve())
    except (OSError, json.JSONDecodeError, PackResolutionError) as exc:
        print(f"pack resolution FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"pack resolution OK: {len(members)} receipted members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
