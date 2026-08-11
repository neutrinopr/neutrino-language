#!/usr/bin/env python3
"""Resolve the two cross-border acceptance inputs from verified domain packs.

The acceptance runner must not reach back into a translator-owned domain tree.
This helper binds the conventional external pack location to its published
verification receipt, then delegates all pack/bundle/payload validation to the
shared M6 pack resolver.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


PACK_SELECTION = (
    (
        "damage",
        "sha256:aa10a51eb298e99ed8a69cc37ec81e8ac8bd88249f6b15788b674749a1451876",
    ),
    (
        "export",
        "sha256:3c5ed17d5b8d935c8540134671b162a58e7ed81ce429dedf4a4639f822717b14",
    ),
)
RECEIPT_KIND = "neutrino.domain-pack-verification-receipt"


class CrossBorderPackError(RuntimeError):
    pass


def _load_json(path: Path, what: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CrossBorderPackError(f"cannot read {what} {path}: {error}") from error
    except ValueError as error:
        raise CrossBorderPackError(f"{what} {path} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise CrossBorderPackError(f"{what} {path} is not a JSON object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CrossBorderPackError(message)


def _under(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((path.resolve(), root.resolve())) == str(root.resolve())
    except ValueError:
        return False


def _selected_rows(repo: Path) -> list[tuple[str, dict]]:
    registry = _load_json(
        repo / "docs" / "externalized-domain-registry.json",
        "externalized-domain registry",
    )
    rows = registry.get("domains")
    _require(isinstance(rows, list), "externalized-domain registry has no domains array")
    selected = []
    for leg, digest in PACK_SELECTION:
        matches = [
            row
            for row in rows
            if isinstance(row, dict) and row.get("packDigest") == digest
        ]
        _require(
            len(matches) == 1,
            f"{leg}: pack digest {digest!r} must select exactly one registry row",
        )
        selected.append((leg, matches[0]))
    return selected


def resolve(repo: Path, packs_root: Path) -> dict[str, dict[str, str]]:
    sys.path.insert(0, str(repo / "scripts" / "gates"))
    import m6_pack_resolver as resolver

    result: dict[str, dict[str, str]] = {}
    for leg, registry_row in _selected_rows(repo):
        member = registry_row.get("id")
        _require(isinstance(member, str), f"{leg}: registry identity is missing")
        pack_rel = registry_row.get("packPath")
        receipt_rel = registry_row.get("receiptPath")
        _require(
            isinstance(pack_rel, str) and isinstance(receipt_rel, str),
            f"{leg}: registry pack/receipt paths are missing",
        )
        pack_root = packs_root.joinpath(*pack_rel.split("/"))
        receipt_path = packs_root.joinpath(*receipt_rel.split("/"))
        receipt = _load_json(receipt_path, f"{member} receipt")
        _require(
            receipt.get("kind") == RECEIPT_KIND,
            f"{member}: receipt kind {receipt.get('kind')!r} != {RECEIPT_KIND!r}",
        )
        _require(
            receipt.get("outcome") == "VERIFIED",
            f"{member}: receipt outcome {receipt.get('outcome')!r} != 'VERIFIED'",
        )
        receipt_pack = receipt.get("pack")
        receipt_bundle = receipt.get("targetsBundle")
        _require(isinstance(receipt_pack, dict), f"{member}: receipt pack is missing")
        _require(
            isinstance(receipt_bundle, dict),
            f"{member}: receipt targetsBundle is missing",
        )
        _require(
            receipt_pack.get("packPath") == pack_rel,
            f"{member}: receipt packPath {receipt_pack.get('packPath')!r} "
            f"!= registry {pack_rel!r}",
        )

        coords = {
            "packPath": str(pack_root),
            "receiptPath": str(receipt_path),
            "packDigest": registry_row.get("packDigest"),
            "bundleDigest": registry_row.get("bundle", {}).get("bundleDigest"),
        }
        try:
            hydrated = resolver.resolve_member(member, coords, repo=repo)
        except resolver.PackResolutionError as error:
            raise CrossBorderPackError(str(error)) from error

        manifest = _load_json(pack_root / "pack.json", f"{member} pack")
        scenarios = [
            row.get("path")
            for row in manifest.get("payloads", [])
            if isinstance(row, dict) and row.get("role") == "scenario"
        ]
        _require(
            len(scenarios) == 1 and isinstance(scenarios[0], str),
            f"{member}: pack must declare exactly one scenario payload",
        )
        source = hydrated.source_path
        scenario = pack_root.joinpath(*scenarios[0].split("/"))
        _require(source is not None and source.is_file(), f"{member}: source payload is missing")
        _require(scenario.is_file(), f"{member}: scenario payload is missing")
        _require(
            _under(source, pack_root) and _under(scenario, pack_root),
            f"{member}: source/scenario escaped the verified pack root",
        )
        result[leg] = {
            "member": member,
            "source": str(source.resolve()),
            "scenario": str(scenario.resolve()),
        }
    return result


def selftest(repo: Path, packs_root: Path) -> None:
    resolved = resolve(repo, packs_root)
    _require(
        set(resolved) == {leg for leg, _ in PACK_SELECTION},
        "positive resolution omitted a selected leg",
    )

    with tempfile.TemporaryDirectory(prefix="cross-border-packs.") as temp:
        copied = Path(temp) / "domain-packs"
        selected = _selected_rows(repo)
        for _, row in selected:
            pack_rel = Path(row["packPath"])
            member_root = pack_rel.parent
            source = packs_root / member_root
            target = copied / member_root
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)

        pack_root = copied / selected[0][1]["packPath"]
        hidden_pack = pack_root.with_name("pack.missing")
        pack_root.rename(hidden_pack)
        try:
            resolve(repo, copied)
        except CrossBorderPackError as error:
            _require(
                "pack" in str(error).lower(),
                f"missing pack failed oddly: {error}",
            )
        else:
            raise CrossBorderPackError("selftest: missing pack was accepted")
        hidden_pack.rename(pack_root)

        missing = copied / selected[0][1]["receiptPath"]
        missing.unlink()
        try:
            resolve(repo, copied)
        except CrossBorderPackError as error:
            _require("cannot read" in str(error), f"missing receipt failed oddly: {error}")
        else:
            raise CrossBorderPackError("selftest: missing receipt was accepted")

        shutil.copy2(
            packs_root / selected[0][1]["receiptPath"],
            missing,
        )
        failed_path = copied / selected[1][1]["receiptPath"]
        failed = _load_json(failed_path, "selftest receipt")
        failed["outcome"] = "FAILED"
        failed_path.write_text(json.dumps(failed), encoding="utf-8")
        try:
            resolve(repo, copied)
        except CrossBorderPackError as error:
            _require("VERIFIED" in str(error), f"failed receipt failed oddly: {error}")
        else:
            raise CrossBorderPackError("selftest: failed receipt was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--packs-root", type=Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    packs_root = (
        args.packs_root.resolve()
        if args.packs_root
        else repo / ".ci" / "domain-packs"
    )
    try:
        if args.selftest:
            selftest(repo, packs_root)
            print("cross-border pack resolver selftest PASS")
        else:
            print(json.dumps(resolve(repo, packs_root), sort_keys=True))
    except CrossBorderPackError as error:
        print(f"cross-border pack resolution FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
