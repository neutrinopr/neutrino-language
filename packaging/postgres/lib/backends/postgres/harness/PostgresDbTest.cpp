//===- PostgresDbTest.cpp - reconciliation/db-test harness (PG) -----------===//
//
// The PostgreSQL reconciliation/test responsibility (): renderDbTest builds
// run_db_test.sh, whose STRUCTURE is single-sourced from the same frozen spec
// as procedure.sql (so they cannot drift) and whose concrete values come from
// the folded TestRealization. View.h-free. Byte-identical to the pre-split
// harness.
//
//===----------------------------------------------------------------------===//

#include "PostgresSpecInternal.h"

#include "Neutrino/Attestation.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/CoordinationEnvelope.h"
#include "Neutrino/Expr.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/TestRealization.h"
#include "Neutrino/ValueModel.h"

#include "llvm/Support/JSON.h"

#include <algorithm>
#include <map>
#include <string>
#include <vector>

using namespace llvm;

namespace neutrino::postgres_detail {

namespace {

template <typename T> T expectSpec(Expected<T> value) {
  if (value)
    return *value;
  throw ExprError("spec.ast", toString(value.takeError()));
}

} // namespace

// Evidence-only docker/psql harness (): defined below, dispatched from
// renderDbTest when the coordination-plan is effectless.
std::string renderEvidenceDbTest(const json::Object &spec,
                                 const TestRealization &tr,
                                 const CoordinationPlan &coordinationPlan);

// The temporal () per-policy multi-admit/multi-execute harness: defined
// below, dispatched when any effect group carries the TemporalSuppress gate.
std::string renderTemporalDbTest(const json::Object &spec,
                                 const TestRealization &tr,
                                 const CoordinationPlan &coordinationPlan);

namespace {
// A temporal coordination gates at least one group on an accepted() policy —
// the per-(key,policy) commit-ledger contract, not the single-shot execute.
bool isTemporalPlan(const CoordinationPlan &coordinationPlan) {
  for (const PlanEffect &pe : coordinationPlan.effects)
    if (pe.gateMode == PlanGateMode::TemporalSuppress)
      return true;
  return false;
}
} // namespace

std::string renderDbTest(const json::Object &spec, const TestRealization &tr,
                         const CoordinationPlan &coordinationPlan) {
  if (coordinationPlan.evidenceOnly)
    return renderEvidenceDbTest(spec, tr, coordinationPlan);
  if (isTemporalPlan(coordinationPlan))
    return renderTemporalDbTest(spec, tr, coordinationPlan);

  // STRUCTURE is single-sourced from the spec (same object procedure.sql
  // renders from), so the harness cannot drift from the procedure; only
  // concrete values/ledger come from the folded TestRealization (WP2, ).
  std::string name =
      expectSpec(requiredString(spec, "procedure", "capability-spec")).str();
  std::string fn = "execute_" + name;

  const json::Array &inputsA =
      *expectSpec(requiredArray(spec, "inputs", "capability-spec"));
  const json::Array &effectsA =
      *expectSpec(requiredArray(spec, "effects", "capability-spec"));
  if (effectsA.empty())
    throw ExprError("spec.ast", "procedure has no ledger entries");

  // input names in spec order + their SQL category (drives bigint vs string
  // literal), sourced from the spec — never re-derived from the scenario.
  std::vector<std::string> inputOrder;
  std::map<std::string, std::string> inputType;
  for (const json::Value &v : inputsA) {
    const json::Object &in = obj(&v, "input");
    std::string n = in.getString("name").value_or("").str();
    inputOrder.push_back(n);
    inputType[n] = in.getString("type").value_or("").str();
  }

  // The workflow key comes off the SAME normalized coordinationPlan instance
  // () the procedure renderer reads, so the harness cannot key on a
  // different input than the procedure it exercises.
  std::string key = coordinationPlan.workflowKey;

  // Gated (): a quorum-accepted spec has NO attest_<proc>; the harness
  // instead seeds M synthetic authorized observers and drives accept_<proc>
  // (the full fail-closed matrix — unauthorized/duplicate/<M/replay/different
  // claim — is proven by the dedicated adversarial db test, wired into CI).
  std::vector<AttestationPolicy> policies = attestationPoliciesFromSpec(spec);
  bool gated = !policies.empty();
  int quorumM = gated ? policies.front().quorum : 0;
  std::string observerSet = gated ? policies.front().observerSet : "";
  // Synthetic quorum: M distinct observer ids + the ARRAY[...] literal for
  // accept, and the seed INSERTs into authorized_observer.
  std::string obsArray = "ARRAY[";
  std::string obsSeed;
  for (int i = 1; i <= quorumM; ++i) {
    std::string oid = "obs-" + std::to_string(i);
    obsArray += (i > 1 ? ", " : "") + sqlQuote(oid);
    obsSeed += "INSERT INTO authorized_observer(observer_set, observer_id) "
               "VALUES (" +
               sqlQuote(observerSet) + ", " + sqlQuote(oid) +
               ") ON CONFLICT DO NOTHING;\n";
  }
  obsArray += "]";
  // The acceptance step for a workflow key: accept the quorum (gated) or the
  // legacy self-attest (unattested).
  auto admit = [&](const std::string &keyLit) -> std::string {
    return gated ? ("SELECT accept_" + name + "(" + keyLit +
                    ", 'claim-hash-1', " + obsArray + ");")
                 : ("SELECT attest_" + name + "(" + keyLit + ");");
  };

  // Concrete values come from the realized cases (WP2, ).
  std::string keyVal = tr.inputs.at(key).s;
  auto shellValue = [&](const std::string &n) -> std::string {
    const ScenarioInput &in = tr.inputs.at(n);
    if (sqlType(inputType[n]) == "bigint")
      return std::to_string(in.i);
    return sqlQuote(in.s);
  };

  // positional args (happy path) and rollback variant (different key)
  std::string args, rollbackArgs;
  for (size_t i = 0; i < inputOrder.size(); ++i) {
    const std::string &n = inputOrder[i];
    std::string v = shellValue(n);
    args += v + (i + 1 < inputOrder.size() ? ", " : "");
    rollbackArgs += (n == key ? "'txn-rollback'" : v) +
                    std::string(i + 1 < inputOrder.size() ? ", " : "");
  }

  std::string escKey = sqlEsc(keyVal);
  // Expected posting count = the legs that actually FIRE for this scenario: an
  // unguarded leg always posts; a guarded leg () posts iff its predicate
  // holds for the realized values. Evaluate each guard over the concrete
  // numeric env (inputs + computed), exactly as the reference evaluator does,
  // so the harness's count matches the guard-aware SQL.
  std::map<std::string, long long> genv;
  for (const auto &kv : inputType)
    if (sqlType(kv.second) == "bigint")
      genv[kv.first] = tr.inputs.at(kv.first).i;
  for (const auto &kv : tr.computed)
    genv[kv.first] = kv.second;
  long long fired = 0;
  for (const json::Value &v : effectsA) {
    const json::Object &e = obj(&v, "effect");
    if (const json::Value *whenV = e.get("when")) {
      const json::Value *astJson = obj(whenV, "when").get("ast");
      if (!astJson)
        throw ExprError("spec.ast", "when guard needs an ast");
      if (!evalGuard(*exprFromJson(*astJson), genv))
        continue;
    }
    ++fired;
  }
  std::string nEntries = std::to_string(fired);
  const std::string drift =
      "SELECT count(*) FROM (SELECT idempotency_key FROM postings GROUP BY "
      "idempotency_key HAVING SUM(signed_amount)<>0) x;";

  std::vector<std::string> L;
  L.push_back("#!/usr/bin/env bash");
  L.push_back("# Generated by the Neutrino Translator. Proves the PostgreSQL "
              "capability-spec against a");
  L.push_back("# real PostgreSQL container via docker + psql (no Python). All "
              "dynamic SQL is");
  L.push_back("# fed through quoted heredocs, so the shell never interpolates "
              "scenario values;");
  L.push_back("# SQL string literals are '-escaped.");
  L.push_back("set -euo pipefail");
  L.push_back("HERE=\"$(cd \"$(dirname \"$0\")\" && pwd)\"");
  L.push_back("CID=$(docker run -d -e POSTGRES_PASSWORD=test -e "
              "POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)");
  L.push_back("cleanup(){ docker rm -f \"$CID\" >/dev/null 2>&1 || true; }");
  L.push_back("trap cleanup EXIT");
  L.push_back("psql(){ docker exec -i \"$CID\" psql -v ON_ERROR_STOP=1 -U test "
              "-d neutrino \"$@\"; }");
  L.push_back("echo 'waiting for postgres...'");
  L.push_back("ready=0");
  L.push_back("for _ in $(seq 1 60); do");
  L.push_back(
      "  if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi");
  L.push_back("  sleep 1");
  L.push_back("done");
  L.push_back("[ \"$ready\" = 1 ] || { echo 'FAIL: postgres did not become "
              "ready'; exit 1; }");
  L.push_back("");
  // Machine-readable stage markers: the last one emitted before a failure names
  // the stage (schema/procedure LOAD = compile, behavioral assertions =
  // runtime), so a consumer distinguishes a load/compile rejection from an
  // execution failure structurally, not by scraping log text.
  L.push_back("echo NEUTRINO_STAGE=compile");
  L.push_back("psql -q < \"$HERE/schema.sql\" >/dev/null");
  L.push_back("psql -q < \"$HERE/procedure.sql\" >/dev/null");
  L.push_back("echo NEUTRINO_STAGE=runtime");
  L.push_back("");
  if (gated) {
    // Seed the bound observer set (N, members) — the deploy-time step the
    // rendered DDL leaves open; the concrete members are a harness fixture.
    L.push_back("psql -q >/dev/null <<'SQL'");
    L.push_back(obsSeed + "SQL");
    L.push_back("");
  }
  // admit (accept quorum / attest) -> execute the happy-path key (quoted
  // heredoc
  // => no shell interpolation)
  L.push_back("run(){ psql -tAq >/dev/null <<'SQL'");
  L.push_back(admit("'" + escKey + "'"));
  L.push_back("SELECT " + fn + "(" + args + ");");
  L.push_back("SQL");
  L.push_back("}");
  L.push_back("expect_fail(){ if psql -tAq >/dev/null 2>&1; then echo \"FAIL: "
              "$1 not refused\"; exit 1; fi; }");

  // scalar(varname, sql): VAR=$(psql -tAq <<'SQL' ... SQL )
  auto scalar = [&](const std::string &var, const std::string &sql) {
    L.push_back(var + "=$(psql -tAq <<'SQL'");
    L.push_back(sql);
    L.push_back("SQL");
    L.push_back(")");
  };

  L.push_back("");
  L.push_back(gated
                  ? "# 1. quorum gate: execute without an accepted quorum is "
                    "refused"
                  : "# 1. attestation gate: execute without a prior attest is "
                    "refused");
  L.push_back(std::string("expect_fail '") +
              (gated ? "unaccepted execute" : "unattested execute") +
              "' <<'SQL'");
  L.push_back("SELECT " + fn + "(" + args + ");");
  L.push_back("SQL");
  L.push_back(gated ? "echo '  [1] quorum gate: PASS'"
                    : "echo '  [1] attestation gate: PASS'");
  L.push_back("");
  L.push_back("# 2. happy path (attest+execute): balances move; a missing "
              "ledger row is upserted");
  L.push_back("run");
  for (auto &kv : tr.ledger) {
    scalar(
        "V",
        "SELECT COALESCE(SUM(balance),0) FROM ledger_balance WHERE ledger='" +
            sqlEsc(kv.first) + "';");
    L.push_back("[ \"$V\" = \"" + std::to_string(kv.second) +
                "\" ] || { echo \"FAIL: net mismatch\"; exit 1; }");
  }
  scalar("N", "SELECT count(*) FROM postings WHERE idempotency_key='" + escKey +
                  "';");
  L.push_back("[ \"$N\" = \"" + nEntries +
              "\" ] || { echo \"FAIL: postings=$N\"; exit 1; }");
  L.push_back("echo '  [2] happy path balances + upsert: PASS'");
  L.push_back("");
  L.push_back("# 3. replay: re-executing a reconciled key is refused");
  L.push_back("expect_fail 'replay' <<'SQL'");
  L.push_back("SELECT " + fn + "(" + args + ");");
  L.push_back("SQL");
  L.push_back("echo '  [3] replay refused: PASS'");
  L.push_back("");
  if (gated) {
    // Gated: replay of an already-accepted claim is refused (the accept-side
    // idempotency lock, parity with the Solidity guard's accepted[claimId]).
    L.push_back(
        "# 4. quorum replay: re-accepting an accepted claim is refused");
    L.push_back("expect_fail 'already accepted' <<'SQL'");
    L.push_back(admit("'" + escKey + "'"));
    L.push_back("SQL");
    L.push_back("echo '  [4] quorum replay refused: PASS'");
  } else {
    L.push_back("# 4. bad transition: attesting a reconciled key is refused");
    L.push_back("expect_fail 'bad transition' <<'SQL'");
    L.push_back("SELECT attest_" + name + "('" + escKey + "');");
    L.push_back("SQL");
    L.push_back("echo '  [4] bad transition refused: PASS'");
  }
  L.push_back("");
  L.push_back("# 5. reconciliation: no drift on the happy path");
  scalar("D", drift);
  L.push_back("[ \"$D\" = \"0\" ] || { echo \"FAIL: unexpected drift "
              "rows=$D\"; exit 1; }");
  L.push_back("echo '  [5] reconciliation no drift: PASS'");
  L.push_back("");
  L.push_back("# 6. reconciliation detects an injected drift");
  L.push_back("psql -q >/dev/null <<'SQL'");
  L.push_back("INSERT INTO "
              "postings(procedure,entry,ledger,party,amount,currency,signed_"
              "amount,idempotency_key)");
  // a deliberately-bogus row; only signed_amount matters for drift detection,
  // so party/ledger/currency are safe constants (no dependency on scenario
  // inputs).
  L.push_back("VALUES ('" + sqlEsc(name) +
              "','injected','injected','injected',1,'X',1,'" + escKey + "');");
  L.push_back("SQL");
  scalar("D2", drift);
  L.push_back("[ \"$D2\" -ge \"1\" ] || { echo \"FAIL: drift not detected\"; "
              "exit 1; }");
  L.push_back("echo '  [6] reconciliation detects injected drift: PASS'");
  L.push_back("");
  L.push_back(gated ? "# 7. atomic rollback: a rolled-back accept+execute "
                      "leaves no rows"
                    : "# 7. atomic rollback: a rolled-back attest+execute "
                      "leaves no rows");
  L.push_back("psql -q >/dev/null <<'SQL'");
  L.push_back("BEGIN;");
  L.push_back(admit("'txn-rollback'"));
  L.push_back("SELECT " + fn + "(" + rollbackArgs + ");");
  L.push_back("ROLLBACK;");
  L.push_back("SQL");
  scalar("NR",
         "SELECT count(*) FROM postings WHERE idempotency_key='txn-rollback';");
  L.push_back("[ \"$NR\" = \"0\" ] || { echo \"FAIL: rollback left rows=$NR\"; "
              "exit 1; }");
  L.push_back("echo '  [7] atomic rollback: PASS'");
  L.push_back("");
  L.push_back("echo 'ALL POSTGRES CHECKS PASSED'");

  std::string out;
  for (auto &l : L)
    out += l + "\n";
  return out;
}

// Evidence-only docker/psql harness (): proves the effectless
// execute_<proc> — refused without an accepted quorum, records the accepted
// terminal on the happy path, refuses replay + quorum-replay, keeps distinct
// instance keys isolated, and rolls back atomically. It asserts NOTHING about
// ledger balances or postings (there are none).
std::string renderEvidenceDbTest(const json::Object &spec,
                                 const TestRealization &tr,
                                 const CoordinationPlan &coordinationPlan) {
  std::string name = spec.getString("procedure").value_or("").str();
  std::string fn = "execute_" + name;

  const json::Array *inputsA = spec.getArray("inputs");
  if (!inputsA)
    throw ExprError("spec.ast", "capability-spec: missing inputs");

  std::vector<std::string> inputOrder;
  std::map<std::string, std::string> inputType;
  for (const json::Value &v : *inputsA) {
    const json::Object &in = obj(&v, "input");
    std::string n = in.getString("name").value_or("").str();
    inputOrder.push_back(n);
    inputType[n] = in.getString("type").value_or("").str();
  }

  std::string key = coordinationPlan.workflowKey;

  // Evidence-only is gated by construction; drive the SAME accept_<proc> with M
  // synthetic authorized observers (the full fail-closed matrix is proven by
  // the shared adversarial db test).
  std::vector<AttestationPolicy> policies = attestationPoliciesFromSpec(spec);
  int quorumM = policies.empty() ? 0 : policies.front().quorum;
  std::string observerSet =
      policies.empty() ? "" : policies.front().observerSet;
  std::string obsArray = "ARRAY[";
  std::string obsSeed;
  for (int i = 1; i <= quorumM; ++i) {
    std::string oid = "obs-" + std::to_string(i);
    obsArray += (i > 1 ? ", " : "") + sqlQuote(oid);
    obsSeed += "INSERT INTO authorized_observer(observer_set, observer_id) "
               "VALUES (" +
               sqlQuote(observerSet) + ", " + sqlQuote(oid) +
               ") ON CONFLICT DO NOTHING;\n";
  }
  obsArray += "]";
  auto admit = [&](const std::string &keyLit) -> std::string {
    return "SELECT accept_" + name + "(" + keyLit + ", 'claim-hash-1', " +
           obsArray + ");";
  };

  std::string keyVal = tr.inputs.at(key).s;
  auto shellValue = [&](const std::string &n) -> std::string {
    const ScenarioInput &in = tr.inputs.at(n);
    if (sqlType(inputType[n]) == "bigint")
      return std::to_string(in.i);
    return sqlQuote(in.s);
  };
  std::string args, rollbackArgs;
  for (size_t i = 0; i < inputOrder.size(); ++i) {
    const std::string &n = inputOrder[i];
    std::string v = shellValue(n);
    args += v + (i + 1 < inputOrder.size() ? ", " : "");
    rollbackArgs += (n == key ? "'txn-rollback'" : v) +
                    std::string(i + 1 < inputOrder.size() ? ", " : "");
  }
  std::string escKey = sqlEsc(keyVal);
  // Isolation call: the same inputs with the key input swapped to a distinct
  // "-2" instance (mirrors the harness's alt-key convention).
  std::string altArgs;
  for (size_t i = 0; i < inputOrder.size(); ++i) {
    const std::string &n = inputOrder[i];
    altArgs += (n == key ? ("'" + escKey + "-2'") : shellValue(n)) +
               (i + 1 < inputOrder.size() ? ", " : "");
  }
  auto acceptedCount = [](const std::string &k) {
    return "SELECT count(*) FROM coordination_status WHERE idempotency_key='" +
           k + "' AND reconciled;";
  };

  std::vector<std::string> L;
  L.push_back("#!/usr/bin/env bash");
  L.push_back(
      "# Generated by the Neutrino Translator. Proves the evidence-only "
      "PostgreSQL");
  L.push_back("# coordination against a real PostgreSQL container via docker + "
              "psql (no Python).");
  L.push_back("# It records ACCEPTED attested evidence by instance key and "
              "moves NO ledger value,");
  L.push_back("# so there are no balances/postings to assert. All dynamic SQL "
              "is fed through");
  L.push_back("# quoted heredocs, so the shell never interpolates scenario "
              "values.");
  L.push_back("set -euo pipefail");
  L.push_back("HERE=\"$(cd \"$(dirname \"$0\")\" && pwd)\"");
  L.push_back("CID=$(docker run -d -e POSTGRES_PASSWORD=test -e "
              "POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)");
  L.push_back("cleanup(){ docker rm -f \"$CID\" >/dev/null 2>&1 || true; }");
  L.push_back("trap cleanup EXIT");
  L.push_back("psql(){ docker exec -i \"$CID\" psql -v ON_ERROR_STOP=1 -U test "
              "-d neutrino \"$@\"; }");
  L.push_back("echo 'waiting for postgres...'");
  L.push_back("ready=0");
  L.push_back("for _ in $(seq 1 60); do");
  L.push_back(
      "  if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi");
  L.push_back("  sleep 1");
  L.push_back("done");
  L.push_back("[ \"$ready\" = 1 ] || { echo 'FAIL: postgres did not become "
              "ready'; exit 1; }");
  L.push_back("");
  // Machine-readable stage markers: the last one emitted before a failure names
  // the stage (schema/procedure LOAD = compile, behavioral assertions =
  // runtime), so a consumer distinguishes a load/compile rejection from an
  // execution failure structurally, not by scraping log text.
  L.push_back("echo NEUTRINO_STAGE=compile");
  L.push_back("psql -q < \"$HERE/schema.sql\" >/dev/null");
  L.push_back("psql -q < \"$HERE/procedure.sql\" >/dev/null");
  L.push_back("echo NEUTRINO_STAGE=runtime");
  L.push_back("");
  L.push_back("psql -q >/dev/null <<'SQL'");
  L.push_back(obsSeed + "SQL");
  L.push_back("");
  L.push_back("run(){ psql -tAq >/dev/null <<'SQL'");
  L.push_back(admit("'" + escKey + "'"));
  L.push_back("SELECT " + fn + "(" + args + ");");
  L.push_back("SQL");
  L.push_back("}");
  L.push_back("expect_fail(){ if psql -tAq >/dev/null 2>&1; then echo \"FAIL: "
              "$1 not refused\"; exit 1; fi; }");

  auto scalar = [&](const std::string &var, const std::string &sql) {
    L.push_back(var + "=$(psql -tAq <<'SQL'");
    L.push_back(sql);
    L.push_back("SQL");
    L.push_back(")");
  };

  L.push_back("");
  L.push_back("# 1. quorum gate: accepting evidence without an accepted quorum "
              "is refused");
  L.push_back("expect_fail 'unaccepted execute' <<'SQL'");
  L.push_back("SELECT " + fn + "(" + args + ");");
  L.push_back("SQL");
  L.push_back("echo '  [1] quorum gate: PASS'");
  L.push_back("");
  L.push_back("# 2. happy path (accept quorum + record): the accepted terminal "
              "is written; NO ledger value moves");
  L.push_back("run");
  scalar("A", acceptedCount(escKey));
  L.push_back("[ \"$A\" = \"1\" ] || { echo \"FAIL: accepted=$A\"; exit 1; }");
  L.push_back("echo '  [2] happy path records accepted evidence: PASS'");
  L.push_back("");
  L.push_back("# 3. replay: re-recording an accepted instance key is refused");
  L.push_back("expect_fail 'replay' <<'SQL'");
  L.push_back("SELECT " + fn + "(" + args + ");");
  L.push_back("SQL");
  L.push_back("echo '  [3] replay refused: PASS'");
  L.push_back("");
  L.push_back("# 4. quorum replay: re-accepting an accepted claim is refused");
  L.push_back("expect_fail 'already accepted' <<'SQL'");
  L.push_back(admit("'" + escKey + "'"));
  L.push_back("SQL");
  L.push_back("echo '  [4] quorum replay refused: PASS'");
  L.push_back("");
  L.push_back("# 5. instance isolation: a distinct instance key is accepted + "
              "recorded independently");
  L.push_back("psql -tAq >/dev/null <<'SQL'");
  L.push_back(admit("'" + escKey + "-2'"));
  L.push_back("SELECT " + fn + "(" + altArgs + ");");
  L.push_back("SQL");
  scalar("A2", acceptedCount(escKey + "-2"));
  L.push_back("[ \"$A2\" = \"1\" ] || { echo \"FAIL: isolated accepted=$A2\"; "
              "exit 1; }");
  scalar("A1", acceptedCount(escKey));
  L.push_back(
      "[ \"$A1\" = \"1\" ] || { echo \"FAIL: first key disturbed=$A1\"; "
      "exit 1; }");
  L.push_back("echo '  [5] instance isolation: PASS'");
  L.push_back("");
  L.push_back(
      "# 6. atomic rollback: a rolled-back accept+record leaves no rows");
  L.push_back("psql -q >/dev/null <<'SQL'");
  L.push_back("BEGIN;");
  L.push_back(admit("'txn-rollback'"));
  L.push_back("SELECT " + fn + "(" + rollbackArgs + ");");
  L.push_back("ROLLBACK;");
  L.push_back("SQL");
  scalar("NR", acceptedCount("txn-rollback"));
  L.push_back("[ \"$NR\" = \"0\" ] || { echo \"FAIL: rollback left rows=$NR\"; "
              "exit 1; }");
  scalar("NQ", "SELECT count(*) FROM quorum_acceptance WHERE "
               "claim_id='txn-rollback';");
  L.push_back("[ \"$NQ\" = \"0\" ] || { echo \"FAIL: rollback left quorum "
              "rows=$NQ\"; exit 1; }");
  L.push_back("echo '  [6] atomic rollback: PASS'");
  L.push_back("");
  L.push_back("echo 'ALL POSTGRES CHECKS PASSED'");

  std::string out;
  for (auto &l : L)
    out += l + "\n";
  return out;
}

// The temporal () behavioral matrix harness — the executable semantic proof
// of the per-(key,policy) commit-ledger contract against a real Postgres. Its
// STRUCTURE is single-sourced from the normalized coordination plan (the same
// instance the procedure renders from), so it cannot drift; concrete values
// come from the folded TestRealization. It drives multi-admit / multi-execute:
//   [1] no-progress   — execute with no accepted policy posts nothing, binds no
//                       claim, does not reconcile (a balanced no-op, not a
//                       fail);
//   [2..] incremental — accept ONE policy, execute: only that group's balanced
//                       pair commits (the others stay suppressed), the key
//                       claim is pinned on the first commit, no premature
//                       terminal;
//   terminal          — only once EVERY required group has committed;
//   exactly-once      — re-accepting a policy / re-executing after terminal is
//                       refused; a redundant execute double-posts nothing;
//   changed-payload   — a later execute on a committed key with a different
//                       payload recomputes a different claim and is refused;
//   cross-key         — an independent key runs its own flow to its own
//   terminal
//                       without disturbing the first key's committed state.
std::string renderTemporalDbTest(const json::Object &spec,
                                 const TestRealization &tr,
                                 const CoordinationPlan &coordinationPlan) {
  (void)spec;
  // The harness is only rendered for a temporal projected coordination
  // already accepted (non-empty effects, every policy the reviewed 'exact'
  // quorum) — it fails closed FIRST in the same run, so this re-validates
  // nothing.
  std::string name = coordinationPlan.procedure;
  std::string fn = "execute_" + name;
  std::string key = coordinationPlan.workflowKey;
  std::string identity = coordinationIdentityHash(coordinationPlan);

  // input SQL type (bigint vs text literal), in declared order (the execute_
  // positional-argument order the procedure renders).
  std::map<std::string, std::string> inputType;
  for (const PlanInput &in : coordinationPlan.inputs)
    inputType[in.name] = in.type;

  // The  claim preimage arrays: inputs sorted by name, with the constant
  // (name, category) columns and a per-value-map value column. IDENTICAL to
  // buildClaimArrays in the legalizer, so accept's recorded executionClaim
  // binds to exactly the claim execute_ recomputes.
  std::vector<PlanInput> sorted = coordinationPlan.inputs;
  std::stable_sort(
      sorted.begin(), sorted.end(),
      [](const auto &a, const auto &b) { return a.name < b.name; });
  std::string namesArr = "ARRAY[", catsArr = "ARRAY[";
  for (size_t i = 0; i < sorted.size(); ++i) {
    std::string sep = (i + 1 < sorted.size() ? ", " : "");
    namesArr += sqlQuote(sorted[i].name) + sep;
    catsArr +=
        sqlQuote(categoryName(classifyValueType(sorted[i].type)).str()) + sep;
  }
  namesArr += "]::text[]";
  catsArr += "]::text[]";

  // The concrete value map (raw, unquoted): a numeric input is its decimal
  // minor-units string (matching execute's (p_x)::text), a symbolic one its
  // string. Callers clone + override (a new key, a bumped amount).
  std::map<std::string, std::string> baseVal;
  for (const PlanInput &in : coordinationPlan.inputs) {
    const ScenarioInput &si = tr.inputs.at(in.name);
    baseVal[in.name] =
        sqlType(in.type) == "bigint" ? std::to_string(si.i) : si.s;
  }
  auto argFor = [&](const std::string &n,
                    const std::map<std::string, std::string> &vm) {
    return sqlType(inputType[n]) == "bigint" ? vm.at(n) : sqlQuote(vm.at(n));
  };
  auto positionalArgs = [&](const std::map<std::string, std::string> &vm) {
    std::string a;
    for (size_t i = 0; i < coordinationPlan.inputs.size(); ++i)
      a += argFor(coordinationPlan.inputs[i].name, vm) +
           (i + 1 < coordinationPlan.inputs.size() ? ", " : "");
    return a;
  };
  // neu_execution_claim(identity, key, names, cats, vals) over the value map —
  // the exact expression the accept step feeds as p_execution_claim so it binds
  // to what execute_ recomputes from the same values.
  auto buildClaim = [&](const std::map<std::string, std::string> &vm) {
    std::string vals = "ARRAY[";
    for (size_t i = 0; i < sorted.size(); ++i)
      vals +=
          sqlQuote(vm.at(sorted[i].name)) + (i + 1 < sorted.size() ? ", " : "");
    vals += "]::text[]";
    return "neu_execution_claim(" + sqlQuote(identity) + ", " +
           sqlQuote(vm.at(key)) + ", " + namesArr + ", " + catsArr + ", " +
           vals + ")";
  };

  // Per-policy synthetic quorum (M distinct authorized observers per set) + the
  // temporal groups in commit order (group_ordinal = the coordination's group
  // index).
  std::map<std::string, int> polM;
  std::map<std::string, std::string> polSet;
  for (const AttestationPolicy &p : coordinationPlan.attestations) {
    polM[p.input] = p.quorum;
    polSet[p.input] = p.observerSet;
  }
  auto obsArray = [&](const std::string &policy) {
    std::string set = polSet.at(policy);
    std::string a = "ARRAY[";
    for (int i = 1; i <= polM.at(policy); ++i)
      a += (i > 1 ? ", " : "") +
           sqlQuote("obs-" + set + "-" + std::to_string(i));
    return a + "]";
  };
  struct TGroup {
    size_t gi;
    std::string policy;
    std::vector<std::string> ledgers;
  };
  std::vector<TGroup> tgroups;
  for (size_t gi = 0; gi < coordinationPlan.effectGroups.size(); ++gi) {
    const PlanEffectGroup &g = coordinationPlan.effectGroups[gi];
    if (g.gateMode != PlanGateMode::TemporalSuppress)
      continue;
    TGroup t;
    t.gi = gi;
    t.policy = g.gatePolicy;
    for (size_t idx : g.effectIndices)
      t.ledgers.push_back(coordinationPlan.effects[idx].ledger);
    tgroups.push_back(t);
  }

  std::string k1 = tr.inputs.at(key).s;
  std::string k2 = k1 + "-x2";
  std::string kc = k1 + "-cp";
  auto vmFor = [&](const std::string &kv) {
    std::map<std::string, std::string> vm = baseVal;
    vm[key] = kv;
    return vm;
  };

  std::vector<std::string> L;
  auto ok = [&](const std::string &stmt) {
    L.push_back("psql -tAq >/dev/null <<'SQL'");
    L.push_back(stmt);
    L.push_back("SQL");
  };
  auto expectFail = [&](const std::string &msg, const std::string &stmt) {
    L.push_back("expect_fail '" + msg + "' <<'SQL'");
    L.push_back(stmt);
    L.push_back("SQL");
  };
  auto scalar = [&](const std::string &var, const std::string &sql) {
    L.push_back(var + "=$(psql -tAq <<'SQL'");
    L.push_back(sql);
    L.push_back("SQL");
    L.push_back(")");
  };
  auto eq = [&](const std::string &var, const std::string &want,
                const std::string &what) {
    L.push_back("[ \"$" + var + "\" = \"" + want + "\" ] || { echo \"FAIL: " +
                what + "=$" + var + " (want " + want + ")\"; exit 1; }");
  };
  auto acceptStmt = [&](const std::string &policy, const std::string &kv) {
    std::map<std::string, std::string> vm = vmFor(kv);
    return "SELECT accept_" + name + "(" + sqlQuote(kv) + ", " +
           sqlQuote(policy) + ", 'canon-" + sqlEsc(policy) + "', " +
           buildClaim(vm) + ", " + obsArray(policy) + ");";
  };
  auto executeStmt = [&](const std::string &kv) {
    return "SELECT " + fn + "(" + positionalArgs(vmFor(kv)) + ");";
  };
  auto committedCount = [&](const std::string &kv) {
    return "SELECT count(*) FROM committed_group WHERE procedure='" +
           sqlEsc(name) + "' AND idempotency_key=" + sqlQuote(kv) + ";";
  };
  auto reconciledOf = [&](const std::string &kv) {
    return "SELECT COALESCE((SELECT reconciled FROM coordination_status WHERE "
           "procedure='" +
           sqlEsc(name) + "' AND idempotency_key=" + sqlQuote(kv) +
           "), false);";
  };
  auto keyClaimCount = [&](const std::string &kv) {
    return "SELECT count(*) FROM key_claim WHERE procedure='" + sqlEsc(name) +
           "' AND idempotency_key=" + sqlQuote(kv) + ";";
  };
  auto postingsCount = [&](const std::string &kv) {
    return "SELECT count(*) FROM postings WHERE idempotency_key=" +
           sqlQuote(kv) + ";";
  };
  auto ledgerSum = [&](const std::string &ledger) {
    return "SELECT COALESCE(SUM(balance),0) FROM ledger_balance WHERE "
           "ledger='" +
           sqlEsc(ledger) + "';";
  };

  L.push_back("#!/usr/bin/env bash");
  L.push_back("# Generated by the Neutrino Translator ( temporal). Proves "
              "the per-(key,policy)");
  L.push_back("# commit-ledger contract against a real PostgreSQL via docker + "
              "psql. All dynamic");
  L.push_back("# SQL is fed through quoted heredocs — the shell never "
              "interpolates scenario values.");
  L.push_back("set -euo pipefail");
  L.push_back("HERE=\"$(cd \"$(dirname \"$0\")\" && pwd)\"");
  L.push_back("CID=$(docker run -d -e POSTGRES_PASSWORD=test -e "
              "POSTGRES_USER=test -e POSTGRES_DB=neutrino postgres:16-alpine)");
  L.push_back("cleanup(){ docker rm -f \"$CID\" >/dev/null 2>&1 || true; }");
  L.push_back("trap cleanup EXIT");
  L.push_back("psql(){ docker exec -i \"$CID\" psql -v ON_ERROR_STOP=1 -U test "
              "-d neutrino \"$@\"; }");
  L.push_back("echo 'waiting for postgres...'");
  L.push_back("ready=0");
  L.push_back("for _ in $(seq 1 60); do");
  L.push_back(
      "  if psql -tAq -c 'SELECT 1' >/dev/null 2>&1; then ready=1; break; fi");
  L.push_back("  sleep 1");
  L.push_back("done");
  L.push_back("[ \"$ready\" = 1 ] || { echo 'FAIL: postgres did not become "
              "ready'; exit 1; }");
  L.push_back("");
  // Machine-readable stage markers: the last one emitted before a failure names
  // the stage (schema/procedure LOAD = compile, behavioral assertions =
  // runtime), so a consumer distinguishes a load/compile rejection from an
  // execution failure structurally, not by scraping log text.
  L.push_back("echo NEUTRINO_STAGE=compile");
  L.push_back("psql -q < \"$HERE/schema.sql\" >/dev/null");
  L.push_back("psql -q < \"$HERE/procedure.sql\" >/dev/null");
  L.push_back("echo NEUTRINO_STAGE=runtime");
  L.push_back("");
  // expect_fail requires the SPECIFIC refusal, not merely a nonzero psql exit:
  // it captures stderr and asserts the expected RAISE message is present, so a
  // replay / missing-column / type / unrelated runtime error cannot masquerade
  // as the claimed refusal (e.g. a premature-terminal regression that reverts
  // with 'replay' must NOT pass a 'claim mismatch' assertion).
  L.push_back("expect_fail(){ local msg=\"$1\" err;");
  L.push_back("  if err=$(psql -tAq 2>&1); then echo \"FAIL: $msg not "
              "refused\"; exit 1; fi;");
  L.push_back("  case \"$err\" in *\"$msg\"*) ;; *) echo \"FAIL: expected "
              "refusal '$msg' but got: $err\"; exit 1;; esac; }");
  L.push_back("");
  // Seed the bound observer set(s) — the deploy-time GRANT/seed the DDL leaves
  // open; the concrete members are a harness fixture.
  L.push_back("psql -q >/dev/null <<'SQL'");
  {
    std::string seed;
    for (const auto &kv : polSet)
      for (int i = 1; i <= polM.at(kv.first); ++i)
        seed += "INSERT INTO authorized_observer(observer_set, observer_id) "
                "VALUES (" +
                sqlQuote(kv.second) + ", " +
                sqlQuote("obs-" + kv.second + "-" + std::to_string(i)) +
                ") ON CONFLICT DO NOTHING;\n";
    L.push_back(seed + "SQL");
  }
  L.push_back("");

  // [1] no-progress: execute with no accepted policy is a balanced no-op.
  L.push_back("# 1. no-progress: execute before any policy is accepted posts "
              "nothing, binds no claim, does not reconcile");
  ok(executeStmt(k1));
  scalar("P", postingsCount(k1));
  eq("P", "0", "no-progress postings");
  scalar("C", committedCount(k1));
  eq("C", "0", "no-progress committed groups");
  scalar("KC", keyClaimCount(k1));
  eq("KC", "0", "no-progress key_claim bound");
  scalar("R", reconciledOf(k1));
  eq("R", "f", "no-progress reconciled");
  L.push_back("echo '  [1] no-progress balanced no-op: PASS'");
  L.push_back("");

  // [2..] incremental per-policy commits — accept ONE policy, execute; only
  // that group commits, the rest stay suppressed; no premature terminal.
  int step = 2;
  for (size_t j = 0; j < tgroups.size(); ++j) {
    bool last = (j + 1 == tgroups.size());
    L.push_back("# " + std::to_string(step) + ". accept policy '" +
                tgroups[j].policy + "' + execute: group " +
                std::to_string(tgroups[j].gi) + " commits" +
                (last ? " and the key reconciles (terminal)"
                      : ", earlier suppressed groups stay held"));
    ok(acceptStmt(tgroups[j].policy, k1) + "\n" + executeStmt(k1));
    scalar("C", committedCount(k1));
    eq("C", std::to_string(j + 1),
       "committed groups after " + tgroups[j].policy);
    scalar("KC", keyClaimCount(k1));
    eq("KC", "1", "key_claim bound after first commit");
    // committed groups' ledgers hold the net; not-yet-committed groups' ledgers
    // are still zero.
    for (const std::string &ledger : tgroups[j].ledgers) {
      scalar("V", ledgerSum(ledger));
      eq("V", std::to_string(tr.ledger.at(ledger)),
         "committed ledger " + ledger);
    }
    for (size_t k = j + 1; k < tgroups.size(); ++k)
      for (const std::string &ledger : tgroups[k].ledgers) {
        scalar("V", ledgerSum(ledger));
        eq("V", "0", "suppressed ledger " + ledger);
      }
    scalar("R", reconciledOf(k1));
    eq("R", last ? "t" : "f", "reconciled after " + tgroups[j].policy);
    // A redundant execute at this state re-posts nothing (each group commits at
    // most once).
    if (!last) {
      ok(executeStmt(k1));
      scalar("C2", committedCount(k1));
      eq("C2", std::to_string(j + 1),
         "committed groups after redundant execute");
    }
    L.push_back("echo '  [" + std::to_string(step) + "] " + tgroups[j].policy +
                " commit + suppression: PASS'");
    L.push_back("");
    ++step;
  }

  // [step] no drift on the reconciled key.
  const std::string drift =
      "SELECT count(*) FROM (SELECT idempotency_key FROM postings GROUP BY "
      "idempotency_key HAVING SUM(signed_amount)<>0) x;";
  L.push_back("# " + std::to_string(step) +
              ". reconciliation: the terminal key has no drift");
  scalar("D", drift);
  eq("D", "0", "drift rows on terminal key");
  L.push_back("echo '  [" + std::to_string(step) +
              "] terminal no drift: PASS'");
  L.push_back("");
  ++step;

  // [step] replay after terminal.
  L.push_back("# " + std::to_string(step) +
              ". replay: re-executing the reconciled key is refused");
  expectFail("replay", executeStmt(k1));
  L.push_back("echo '  [" + std::to_string(step) + "] replay refused: PASS'");
  L.push_back("");
  ++step;

  // [step] per-policy accept-once.
  L.push_back("# " + std::to_string(step) +
              ". exactly-once: re-accepting an already-accepted policy is "
              "refused");
  expectFail("already accepted", acceptStmt(tgroups.front().policy, k1));
  L.push_back("echo '  [" + std::to_string(step) +
              "] per-policy accept-once: PASS'");
  L.push_back("");
  ++step;

  // [step] changed-payload claim binding: commit ONE group on a fresh key
  // (which leaves it committed-but-not-terminal, so this needs >1 group), then
  // re-execute the SAME key with a different payload — the recomputed claim
  // differs from the pinned one and is refused with 'claim mismatch'. For N=1
  // the first commit is already terminal, so a re-execute is 'replay' (not a
  // claim mismatch) and this reachable-failure-mode does not exist — skip it
  // rather than assert vacuously.
  std::string bumped;
  for (const PlanInput &in : coordinationPlan.inputs)
    if (in.name != key && sqlType(in.type) == "bigint") {
      bumped = in.name;
      break;
    }
  if (!bumped.empty() && tgroups.size() > 1) {
    L.push_back("# " + std::to_string(step) +
                ". changed payload: a later execute on a committed key with a "
                "different payload fails claim binding");
    ok(acceptStmt(tgroups.front().policy, kc) + "\n" + executeStmt(kc));
    scalar("C", committedCount(kc));
    eq("C", "1", "changed-payload key first commit");
    // The key must be COMMITTED-BUT-NOT-TERMINAL here (only the first of N
    // groups committed), so the re-execute below is refused for the RIGHT
    // reason — the changed-payload claim mismatch — and cannot be a 'replay' of
    // a terminal key (which a premature-terminal regression would produce).
    scalar("R", reconciledOf(kc));
    eq("R", "f", "changed-payload key non-terminal after first commit");
    std::map<std::string, std::string> vmBump = vmFor(kc);
    vmBump[bumped] = std::to_string(tr.inputs.at(bumped).i + 1);
    expectFail("claim mismatch",
               "SELECT " + fn + "(" + positionalArgs(vmBump) + ");");
    L.push_back("echo '  [" + std::to_string(step) +
                "] changed-payload claim mismatch: PASS'");
    L.push_back("");
    ++step;
  }

  // [step] cross-key isolation: an independent key runs its full flow to its
  // own terminal without disturbing the first key's committed state.
  L.push_back("# " + std::to_string(step) +
              ". cross-key isolation: an independent key reconciles on its own "
              "without touching the first key");
  for (const TGroup &t : tgroups)
    ok(acceptStmt(t.policy, k2) + "\n" + executeStmt(k2));
  scalar("R2", reconciledOf(k2));
  eq("R2", "t", "second key reconciled");
  scalar("C2", committedCount(k2));
  eq("C2", std::to_string(tgroups.size()), "second key committed groups");
  scalar("C1", committedCount(k1));
  eq("C1", std::to_string(tgroups.size()), "first key committed groups intact");
  scalar("R1", reconciledOf(k1));
  eq("R1", "t", "first key still reconciled");
  L.push_back("echo '  [" + std::to_string(step) +
              "] cross-key isolation: PASS'");
  L.push_back("");

  L.push_back("echo 'ALL POSTGRES TEMPORAL CHECKS PASSED'");

  std::string out;
  for (auto &l : L)
    out += l + "\n";
  return out;
}

} // namespace neutrino::postgres_detail
