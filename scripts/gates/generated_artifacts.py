#!/usr/bin/env python3
"""Build-dir-aware resolution for generated ``.inc`` artifacts (,  (a)).

Since  the generated backend ``.inc`` are build products, not committed
sources. Gates that used to open them at a repo-relative path must resolve them
from the configured build directory instead. The build tree mirrors the source
layout, so resolution is the same relative path under ``--build-dir``.

Resolution is **fail-closed**. A gate that cannot find a generated artifact must
refuse, never fall back to a source-tree copy and never treat absence as "nothing
to check" -- absence is precisely the regression this module exists to catch. The
distinct identities below let a caller report *why* it refused rather than
collapsing every case into one error.
"""

import os


class GeneratedArtifactError(RuntimeError):
    def __init__(self, identity, detail):
        super().__init__(f"{identity}: {detail}")
        self.identity = identity


# Repo-relative paths that stopped being committed in . The value is the
# path under the build directory; the build tree mirrors the source layout, so
# the two are identical today and the mapping stays explicit rather than implied
# so a future relocation is a data change instead of a code change.
MIGRATED_ARTIFACTS = {
    path: path
    for path in (
        "lib/backends/solidity/generated/SolidityTargetNodes.inc",
        "lib/backends/solidity/generated/SolidityPrinterHandlers.inc",
        "lib/backends/solidity/generated/SolidityTargetEnums.inc",
        "lib/backends/solidity/generated/SolidityEmitBuilderDecls.inc",
        "lib/backends/solidity/generated/SolidityEmitBuilders.inc",
        "lib/backends/solidity/generated/SolidityProjection.inc",
        "lib/backends/solidity/generated/SolidityRecipeBuilders.inc",
        # PostgreSQL ( batch 2). Same migration, same rule: the build tree
        # mirrors the source layout, so the mapping is identity today and stays
        # explicit so a relocation is a data change rather than a code change.
        "lib/backends/postgres/generated/PostgresTargetNodes.inc",
        "lib/backends/postgres/generated/PostgresTargetEnums.inc",
        "lib/backends/postgres/generated/PostgresPrinterHandlers.inc",
        "lib/backends/postgres/generated/PostgresProjection.inc",
        "lib/backends/postgres/generated/PostgresRecipeAdapter.inc",
        "lib/backends/postgres/generated/PostgresRecipeBuilders.inc",
        "lib/backends/postgres/generated/PostgresRecipeBuilders.decl.inc",
        "lib/backends/postgres/generated/PgDdlBuilders.inc",
        # Family-D: the shared finalized-projection codec ownership map. Not a
        # backend artifact -- it is produced by
        # scripts/generators/gen_finalized_projection_schema.py and multi-included
        # by BackendProjectionCodec.cpp -- but it is a committed generated file
        # under the same rule, so it migrates with the rest rather than being
        # left as the one exception that keeps the old pattern alive.
    )
}
# Family D uses the spec-contract target's dedicated generated subdirectory;
# keep that non-identity relocation explicit so gates cannot accidentally look
# for (or fall back to) the deleted source-tree spelling.
MIGRATED_ARTIFACTS["lib/spec-contract/BackendProjectionCodecFields.inc"] = (
    "lib/spec-contract/generated/BackendProjectionCodecFields.inc"
)


def is_migrated(repo_relative):
    return repo_relative in MIGRATED_ARTIFACTS


def resolve(repo_relative, build_dir):
    """Absolute path to a generated artifact in the configured build tree.

    Raises ``GeneratedArtifactError`` when the artifact is unusable. Callers must
    not rescue that by reading the source tree: after  a source-tree copy is
    itself a defect (a rogue same-name artifact), not a fallback.
    """
    if not is_migrated(repo_relative):
        raise GeneratedArtifactError(
            "generated.not_migrated",
            f"{repo_relative} is not a  build product",
        )
    if not build_dir:
        raise GeneratedArtifactError(
            "generated.build_dir_required",
            f"{repo_relative} is generated; pass --build-dir to resolve it",
        )
    resolved = os.path.join(build_dir, MIGRATED_ARTIFACTS[repo_relative])
    if not os.path.isfile(resolved):
        raise GeneratedArtifactError(
            "generated.missing",
            f"{repo_relative} was not generated at {resolved}; configure and "
            "build before running this gate",
        )
    if os.path.getsize(resolved) == 0:
        raise GeneratedArtifactError(
            "generated.empty",
            f"{resolved} is empty; the generator did not complete",
        )
    return resolved


def read_text(repo_relative, build_dir):
    with open(resolve(repo_relative, build_dir), encoding="utf-8") as stream:
        return stream.read()


def assert_not_committed(repo_root):
    """No  build product may reappear as a committed source file.

    A rogue same-name artifact in the source tree would shadow the generated one
    on the include path and silently reintroduce the drift this migration
    removed, so its presence is a refusal in its own right.
    """
    rogue = sorted(
        path for path in MIGRATED_ARTIFACTS
        if os.path.isfile(os.path.join(repo_root, path))
    )
    if rogue:
        raise GeneratedArtifactError(
            "generated.rogue_source_copy",
            "generated artifacts must not be committed: " + ", ".join(rogue),
        )


def add_build_dir_argument(parser):
    """Register the standard ``--build-dir`` on a gate's parser.

    Uniform across gates so a caller learns one spelling, and so the default
    (``NEUTRINO_BUILD_DIR``) gives CI one place to configure every gate at once.
    """
    parser.add_argument(
        "--build-dir",
        default=os.environ.get("NEUTRINO_BUILD_DIR", ""),
        help="configured build directory holding the  generated artifacts "
             "(default: $NEUTRINO_BUILD_DIR). Required for any gate that reads "
             "a generated .inc; there is no source-tree fallback.",
    )
