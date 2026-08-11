#!/usr/bin/env bash
# Heavy provisioning-test dispatcher (). ONE place that holds the render+drive
# recipe for each acceptance/e2e test, plus the runtime skip-when-absent gate so a
# machine lacking solc/forge/docker skips (exit 77) instead of failing.
#
# Invoked by the labeled CTest tests in cmake/NeutrinoAcceptanceTests.cmake; the
# Makefile targets are thin `ctest -R …` wrappers over those. This is the single
# orchestration source — neither the Makefile nor cmake re-implements the recipe.
#
#   run.sh <kind> <gen> <artifact_dir> [pack-resolver]
#
# <gen> may be empty for kinds that render nothing (solidity-reference tests a
# hand-authored Foundry project, so it needs neither neutrino-gen nor a build).
# NEU_SOURCE / NEU_SCENARIO env vars override the committed default .neu/scenario
# for the source-driven kinds (solidity/db/equivalence/equivalence-scheme) — the
# Makefile passes EXAMPLE/SCENARIO (or EXAMPLE2/SCENARIO2) through them.
#
# Exit: 0 pass · 77 skipped (tool absent — CTest SKIP_RETURN_CODE) · other = fail.
set -euo pipefail

KIND="${1:?kind required}"
GEN="${2:-}"
ART="${3:?artifact dir required}"
PACK_RESOLVER="${4:-}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Acceptance defaults are translator-owned synthetic fixtures. Production-domain
# release inputs are hydrated only by the curated pack checkers below.
_dom() {
  case "$1" in
    core_sample_installment)
      echo "$SRC/test/ir/pipeline/Inputs/core_sample_installment/source/core_sample_installment.neu" ;;
    core_scheme_settlement)
      echo "$SRC/test/ir/pipeline/Inputs/core_scheme_settlement/source/core_scheme_settlement.neu" ;;
    *) echo "run.sh: unknown synthetic source fixture '$1'" >&2; return 1 ;;
  esac
}
_scn() {
  case "$1" in
    core_sample_installment)
      echo "$SRC/test/ir/pipeline/Inputs/core_sample_installment/scenario/core_sample_installment_happy_path.json" ;;
    core_scheme_settlement)
      echo "$SRC/test/ir/pipeline/Inputs/core_scheme_settlement/scenario/core_scheme_settlement_happy_path.json" ;;
    *) echo "run.sh: unknown synthetic scenario fixture '$1'" >&2; return 1 ;;
  esac
}
# Source-driven kinds honor NEU_SOURCE/NEU_SCENARIO, else the committed default domain.
need_gen() { [ -n "$GEN" ] || { echo "run.sh [$KIND]: neutrino-gen path required" >&2; exit 2; }; }

SOLC="${SOLC:-$(command -v solc 2>/dev/null || true)}"
FORGE="${FORGE:-$(command -v forge 2>/dev/null || echo "$SRC/.foundry/bin/forge")}"

have_solc()  { [ -n "$SOLC" ] && [ -x "$SOLC" ] || command -v solc  >/dev/null 2>&1; }
have_forge() { [ -x "$FORGE" ] || command -v forge >/dev/null 2>&1; }
# A usable Docker DAEMON, not just the CLI — a box with `docker` installed but no
# reachable daemon must SKIP (or hard-fail under REQUIRE), never enter the DB recipe.
have_docker(){ command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; }
# Absent tool -> skip (exit 77) for local `ctest -L …` selection. But when
# NEUTRINO_REQUIRE_TOOLS is set (the `make` acceptance targets / CI set it), a missing
# tool is a HARD FAILURE — so a CI acceptance job can never silently skip its evidence.
skip() {
  if [ -n "${NEUTRINO_REQUIRE_TOOLS:-}" ]; then
    echo "FAIL [$KIND]: $1 required but not available (NEUTRINO_REQUIRE_TOOLS set)" >&2
    exit 1
  fi
  echo "SKIP [$KIND]: $1 not available"
  exit 77
}

# The DECLARED Forge native-library prefix (). CTest supplies it through the
# requires-forge tests' ENVIRONMENT property (cmake/NeutrinoForgeToolchain.cmake); a direct
# invocation derives it from the same single authority. It travels in this NEUTRAL variable
# because macOS SIP strips DYLD_* from a protected process's environment, and is re-materialised
# as DYLD_LIBRARY_PATH only where a launcher DIRECTLY spawns forge (forge_test below,
# check_solidity_goldens.py's forge_env(), neutrino-equiv's forgeCmd()). Exported so every one of
# those child launch routes sees the same identity.
if [ -z "${FORGE_DYLD_LIBRARY_PATH:-}" ]; then
  FORGE_DYLD_LIBRARY_PATH="$(python3 "$SRC/scripts/gates/check_forge_toolchain.py" \
    --print-library-path 2>/dev/null || true)"
fi
export FORGE_DYLD_LIBRARY_PATH

# Toolchain PROVISIONING check, run before any render/compile/execute step. A forge whose native
# closure does not resolve aborts in dyld with `Abort trap: 6` and no conformance is measured; that
# must surface as an INFRASTRUCTURE failure with a clear diagnostic, never as a backend result and
# never as a skip. Exit 66 (the checker's infrastructure code) is deliberately NOT 77.
forge_preflight() {
  local out
  if ! out="$(FORGE="$FORGE" python3 "$SRC/scripts/gates/check_forge_toolchain.py" \
      --preflight --library-path "${FORGE_DYLD_LIBRARY_PATH:-}" 2>&1)"; then
    echo "INFRASTRUCTURE [$KIND]: the configured Forge toolchain is not usable; no conformance" \
      "was measured." >&2
    echo "$out" >&2
    exit 66
  fi
  echo "[$KIND] $out"
}

forge_test() { # <root>
  if [ -n "${FORGE_DYLD_LIBRARY_PATH:-}" ]; then
    env DYLD_LIBRARY_PATH="$FORGE_DYLD_LIBRARY_PATH" \
      "$FORGE" test --root "$1" --use "$SOLC"
  else
    "$FORGE" test --root "$1" --use "$SOLC"
  fi
}

case "$KIND" in
  solidity)
    have_forge || skip forge; forge_preflight; have_solc || skip solc; need_gen
    src="${NEU_SOURCE:-$(_dom core_sample_installment)}"
    scen="${NEU_SCENARIO:-$(_scn core_sample_installment)}"
    "$GEN" --target=solidity --scenario="$scen" "$src" -o "$ART/solidity"
    forge_test "$ART/solidity" ;;

  solidity-explicit-time)
    # : the ordinary production generator must emit a Foundry witness that
    # drives both sides of an explicit timestamp guard. Before the deadline the
    # guarded balanced legs are suppressed with zero ledger movement; equality
    # is the inclusive success boundary and posts the balanced transfer.
    have_forge || skip forge; forge_preflight; have_solc || skip solc; need_gen
    "$GEN" --target=solidity \
      --scenario="$SRC/test/ir/legality/time_dependent.scn.json" \
      "$SRC/test/ir/legality/time_dependent.neu" -o "$ART/solidity-explicit-time"
    cp "$SRC/test/backend-guard/explicit_time/ExplicitTimeGuard.t.sol" \
      "$ART/solidity-explicit-time/test/"
    forge_test "$ART/solidity-explicit-time" ;;

  solidity-reference)
    have_forge || skip forge; forge_preflight; have_solc || skip solc
    forge_test "$SRC/examples/oracle-reference/threshold-quorum"
    # : the on-chain coordination-envelope digest, pinned to the committed vector.
    forge_test "$SRC/examples/oracle-reference/coordination-envelope" ;;

  oracle-coordination)
    have_forge || skip forge; forge_preflight; have_solc || skip solc; need_gen
    "$GEN" --target=solidity --scenario="$SRC/test/ir/oracle/oracle_delivery_scenario.json" \
      "$SRC/test/ir/oracle/oracle_delivery.neu" -o "$ART/oracle-coordination"
    cp "$SRC/test/backend-guard/oracle/OracleDeliveryRollback.t.sol" \
      "$ART/oracle-coordination/test/"
    forge_test "$ART/oracle-coordination" ;;

  oracle-temporal)
    #  activation: the per-policy accepted() coordination's SOUND temporal
    # commit-ledger contract + its generated behavioral matrix (early/late, no-
    # progress, exactly-once, replay, changed-payload claim-mismatch, cross-key).
    have_forge || skip forge; forge_preflight; have_solc || skip solc; need_gen
    "$GEN" --target=solidity --scenario="$SRC/test/ir/oracle/accepted_multi_policy.scn.json" \
      "$SRC/test/ir/oracle/accepted_multi_policy.neu" -o "$ART/oracle-temporal"
    forge_test "$ART/oracle-temporal" ;;

  curated-solidity)
    have_forge || skip forge; forge_preflight; have_solc || skip solc; need_gen
    python3 "$SRC/test/curated/check_solidity_goldens.py" \
      --repo "$SRC" --gen "$GEN" --work "$ART/curated-solidity" \
      --profile "$SRC/examples/target-profiles/solidity.target-profile.json" \
      --forge "$FORGE" --solc "$SOLC" ;;

  core-compliance-guard)
    have_forge || skip forge; forge_preflight; have_solc || skip solc; have_docker || skip docker; need_gen
    ct_src="$SRC/test/ir/token/Inputs/core_compliance_guard_fixture.neu"
    ct_scen="$SRC/test/ir/token/Inputs/core_compliance_guard_fixture.scn.json"
    "$GEN" --target=solidity --scenario="$ct_scen" "$ct_src" -o "$ART/core-compliance-guard-sol"
    cp "$SRC/test/backend-guard/core_compliance_guard/CoreComplianceGuardFixtureGuard.t.sol" "$ART/core-compliance-guard-sol/test/"
    forge_test "$ART/core-compliance-guard-sol"
    "$GEN" --target=postgres --scenario="$ct_scen" "$ct_src" -o "$ART/core-compliance-guard-pg"
    bash "$SRC/test/backend-guard/core_compliance_guard/guard_loss_db_test.sh" "$ART/core-compliance-guard-pg" ;;

  postgres-quorum-guard)
    have_docker || skip docker; need_gen
    "$GEN" --target=postgres --scenario="$SRC/test/ir/oracle/oracle_delivery_scenario.json" \
      "$SRC/test/ir/oracle/oracle_delivery.neu" -o "$ART/oracle-postgres"
    bash "$SRC/test/backend-guard/oracle_delivery/quorum_fail_closed_db_test.sh" "$ART/oracle-postgres" ;;

  postgres-temporal-migration)
    # : the temporal per-policy `quorum_acceptance` shape differs from the
    # single-shot one; the temporal schema's upgrade preflight must deterministically
    # REFUSE a pre-existing single-shot table (a fresh-container test cannot catch it).
    have_docker || skip docker; need_gen
    "$GEN" --target=postgres --scenario="$SRC/test/ir/oracle/accepted_multi_policy.scn.json" \
      "$SRC/test/ir/oracle/accepted_multi_policy.neu" -o "$ART/temporal-mig"
    "$GEN" --target=postgres --scenario="$SRC/test/ir/oracle/oracle_delivery_scenario.json" \
      "$SRC/test/ir/oracle/oracle_delivery.neu" -o "$ART/single-shot-mig"
    bash "$SRC/test/backend-guard/temporal_migration/old_schema_refused_db_test.sh" \
      "$ART/temporal-mig" "$ART/single-shot-mig" ;;

  postgres-temporal)
    #  activation: the PostgreSQL per-policy accepted() commit-ledger contract
    # + its generated behavioral matrix (no-progress, per-policy incremental
    # commit + suppression, exactly-once, terminal, replay, changed-payload
    # claim-mismatch, cross-key isolation) against a real Postgres. The PG twin of
    # the oracle-temporal Solidity Forge matrix.
    have_docker || skip docker; need_gen
    "$GEN" --target=postgres --scenario="$SRC/test/ir/oracle/accepted_multi_policy.scn.json" \
      "$SRC/test/ir/oracle/accepted_multi_policy.neu" -o "$ART/oracle-temporal-pg"
    bash "$ART/oracle-temporal-pg/run_db_test.sh"
    # Cross-impl differential (): the SAME generated envelope must reproduce
    # the committed execution-claim vector f08e38… byte-for-byte — the PG leg of
    # the value ratchet (test/ir/oracle/execution_claim_vector.test).
    bash "$SRC/test/backend-guard/execution_claim_vector/pg_claim_vector_db_test.sh" \
      "$ART/oracle-temporal-pg" ;;

  curated-postgres)
    have_docker || skip docker; need_gen
    python3 "$SRC/test/curated/check_postgres_goldens.py" \
      --repo "$SRC" \
      --gen "$GEN" \
      --profile "$SRC/examples/target-profiles/postgres.target-profile.json" \
      --work "$ART/curated-postgres" \
      --real-postgres ;;

  cross-border)
    have_docker || skip docker; need_gen
    # The two remaining signature legs are external domain packs. Resolve their
    # source/scenario roles only after their published receipts and payload bytes
    # verify against this checkout's core bundle; there is no core fallback.
    [ -n "$PACK_RESOLVER" ] && [ -f "$PACK_RESOLVER" ] \
      || { echo "FAIL: cross-border pack resolver is missing"; exit 1; }
    pack_map="$ART/cross-border-packs.json"
    mkdir -p "$ART"
    python3 "$PACK_RESOLVER" --repo "$SRC" > "$pack_map"
    pack_field() {
      python3 - "$pack_map" "$1" "$2" <<'PY'
import json
import sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data[sys.argv[2]][sys.argv[3]])
PY
    }
    damage_procedure=
    export_procedure=
    for key in damage export; do
      source="$(pack_field "$key" source)"
      scenario="$(pack_field "$key" scenario)"
      procedure="$(pack_field "$key" member)"
      "$GEN" --target=postgres --scenario="$scenario" "$source" \
        -o "$ART/cross-border-$key"
      bash "$SRC/test/backend-guard/cross_border/acceptance_db_test.sh" \
        "$ART/cross-border-$key" "$key" "$procedure"
      if [ "$key" = damage ]; then
        damage_procedure="$procedure"
      else
        export_procedure="$procedure"
      fi
    done
    # Both verified pack inputs now compose in one real database, preserving
    # the existing procedure/key replay-isolation witness.
    bash "$SRC/test/backend-guard/cross_border/composed_replay_isolation_db_test.sh" \
      "$ART/cross-border-export" "$ART/cross-border-damage" \
      "$export_procedure" "$damage_procedure" ;;

  db)
    have_docker || skip docker; need_gen
    src="${NEU_SOURCE:-$(_dom core_sample_installment)}"
    scen="${NEU_SCENARIO:-$(_scn core_sample_installment)}"
    "$GEN" --target=postgres --scenario="$scen" "$src" -o "$ART/sql"
    bash "$ART/sql/run_db_test.sh" ;;

  postgres-balance-scope)
    #  PR2: the balanced obligation is scoped to (procedure, key) — a sibling
    # procedure reusing the raw key cannot fail/mask this procedure's balance.
    have_docker || skip docker; need_gen
    "$GEN" --target=postgres --scenario="$SRC/test/ir/token/Inputs/core_compliance_guard_fixture.scn.json" \
      "$SRC/test/ir/token/Inputs/core_compliance_guard_fixture.neu" -o "$ART/balance-scope"
    bash "$SRC/test/backend-guard/balance_scope/balance_scope_db_test.sh" \
      "$ART/balance-scope" ;;

  equivalence|equivalence-scheme)
    have_forge || skip forge; forge_preflight; have_solc || skip solc; need_gen
    EQUIV="${EQUIV:-$(dirname "$(dirname "$GEN")")/neutrino-equiv/neutrino-equiv}"
    [ -x "$EQUIV" ] || skip neutrino-equiv
    if [ "$KIND" = equivalence ]; then
      dom=core_sample_installment; out="$ART/equivalence"
    else
      dom=core_scheme_settlement; out="$ART/equivalence-scheme"
    fi
    src="${NEU_SOURCE:-$(_dom "$dom")}"
    scen="${NEU_SCENARIO:-$(_scn "$dom")}"
    mkdir -p "$ART"
    FORGE="$FORGE" SOLC="$SOLC" "$EQUIV" --scenario="$scen" "$src" --report="$out" ;;

  *) echo "run.sh: unknown kind '$KIND'" >&2; exit 2 ;;
esac
