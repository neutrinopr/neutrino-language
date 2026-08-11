"""Resolve the inputs owned by the lit checks.

Production-domain inputs are consumed only through the receipt-verifying M6
pack resolver.  No hydrated-cache path is assembled by a consumer.

Core-owned coverage is served instead by the in-core synthetic fixtures the
externalization trains (-) left under ``test/ir/<area>/Inputs/core_*``
when the production domain they replaced moved out to a pack.  Those are core
artifacts, not production domains, so they carry no receipt -- but they are
still resolved through :func:`resolve_core_fixture` so a missing surface is
reported by name instead of surfacing as an empty glob or a downstream
usage-2 cascade ().

A checker in another ``test/ir`` area consumes this same boundary with::

    sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
    from pipeline_inputs import PipelineInputError, resolve_core_fixture

so that every lit check reaches its inputs through one place rather than each
area inventing its own path assembly.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Optional


class PipelineInputError(RuntimeError):
    """A required pipeline-test input surface is absent or unverified."""


# The in-core synthetic fixtures that carry core-owned coverage after their
# production counterparts were externalized.  This registry is the single place
# a checker learns where a `core_*` fixture lives; `check_pipeline_inputs.py`
# proves it is a bijection with what is actually committed, so a fixture added
# or moved without updating this map fails closed rather than silently
# shrinking a corpus.
CORE_FIXTURES = {
    "core_document_escrow": "test/ir/samples/Inputs/core_document_escrow",
    "core_dual_offer": "test/ir/samples/Inputs/core_dual_offer",
    "core_evidence_only_milestone": "test/ir/evidence/Inputs/core_evidence_only_milestone",
    "core_flexible_binding": "test/ir/domain/Inputs/core_flexible_binding",
    "core_hybrid_compute_sample": "test/ir/samples/Inputs/core_hybrid_compute_sample",
    "core_installment_fulfillment": "test/ir/samples/Inputs/core_installment_fulfillment",
    "core_multi_pair_role": "test/ir/security/Inputs/core_multi_pair_role",
    "core_promo_campaign": "test/ir/samples/Inputs/core_promo_campaign",
    "core_regulated_evidence_sample": "test/ir/samples/Inputs/core_regulated_evidence_sample",
    "core_reserve_authority": "test/ir/security/Inputs/core_reserve_authority",
    "core_role_constrained": "test/ir/security/Inputs/core_role_constrained",
    "core_sample_installment": "test/ir/pipeline/Inputs/core_sample_installment",
    "core_scheme_settlement": "test/ir/pipeline/Inputs/core_scheme_settlement",
    "core_secured_offer": "test/ir/security/Inputs/core_secured_offer",
}


REGISTRY_MEMBERS = {
    # Additional single-source/single-scenario packs retain the original
    # >=10 capability-spec and test-realization corpus assertions; the curated
    # seven alone contain only five realizations.
    "account_freeze_transfer",
    "clinical_evidence_verification",
    "compliant_transfer",
    "conditional_escrow",
    "merchant_sponsored_installment",
}


@dataclass(frozen=True)
class Fixture:
    name: str
    root: Path
    source: Path
    scenario: Optional[Path]
    capability_spec: Optional[Path]
    test_realization: Optional[Path]


def _require_path(owner: str, surface: str, path: Path, *, directory: bool = False) -> Path:
    present = path.is_dir() if directory else path.is_file()
    if not present:
        kind = "directory" if directory else "file"
        raise PipelineInputError(
            f"required pipeline input missing: {owner}.{surface} "
            f"({kind} {path})"
        )
    return path


def _only_payload(root: Path, subdir: str, suffix: str, owner: str) -> Path:
    directory = _require_path(owner, subdir, root / subdir, directory=True)
    matches = sorted(directory.glob(f"*{suffix}"))
    if len(matches) != 1:
        raise PipelineInputError(
            f"required pipeline input misregistered: {owner}.{subdir} "
            f"(expected exactly one *{suffix}, found {len(matches)} in {directory})"
        )
    return matches[0]


def _fixture(owner: str, root: Path, *, scenario_required: bool) -> Fixture:
    source = _only_payload(root, "source", ".neu", owner)
    scenario = None
    if scenario_required:
        scenario = _only_payload(root, "scenario", ".json", owner)
    elif (root / "scenario").is_dir():
        matches = sorted((root / "scenario").glob("*.json"))
        if len(matches) == 1:
            scenario = matches[0]
    spec = root / "generated" / "capability-spec" / "capability-spec.json"
    realization = root / "generated" / "test-realization" / "test-realization.json"
    return Fixture(
        name=owner,
        root=root,
        source=source,
        scenario=scenario,
        capability_spec=spec if spec.is_file() else None,
        test_realization=realization if realization.is_file() else None,
    )


def require_surface(fixture: Fixture, *parts: str, directory: bool = False) -> Path:
    """Return ``fixture.root/<parts>``, diagnosing an absent surface by name.

    Checkers use this instead of ``os.path.join`` so a fixture that lost an
    artifact reports *which* owner and *which* surface is missing, rather than
    letting the absence reappear as an empty read, a usage-2 exit or a
    ``TypeError`` several steps downstream ().
    """
    return _require_path(fixture.name, "/".join(parts),
                         fixture.root.joinpath(*parts), directory=directory)


def discover_core_fixture_roots(repo: Path) -> dict[str, Path]:
    """Return every committed ``test/ir/*/Inputs/core_*`` fixture that has a source."""
    found: dict[str, Path] = {}
    area_root = Path(repo) / "test" / "ir"
    for inputs in sorted(area_root.glob("*/Inputs")):
        for candidate in sorted(inputs.glob("core_*")):
            if candidate.is_dir() and sorted((candidate / "source").glob("*.neu")):
                found[candidate.name] = candidate
    return found


def resolve_core_fixture(repo: Path, owner: str, *,
                         source: Optional[str] = None,
                         scenario: Optional[str] = None) -> Fixture:
    """Resolve one core-owned synthetic fixture by registry name.

    ``source``/``scenario`` name a specific payload for the fixtures that ship
    more than one; otherwise the fixture must hold exactly one of each.
    """
    if owner not in CORE_FIXTURES:
        raise PipelineInputError(
            f"required core fixture is not registered: {owner} "
            f"(known: {', '.join(sorted(CORE_FIXTURES))})"
        )
    root = _require_path(owner, "root", Path(repo) / CORE_FIXTURES[owner],
                         directory=True)
    if source is None:
        src = _only_payload(root, "source", ".neu", owner)
    else:
        src = _require_path(owner, f"source/{source}", root / "source" / source)
    scn: Optional[Path]
    if scenario is not None:
        scn = _require_path(owner, f"scenario/{scenario}",
                            root / "scenario" / scenario)
    elif (root / "scenario").is_dir():
        matches = sorted((root / "scenario").glob("*.json"))
        scn = matches[0] if len(matches) == 1 else None
    else:
        scn = None
    spec = root / "generated" / "capability-spec" / "capability-spec.json"
    realization = root / "generated" / "test-realization" / "test-realization.json"
    return Fixture(
        name=owner,
        root=root,
        source=src,
        scenario=scn,
        capability_spec=spec if spec.is_file() else None,
        test_realization=realization if realization.is_file() else None,
    )


def resolve_core_fixtures(repo: Path) -> dict[str, Fixture]:
    """Resolve every registered core fixture, failing closed on registry drift."""
    committed = discover_core_fixture_roots(repo)
    registered = set(CORE_FIXTURES)
    if committed.keys() != registered:
        missing = sorted(registered - committed.keys())
        unregistered = sorted(committed.keys() - registered)
        raise PipelineInputError(
            "core fixture registry is not a bijection with the committed tree: "
            f"registered-but-absent={missing} committed-but-unregistered={unregistered}"
        )
    resolved: dict[str, Fixture] = {}
    for owner in sorted(registered):
        root = Path(repo) / CORE_FIXTURES[owner]
        sources = sorted((root / "source").glob("*.neu"))
        resolved[owner] = resolve_core_fixture(
            repo, owner, source=sources[0].name if len(sources) > 1 else None)
    return resolved


def view_golden_fixtures(repo: Path) -> list[Fixture]:
    """Return every fixture that pins committed participant-view goldens.

    The portfolio is the same receipt-verified corpus ``resolve_pipeline_inputs``
    establishes (what ``examples/domains/*`` used to be), plus the core-owned
    synthetic that still pins the guarded document-escrow views.  Discovery-based
    rather than a hardcoded list, so a fixture that gains views grows the corpus;
    the caller enforces the non-vacuity floor so it can never shrink silently.
    """
    fixtures = [
        fixture for fixture in resolve_pipeline_inputs(repo).values()
        if fixture.capability_spec is not None
        and sorted((fixture.root / "generated" / "views").glob("*.json"))
    ]
    #  synthetic still pins the document-escrow guarded-view goldens after
    # core removal; it is core-owned coverage, not a published domain.
    escrow = resolve_core_fixture(repo, "core_document_escrow")
    if escrow.capability_spec is not None and sorted(
            (escrow.root / "generated" / "views").glob("*.json")):
        fixtures.append(escrow)
    return sorted(fixtures, key=lambda fixture: fixture.name)


def resolve_pipeline_inputs(repo: Path) -> dict[str, Fixture]:
    """Return the named fixtures after verifying every external pack."""
    repo = Path(repo).resolve()
    sys.path.insert(0, str(repo / "scripts" / "gates"))
    try:
        from m6_pack_resolver import (PackResolutionError, resolve_member,
                                      resolve_members)
    except ImportError as error:
        raise PipelineInputError(
            f"required pipeline input resolver unavailable: {error}"
        ) from error

    manifest_path = repo / "docs" / "m6-curated-example-corpus.json"
    _require_path("curated_corpus", "manifest", manifest_path)
    try:
        with manifest_path.open(encoding="utf-8") as handle:
            members = resolve_members(json.load(handle), repo=repo)
    except (OSError, ValueError, PackResolutionError) as error:
        raise PipelineInputError(
            f"required pipeline input pack verification failed: {error}"
        ) from error

    resolved: dict[str, Fixture] = {}
    for owner in sorted(members):
        resolved[owner] = _fixture(
            owner, members[owner].root, scenario_required=False
        )
    for owner in ("sponsored_offer_agreement", "channel_verified_payout"):
        resolved[owner] = _fixture(
            owner, members[owner].root, scenario_required=True
        )

    registry_path = repo / "docs" / "externalized-domain-registry.json"
    _require_path("externalized_domains", "registry", registry_path)
    try:
        with registry_path.open(encoding="utf-8") as handle:
            registry = json.load(handle)
        prefix = repo / ".ci" / "domain-packs"
        for entry in registry["domains"]:
            owner = entry["id"]
            if owner in resolved or owner not in REGISTRY_MEMBERS:
                continue
            coords = {
                "packPath": str(prefix / entry["packPath"]),
                "receiptPath": str(prefix / entry["receiptPath"]),
                "packDigest": entry["packDigest"],
                "bundleDigest": entry["bundle"]["bundleDigest"],
            }
            member = resolve_member(owner, coords, repo=repo)
            resolved[owner] = _fixture(
                owner,
                member.root,
                scenario_required=(owner == "merchant_sponsored_installment"),
            )
    except (KeyError, OSError, ValueError, PackResolutionError) as error:
        raise PipelineInputError(
            "required pipeline input pack verification failed: "
            f"externalized registry: {error}"
        ) from error
    return resolved


def committed_capability_fixtures(repo: Path,
                                  external: dict[str, Fixture]) -> list[Fixture]:
    """Return the verified published specs owned by this pipeline check."""
    fixtures: list[Fixture] = []
    fixtures.extend(
        fixture for fixture in external.values()
        if fixture.capability_spec is not None
    )
    return fixtures


def committed_realization_fixtures(repo: Path,
                                   external: dict[str, Fixture]) -> list[Fixture]:
    """Return the verified published realizations owned by this pipeline check."""
    fixtures: list[Fixture] = []
    fixtures.extend(
        fixture for fixture in external.values()
        if fixture.capability_spec is not None
        and fixture.test_realization is not None
        and fixture.scenario is not None
    )
    return fixtures
