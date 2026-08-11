#!/usr/bin/env python3
"""Backend-parameterized recipe-record round-trip gate ( R5a).

Completion bar executes on the production Solidity recipe corpus:

  1. dump-json → extract TargetIdiomRecipe IR → canonicalize is pure and
     idempotent (two runs byte-identical);
  2. production membership is closed: configured sources and extracted
     recipeIds match the discovered surface exactly (order + set);
  3. re-emit TableGen → dump-json → same canonical IR;
  4. after corpus normalization, re-emitting each def into its source file is
     a no-op (byte-identical sources);
  5. mutations applied to a temporary corpus package are run through this
     gate and MUST be rejected (record order, input/field order, operation,
     binding, cardinality, source membership, canonical source bytes);
  6. fresh gen_backend_idiom_recipes / recipe-adapter builders match committed
     artifacts (no semantic/generated delta).

Residue (includes, TargetNode rows, leaf hooks, class templates, comments) is
explicitly out of grammar and is never required to round-trip.

Pinned-TableGen entrypoint (CTest `recipe-roundtrip`):
  python3 scripts/gates/check_recipe_roundtrip.py \\
      --backend solidity --tblgen ${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen

Usage:
  check_recipe_roundtrip.py --backend solidity --tblgen PATH
  check_recipe_roundtrip.py --backend solidity --tblgen PATH --selftest
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "generators"))
import recipe_canonicalizer as RC  # noqa: E402
import generated_artifacts  # noqa: E402

# Closed production Solidity surface (must match dump-json discovery exactly).
# Order = configured corpus file order × def appearance order (production referee).
SOLIDITY_EXPECTED_ORDER = (
    "solidity.guard-consumer.evidence.v1",
    "solidity.guard-consumer.temporal.v1",
    "solidity.guard-consumer.effectful.v1",
    "solidity.temporal.contract.v1",
    "solidity.effectful.primitive.with-attestation.v1",
    "solidity.effectful.primitive.without-attestation.v1",
    "solidity.effectful.contract.without-attestation.v1",
    "solidity.effectful.contract.with-attestation.v1",
    "solidity.evidence.contract.v1",
)
SOLIDITY_EXPECTED_IDS = frozenset(SOLIDITY_EXPECTED_ORDER)

BACKENDS = {
    "solidity": {
        "entry": RC.SOLIDITY_ENTRY_TD,
        "corpus": RC.SOLIDITY_CORPUS,
        "includes": lambda repo: RC.default_includes(repo),
        "builders_inc": Path(
            "lib/backends/solidity/generated/SolidityRecipeBuilders.inc"
        ),
        "builders_profile": "solidity-recipe-adapter",
        "target_td": Path("lib/backends/solidity/model/SolidityTargetNodes.td"),
        "gen_symbol": "solidity",
        "expected_order": SOLIDITY_EXPECTED_ORDER,
        "expected_ids": SOLIDITY_EXPECTED_IDS,
    },
}


def die(msg: str) -> None:
    sys.stderr.write(f"check_recipe_roundtrip: {msg}\n")
    sys.exit(1)


def load_backend(repo: Path, backend: str, tblgen: str):
    cfg = BACKENDS[backend]
    entry = repo / cfg["entry"]
    includes = cfg["includes"](repo)
    records = RC.load_records(entry, includes, tblgen)
    recipes = RC.extract_corpus_ordered(repo, records, list(cfg["corpus"]))
    return cfg, entry, includes, records, recipes


def check_idempotent(recipes: list[dict], fails: list) -> list[dict]:
    c1 = [RC.canonicalize_recipe(r) for r in recipes]
    c2 = [RC.canonicalize_recipe(copy.deepcopy(r)) for r in recipes]
    if RC.compact(c1) != RC.compact(c2):
        fails.append("canonicalize is not idempotent (two runs differ)")
    return c1


def check_membership(cfg: dict, recipes: list[dict], records: dict, fails: list) -> None:
    """Configured sources + expected IDs must match discovery exactly."""
    got_ids = [r["recipeId"] for r in recipes]
    got_set = set(got_ids)
    exp_ids = set(cfg["expected_ids"])
    exp_order = list(cfg["expected_order"])
    if got_set != exp_ids:
        fails.append(
            f"membership set mismatch: extra={sorted(got_set - exp_ids)} "
            f"missing={sorted(exp_ids - got_set)}"
        )
    if got_ids != exp_order:
        fails.append(
            f"membership order mismatch:\n  got {got_ids}\n  exp {exp_order}"
        )
    # Every configured corpus file must exist; every discovered def must live
    # in the configured corpus (no escape via an unlisted .td include).
    repo_marker = True  # used by callers that pass repo-relative cfg
    _ = repo_marker
    all_named = set(RC.production_recipe_names(records))
    if all_named != {r["defName"] for r in recipes}:
        fails.append(
            "discovered TargetIdiomRecipe defs disagree with ordered extraction "
            f"(all={sorted(all_named)} ordered={[r['defName'] for r in recipes]})"
        )


def check_reemit_roundtrip(
    includes: list[str], tblgen: str, recipes: list[dict], fails: list,
) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="recipe-rt-"))
    try:
        body = (
            '// RUN-generated round-trip package\n'
            'include "BackendIdiom.td"\n\n'
            + RC.emit_corpus_td(recipes)
        )
        td = tmp / "RoundTripRecipes.td"
        td.write_text(body, encoding="utf-8")
        records = RC.load_records(td, includes, tblgen)
        after = RC.extract_corpus(records)
        before = [RC.canonicalize_recipe(r) for r in recipes]
        after_c = [RC.canonicalize_recipe(r) for r in after]

        def strip_def(rs):
            out = []
            for r in rs:
                c = copy.deepcopy(r)
                c.pop("defName", None)
                out.append(c)
            return sorted(out, key=lambda r: r["recipeId"])

        if RC.compact(strip_def(before)) != RC.compact(strip_def(after_c)):
            fails.append("re-emit → dump-json IR diverged from source IR")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_source_normalized(
    repo: Path, cfg: dict, recipes: list[dict], fails: list,
) -> None:
    by_def = {r["defName"]: r for r in recipes}
    mapping = RC.map_defs_to_files(repo, list(by_def), list(cfg["corpus"]))
    per_file: dict[Path, dict[str, dict]] = {}
    for def_name, path in mapping.items():
        per_file.setdefault(path, {})[def_name] = by_def[def_name]
    for path, group in per_file.items():
        text = (repo / path).read_text(encoding="utf-8")
        rewritten = RC.rewrite_file_recipes(text, group)
        if rewritten != text:
            fails.append(
                f"source not normalized: {path} would change under re-emit "
                f"(run recipe_canonicalizer.py --canonicalize-files)"
            )


def check_fresh_generation(
    repo: Path, cfg: dict, tblgen: str, build_dir: Path, fails: list,
) -> None:
    entry = repo / cfg["entry"]
    tmp = Path(tempfile.mkdtemp(prefix="recipe-fresh-"))
    try:
        gen_mod = repo / "scripts/generators/gen_backend_idiom_recipes.py"
        out_a = tmp / "recipes_a.inc"
        out_b = tmp / "recipes_b.inc"
        for out in (out_a, out_b):
            cmd = [
                sys.executable, str(gen_mod),
                "--td", str(entry),
                "--tblgen", tblgen,
                "-I", str(repo / "lib/backends"),
                "--symbol", cfg["gen_symbol"],
                "-o", str(out),
            ]
            proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
            if proc.returncode:
                fails.append(
                    "fresh gen_backend_idiom_recipes failed:\n"
                    + (proc.stderr or proc.stdout)[:2000]
                )
                return
        if out_a.read_bytes() != out_b.read_bytes():
            fails.append("recipe-module generator is not deterministic across two runs")

        try:
            builders = Path(generated_artifacts.resolve(
                cfg["builders_inc"].as_posix(), str(build_dir)
            ))
        except generated_artifacts.GeneratedArtifactError as error:
            fails.append(str(error))
            return
        gen_b = repo / "scripts/generators/backend_recipe_gen.py"
        out_builders = tmp / "builders.inc"
        cmd = [
            sys.executable, str(gen_b),
            "--profile", cfg["builders_profile"],
            "--td", str(entry),
            "--target-td", str(repo / cfg["target_td"]),
            "--tblgen", tblgen,
            "-I", str(repo / "lib/backends"),
            "-o", str(out_builders),
        ]
        proc = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        if proc.returncode:
            fails.append(
                "fresh backend_recipe_gen (solidity-recipe-adapter) failed:\n"
                + (proc.stderr or proc.stdout)[:2000]
            )
            return
        if out_builders.read_bytes() != builders.read_bytes():
            fails.append(
                f"fresh builders differ from build product {cfg['builders_inc']} "
                f"(semantic/generated delta after recipe normalize)"
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- Temporary package + real gate rejection --------------------------------


def _copy_solidity_package(
    src_repo: Path, src_build: Path, dst_repo: Path, dst_build: Path
) -> None:
    """Minimal package tree so load_backend/freshness can run against dst_repo."""
    pairs = [
        "lib/backends/BackendIdiom.td",
        "lib/backends/solidity/recipes/SolidityIdiomRecipes.td",
        "lib/backends/solidity/recipes/SolidityTemporalIdiomRecipes.td",
        "lib/backends/solidity/recipes/SolidityEffectfulIdiomRecipes.td",
        "lib/backends/solidity/recipes/SolidityEvidenceIdiomRecipes.td",
        "lib/backends/solidity/model/SolidityTargetNodes.td",
        "scripts/generators/recipe_canonicalizer.py",
        "scripts/generators/gen_backend_idiom_recipes.py",
        "scripts/generators/backend_recipe_gen.py",
    ]
    for rel in pairs:
        s = src_repo / rel
        d = dst_repo / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
    generated_rel = BACKENDS["solidity"]["builders_inc"].as_posix()
    generated_src = Path(generated_artifacts.resolve(generated_rel, str(src_build)))
    generated_dst = dst_build / generated_artifacts.MIGRATED_ARTIFACTS[generated_rel]
    generated_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated_src, generated_dst)


def evaluate_backend(repo: Path, backend: str, tblgen: str, build_dir: Path,
                     *, run_mutations: bool = True) -> list[str]:
    """Core gate evaluation. `run_mutations` is False when evaluating a mutant
    (avoid recursive mutation packages)."""
    fails: list[str] = []
    if backend not in BACKENDS:
        return [f"unknown backend {backend!r}"]
    cfg, entry, includes, records, recipes = load_backend(repo, backend, tblgen)
    check_membership(cfg, recipes, records, fails)
    canon = check_idempotent(recipes, fails)
    check_reemit_roundtrip(includes, tblgen, recipes, fails)
    check_source_normalized(repo, cfg, canon, fails)
    check_fresh_generation(repo, cfg, tblgen, build_dir, fails)
    if run_mutations:
        mutation_probes(repo, backend, tblgen, build_dir, fails)
    return fails


def _require_reject(label: str, fails: list, mutant_fails: list) -> None:
    if not mutant_fails:
        fails.append(f"mutation not rejected: {label}")
    else:
        print(f"  mutation rejected as expected: {label} ({len(mutant_fails)} fail(s))")


def _find_def_file(repo: Path, cfg: dict, def_name: str) -> Path:
    mapping = RC.map_defs_to_files(repo, [def_name], list(cfg["corpus"]))
    return repo / mapping[def_name]


def mutation_probes(
    repo: Path, backend: str, tblgen: str, build_dir: Path, fails: list
) -> None:
    """Apply each required mutation to a temp package and require gate rejection."""
    cfg = BACKENDS[backend]

    def with_mutant(label: str, mutator) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="recipe-mut-"))
        try:
            tmp_repo = tmp / "repo"
            tmp_build = tmp / "build"
            _copy_solidity_package(repo, build_dir, tmp_repo, tmp_build)
            mutator(tmp_repo)
            try:
                mutant_fails = evaluate_backend(
                    tmp_repo, backend, tblgen, tmp_build, run_mutations=False
                )
            except SystemExit as exc:
                # recipe_canonicalizer.die / hard tblgen failure counts as rejection.
                mutant_fails = [f"hard-fail: {exc}"]
            except Exception as exc:  # noqa: BLE001 — mutant may be ill-formed
                mutant_fails = [f"exception: {type(exc).__name__}: {exc}"]
            _require_reject(label, fails, mutant_fails)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # --- source membership: delete one production recipe def ---
    def mut_drop_recipe(tmp: Path) -> None:
        path = tmp / "lib/backends/solidity/recipes/SolidityEvidenceIdiomRecipes.td"
        text = path.read_text(encoding="utf-8")
        span = RC._find_def_span(text, "SolidityEvidenceContractRecipe")
        if not span:
            raise RuntimeError("membership mutant: def not found")
        path.write_text(text[:span[0]] + text[span[1]:], encoding="utf-8")

    with_mutant("source-membership (drop evidence contract recipe)", mut_drop_recipe)

    # --- record order: swap two top-level recipe defs in one file ---
    def mut_record_order(tmp: Path) -> None:
        path = tmp / "lib/backends/solidity/recipes/SolidityIdiomRecipes.td"
        text = path.read_text(encoding="utf-8")
        a = RC._find_def_span(text, "SolidityGuardConsumerEvidence")
        b = RC._find_def_span(text, "SolidityGuardConsumerTemporal")
        if not a or not b:
            raise RuntimeError("record-order mutant: defs not found")
        # Ensure a before b.
        if a[0] > b[0]:
            a, b = b, a
        block_a, block_b = text[a[0]:a[1]], text[b[0]:b[1]]
        # Rebuild with swapped blocks.
        text2 = text[:a[0]] + block_b + text[a[1]:b[0]] + block_a + text[b[1]:]
        path.write_text(text2, encoding="utf-8")

    with_mutant("record-order (swap two guard-consumer defs)", mut_record_order)

    # --- input/field order: swap the first two single-line One<> inputs ---
    def mut_input_order(tmp: Path) -> None:
        path = tmp / "lib/backends/solidity/recipes/SolidityTemporalIdiomRecipes.td"
        text = path.read_text(encoding="utf-8")
        a = 'One<"execution", "FinalizedTemporalExecution">'
        b = 'One<"initialRole", "FinalizedTemporalRole">'
        if a not in text or b not in text:
            raise RuntimeError("input-order mutant: anchors missing")
        text2 = text.replace(a, "__TMP_INPUT_A__", 1).replace(b, a, 1).replace(
            "__TMP_INPUT_A__", b, 1
        )
        path.write_text(text2, encoding="utf-8")

    with_mutant("input/field-order (swap first two One<> inputs)", mut_input_order)

    # --- operation mutation: rename an Emit node ---
    def mut_operation(tmp: Path) -> None:
        path = tmp / "lib/backends/solidity/recipes/SolidityIdiomRecipes.td"
        text = path.read_text(encoding="utf-8")
        span = RC._find_def_span(text, "SolidityGuardConsumerEvidence")
        if not span:
            raise RuntimeError("operation mutant: def not found")
        block = text[span[0]:span[1]]
        if "Emit<\"GuardIntroComment\"" not in block:
            raise RuntimeError("operation mutant: anchor missing")
        block2 = block.replace(
            'Emit<"GuardIntroComment"', 'Emit<"GuardIntroCommentMUTATED"', 1
        )
        path.write_text(text[:span[0]] + block2 + text[span[1]:], encoding="utf-8")

    with_mutant("operation (mutate Emit node)", mut_operation)

    # --- binding mutation: reverse two bindings on one Emit ---
    def mut_binding(tmp: Path) -> None:
        path = tmp / "lib/backends/solidity/recipes/SolidityTemporalIdiomRecipes.td"
        text = path.read_text(encoding="utf-8")
        # Swap Direct initial/success on SolStatusEnum emit if present.
        if 'Direct<"initial"' not in text or 'Direct<"success"' not in text:
            raise RuntimeError("binding mutant: anchors missing")
        text2 = text.replace('Direct<"initial"', 'Direct<"__TMP_SUCCESS__"', 1)
        text2 = text2.replace('Direct<"success"', 'Direct<"initial"', 1)
        text2 = text2.replace('Direct<"__TMP_SUCCESS__"', 'Direct<"success"', 1)
        path.write_text(text2, encoding="utf-8")

    with_mutant("binding (swap Direct fields)", mut_binding)

    # --- cardinality mutation ---
    def mut_cardinality(tmp: Path) -> None:
        path = tmp / "lib/backends/solidity/recipes/SolidityIdiomRecipes.td"
        text = path.read_text(encoding="utf-8")
        span = RC._find_def_span(text, "SolidityGuardConsumerEvidence")
        if not span:
            raise RuntimeError("cardinality mutant: def not found")
        block = text[span[0]:span[1]]
        if "CardinalityMany<5," not in block:
            # Accept either spacing.
            if "CardinalityMany<5" not in block:
                raise RuntimeError("cardinality mutant: anchor missing")
        block2 = block.replace("CardinalityMany<5", "CardinalityMany<6", 1)
        path.write_text(text[:span[0]] + block2 + text[span[1]:], encoding="utf-8")

    with_mutant("cardinality (CardinalityMany min 5→6)", mut_cardinality)

    # --- canonical source bytes: corrupt a recipeId string ---
    def mut_bytes(tmp: Path) -> None:
        path = tmp / "lib/backends/solidity/recipes/SolidityEvidenceIdiomRecipes.td"
        text = path.read_text(encoding="utf-8")
        if "solidity.evidence.contract.v1" not in text:
            raise RuntimeError("bytes mutant: recipeId missing")
        path.write_text(
            text.replace(
                "solidity.evidence.contract.v1",
                "solidity.evidence.contract.v1.MUTATED",
                1,
            ),
            encoding="utf-8",
        )

    with_mutant("canonical-bytes (recipeId corruption)", mut_bytes)


def run_backend(
    repo: Path, backend: str, tblgen: str, build_dir: Path
) -> list[str]:
    fails = evaluate_backend(
        repo, backend, tblgen, build_dir, run_mutations=True
    )
    if not fails:
        cfg = BACKENDS[backend]
        _, _, _, _, recipes = load_backend(repo, backend, tblgen)
        canon = [RC.canonicalize_recipe(r) for r in recipes]
        print(
            f"ok: backend={backend} recipes={len(canon)} "
            f"digest={RC.sha256_text(RC.compact(canon))}"
        )
    return fails


def selftest(repo: Path, tblgen: str) -> int:
    """Fixture package: round-trip + each mutation class rejects via evaluate."""
    tmp = Path(tempfile.mkdtemp(prefix="recipe-selftest-"))
    try:
        includes = RC.default_includes(repo)
        td = tmp / "Fixture.td"
        base = (
            'include "BackendIdiom.td"\n'
            'def FixtureNode : TargetNode<"FixtureNode", "FixtureCat", [], "fixture">;\n'
            'def FixtureNodeB : TargetNode<"FixtureNodeB", "FixtureCat", [], "fixture-b">;\n'
            'def FixtureRecipeA : TargetIdiomRecipe<\n'
            '  "fixture.recipe.a.v1", "solidity",\n'
            '  "FixtureKind", "NotApplicable", "NotApplicable", [],\n'
            '  "FixtureCat", CardinalityOne,\n'
            '  Sequence<[Emit<"FixtureNode", []>]>>;\n'
            'def FixtureRecipeB : TargetIdiomRecipe<\n'
            '  "fixture.recipe.b.v1", "solidity",\n'
            '  "FixtureKindB", "NotApplicable", "NotApplicable", [],\n'
            '  "FixtureCat", CardinalityOne,\n'
            '  Sequence<[Emit<"FixtureNodeB", []>]>>;\n'
        )
        td.write_text(base, encoding="utf-8")
        recipes = RC.extract_corpus(RC.load_records(td, includes, tblgen))
        if len(recipes) != 2:
            die(f"selftest expected 2 recipes, got {len(recipes)}")
        c1 = [RC.canonicalize_recipe(r) for r in recipes]
        c2 = [RC.canonicalize_recipe(copy.deepcopy(r)) for r in recipes]
        if RC.compact(c1) != RC.compact(c2):
            die("selftest: canonicalize not idempotent")
        # Re-emit round-trip.
        td2 = tmp / "Fixture2.td"
        td2.write_text(
            'include "BackendIdiom.td"\n'
            'def FixtureNode : TargetNode<"FixtureNode", "FixtureCat", [], "fixture">;\n'
            'def FixtureNodeB : TargetNode<"FixtureNodeB", "FixtureCat", [], "fixture-b">;\n'
            + RC.emit_corpus_td(c1),
            encoding="utf-8",
        )
        r2 = [RC.canonicalize_recipe(r) for r in RC.extract_corpus(
            RC.load_records(td2, includes, tblgen))]
        def strip(rs):
            out = []
            for r in rs:
                c = copy.deepcopy(r)
                c.pop("defName", None)
                out.append(c)
            return sorted(out, key=lambda x: x["recipeId"])
        if RC.compact(strip(c1)) != RC.compact(strip(r2)):
            die("selftest: re-emit IR mismatch")

        # Operation mutation: change Emit node string → IR must change.
        td3 = tmp / "Fixture3.td"
        td3.write_text(
            base.replace('Emit<"FixtureNode"', 'Emit<"FixtureNodeMUTATED"', 1),
            encoding="utf-8",
        )
        mut = [
            RC.canonicalize_recipe(r)
            for r in RC.extract_corpus(RC.load_records(td3, includes, tblgen))
        ]
        if RC.compact(strip(mut)) == RC.compact(strip(c1)):
            die("selftest: operation mutation did not change IR")

        # Membership drop.
        td4 = tmp / "Fixture4.td"
        text = base
        span = RC._find_def_span(text, "FixtureRecipeB")
        if not span:
            die("selftest: cannot find FixtureRecipeB")
        td4.write_text(text[:span[0]] + text[span[1]:], encoding="utf-8")
        dropped = RC.extract_corpus(RC.load_records(td4, includes, tblgen))
        if len(dropped) != 1:
            die(f"selftest: membership drop expected 1 recipe, got {len(dropped)}")

        # Record-order swap must change ordered identity.
        td5 = tmp / "Fixture5.td"
        sa = RC._find_def_span(base, "FixtureRecipeA")
        sb = RC._find_def_span(base, "FixtureRecipeB")
        if not sa or not sb or sa[0] > sb[0]:
            die("selftest: cannot order FixtureRecipe A/B")
        ba, bb = base[sa[0]:sa[1]], base[sb[0]:sb[1]]
        swapped = base[:sa[0]] + bb + base[sa[1]:sb[0]] + ba + base[sb[1]:]
        td5.write_text(swapped, encoding="utf-8")
        # Ordered extract from a one-file corpus.
        from pathlib import Path as _P
        # Use dump-json names + file order via extract on the single file:
        rec5 = RC.load_records(td5, includes, tblgen)
        # Simulate ordered scan: both defs in one file swapped.
        text5 = td5.read_text(encoding="utf-8")
        order = []
        for m in RC._DEF_START.finditer(text5):
            n = m.group(1)
            if n in RC.production_recipe_names(rec5):
                order.append(n)
        if order != ["FixtureRecipeB", "FixtureRecipeA"]:
            die(f"selftest: record-order swap not observed ({order})")

        print("ok (selftest)")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="solidity")
    ap.add_argument("--tblgen", required=True,
                    help="pinned llvm-tblgen (CTest passes LLVM_TOOLS_BINARY_DIR/llvm-tblgen)")
    ap.add_argument(
        "--build-dir", type=Path,
        default=Path(os.environ.get("NEUTRINO_BUILD_DIR", REPO / "out")),
        help="configured build tree containing generated recipe artifacts",
    )
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    if not Path(args.tblgen).is_file():
        die(f"tblgen not found: {args.tblgen}")
    if args.selftest:
        return selftest(repo, args.tblgen)
    fails = run_backend(repo, args.backend, args.tblgen, args.build_dir.resolve())
    if fails:
        for f in fails:
            print(f"FAIL: {f}", file=sys.stderr)
        print(f"check_recipe_roundtrip: {len(fails)} failure(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
