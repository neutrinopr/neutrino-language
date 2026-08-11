//===- postgres_model_test.cpp - typed PostgreSQL legalization model ----===//
//
// Target-model unit test: it asserts on the STRUCTURE graph materialization
// produces (not on printed bytes — the goldens pin those), covering quorum
// gating, the replay/quorum RAISE guards, the balanced obligation, the
// reconciled StatusWrite lifecycle transition, typed parameters, and a nested
// conditional-effect guard. Legalization drives off the CoordinationPlan alone,
// so the model is single-source by construction. Links ONLY
// NeutrinoBackendPostgres, so it doubles as a leaf-boundary proof for the model
// TU.
//
//===----------------------------------------------------------------------===//

#include "PostgresModel.h"

#include "Neutrino/CoordinationPlan.h"

#include "llvm/Support/JSON.h"

#include <cstdio>
#include <fstream>
#include <functional>
#include <sstream>
#include <string>
#include <type_traits>

using namespace neutrino;
using namespace neutrino::postgres_model;

static_assert(!std::is_constructible_v<PgStmt, PgSchemaDecl>,
              "a schema declaration must not construct a procedure statement");
static_assert(!std::is_convertible_v<PgSchemaDecl, PgStmt>,
              "a schema declaration must not inhabit PgFunction::body");
static_assert(static_cast<int>(PgSchemaDecl::Kind::AuthorizedObserverTable) ==
                  0,
              "the first schema node keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::CoordinationStatusTable) ==
                  1,
              "the second schema node keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::LedgerBalanceTable) == 2,
              "the third schema node keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::PostingIdempotencyTable) ==
                  3,
              "the fourth schema node keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::CommittedGroupTable) == 4,
              "the fifth schema node keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::PostingsTable) == 5,
              "the base postings shape keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::PostingsWithMemoTable) == 6,
              "the memo postings shape keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::KeyClaimTable) == 7,
              "the claim-binding shape keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::QuorumAcceptanceTable) == 8,
              "the single-policy quorum shape keeps its registered ordinal");
static_assert(
    static_cast<int>(PgSchemaDecl::Kind::TemporalQuorumAcceptanceTable) == 9,
    "the temporal per-policy quorum shape keeps its registered ordinal");
static_assert(
    static_cast<int>(PgSchemaDecl::Kind::QuorumAcceptanceTemporalPreflight) ==
        10,
    "the temporal quorum-acceptance preflight keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::CommittedGroupPreflight) ==
                  11,
              "the committed-group preflight keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::KeyClaimPreflight) == 12,
              "the key-claim preflight keeps its registered ordinal");
static_assert(static_cast<int>(
                  PgSchemaDecl::Kind::QuorumAcceptanceUpgradePreflight) == 13,
              "the  upgrade preflight keeps its registered ordinal");
static_assert(static_cast<int>(PgSchemaDecl::Kind::Count) == 14,
              "the schema carrier contains exactly the migrated table +  "
              "preflight shapes");

static int failures = 0;
static void check(bool ok, const char *what) {
  if (!ok) {
    fprintf(stderr, "postgres-model-test: FAIL: %s\n", what);
    ++failures;
  }
}

static PgProcedure materializeFile(const char *path) {
  std::ifstream in(path);
  std::stringstream ss;
  ss << in.rdbuf();
  llvm::Expected<llvm::json::Value> j = llvm::json::parse(ss.str());
  if (!j)
    llvm::report_fatal_error("spec is not valid JSON");
  llvm::Expected<CoordinationPlan> coordinationPlan =
      planFromSpec(*j->getAsObject());
  if (!coordinationPlan)
    llvm::report_fatal_error("spec failed coordination-plan normalization");
  llvm::Expected<projection::BackendProjectionGraph> graph =
      projection::projectBackendGraph(*coordinationPlan);
  if (!graph)
    llvm::report_fatal_error("backend projection failed");
  return materializePostgresProjection(*graph);
}

static std::vector<const PgCallableRoot *>
callableRoots(const PgProcedure &procedure) {
  std::vector<const PgCallableRoot *> roots;
  for (const PgProcedurePart &part : procedure.root)
    if (const auto *callable = std::get_if<PgCallableRoot>(&part))
      roots.push_back(callable);
  return roots;
}

static const PgStmt &callablePart(const PgCallableRoot &root,
                                  PgStmt::Kind kind) {
  for (const PgStmt &part : root.parts)
    if (part.kind == kind)
      return part;
  llvm::report_fatal_error("callable root is missing a required typed part");
}

static std::string callableName(const PgCallableRoot &root) {
  const PgStmt &signature = callablePart(root, PgStmt::Kind::CallableSig);
  return signature.operands.empty() ? std::string() : signature.operands[0];
}

// The execute_ callable is the final callable root; its body is a typed
// CallableBody child produced by the recipe.
static const std::vector<PgStmt> &execBody(const PgProcedure &m) {
  return callablePart(*callableRoots(m).back(), PgStmt::Kind::CallableBody)
      .body;
}

// Depth-first search for a statement of `kind` satisfying `pred` (recurses into
// If/FlatIf bodies — where a conditional leg's statements live).
static bool anyStmt(const std::vector<PgStmt> &body, PgStmt::Kind kind,
                    const std::function<bool(const PgStmt &)> &pred) {
  for (const PgStmt &s : body) {
    if (s.kind == kind && pred(s))
      return true;
    if (!s.body.empty() && anyStmt(s.body, kind, pred))
      return true;
  }
  return false;
}

int main(int argc, char **argv) {
  if (argc < 5) {
    fprintf(stderr, "usage: postgres-model-test <attested-balanced-spec> "
                    "<guarded-spec> <temporal-multi-policy-spec> "
                    "<evidence-only-spec>\n");
    return 2;
  }

  // [ C3 endpoint] Raw Line authoring is prohibited by ENUM VALUE at the
  // canonical constructor, closing renamed factories and ordinal/cast bypasses.
  auto guardRejects = [](PgStmt::Kind k) {
    try {
      PgStmt::ensureAuthorable(k);
    } catch (const ExprError &) {
      return true;
    }
    return false;
  };
  check(guardRejects(PgStmt::Kind::Line),
        "ensureAuthorable rejects the retired raw Line kind");
  check(
      guardRejects(static_cast<PgStmt::Kind>(0)),
      "ensureAuthorable rejects the raw Line ordinal independent of spelling");
  check(!guardRejects(PgStmt::Kind::Blank),
        "ensureAuthorable accepts a structured statement kind");
  check(PgStmt::rejectsAtConstructionForTest(PgStmt::Kind::Line),
        "canonical construction rejects the retired raw Line kind");
  check(PgStmt::rejectsAtConstructionForTest(static_cast<PgStmt::Kind>(0)),
        "canonical construction rejects the raw Line ordinal");
  check(!PgStmt::rejectsAtConstructionForTest(PgStmt::Kind::Blank),
        "canonical construction accepts a structured statement kind");

  // (1) An attested + balanced coordination legalizes to a quorum-gated model
  // with accept_<proc> + execute_<proc>, the replay/quorum RAISE guards, the
  // balance-obligation RAISE, and the reconciled StatusWrite — every DECISION
  // legalization made, inspectable without printing.
  PgProcedure gated = materializeFile(argv[1]);
  check(!gated.evidenceOnly, "attested spec is effectful (not evidence-only)");
  check(gated.gated, "attested spec legalizes to a quorum-gated procedure");
  const auto gatedCallables = callableRoots(gated);
  check(gatedCallables.size() == 2,
        "gated procedure has an accept_ gate + execute_");
  check(callableName(*gatedCallables.front()).rfind("accept_", 0) == 0,
        "the first function is the quorum accept_ gate");
  check(std::any_of(gated.root.begin(), gated.root.end(),
                    [](const PgProcedurePart &part) {
                      return std::holds_alternative<PgProcedureRevoke>(part);
                    }),
        "the gated procedure carries the accept_ REVOKE");
  const std::vector<PgStmt> &gb = execBody(gated);
  const PgStmt &executeSig =
      callablePart(*gatedCallables.back(), PgStmt::Kind::CallableSig);
  check(!executeSig.group.empty() && !executeSig.group.front().empty() &&
            executeSig.group.front().front().rfind("p_", 0) == 0,
        "execute_ carries a typed p_-named parameter vector");
  check(anyStmt(gb, PgStmt::Kind::Raise,
                [](const PgStmt &s) { return s.text == "replay"; }),
        "execute_ has the replay RAISE guard");
  check(
      anyStmt(gb, PgStmt::Kind::Raise,
              [](const PgStmt &s) { return s.text == "quorum not accepted"; }),
      "gated execute_ raises on an unaccepted quorum");
  check(anyStmt(gb, PgStmt::Kind::Raise,
                [](const PgStmt &s) {
                  return s.text == "not balanced for %" && !s.aux.empty();
                }),
        "balanced coordination raises the balance-obligation guard");
  // The balance SUM is scoped to THIS coordination (procedure, key): the
  // guard's predicate must filter postings by procedure, so a sibling procedure
  // sharing the raw key cannot cross-contaminate the balance ( identity).
  check(anyStmt(gb, PgStmt::Kind::If,
                [](const PgStmt &s) {
                  // : the guard predicate is operand 0 (projected into the
                  // generated `${cond}`), no longer the node's `text`.
                  const std::string &cond =
                      s.operands.empty() ? s.text : s.operands.front();
                  return cond.find("FROM postings WHERE procedure =") !=
                             std::string::npos &&
                         cond.find("SUM(signed_amount)") != std::string::npos;
                }),
        "the balance sum is procedure-scoped (FROM postings WHERE procedure=)");
  // The effect DML is TYPED, not opaque Line strings: the ledger upsert and the
  // postings insert are their own shapes.
  check(anyStmt(gb, PgStmt::Kind::LedgerUpsert,
                [](const PgStmt &s) {
                  return s.operands.size() == 5 && s.operands[4] == "balance";
                }),
        "an effect leg carries a typed LedgerUpsert shape with its fixed "
        "target column");
  check(anyStmt(gb, PgStmt::Kind::PostingInsert,
                [](const PgStmt &s) { return s.parts.size() == 9; }),
        "an effect leg carries a typed PostingInsert shape");
  check(
      anyStmt(gb, PgStmt::Kind::StatusWrite,
              [](const PgStmt &s) { return s.text == "reconciled" && s.flag; }),
      "execute_ ends in the reconciled StatusWrite (DO UPDATE)");
  // The effectful replay guard is a TYPED PostingIdempotency node (), not
  // three raw Line strings: it carries the workflow key + entry as its two
  // already-lowered operands, and the shared generated printer reproduces the
  // exact three-line `posting_idempotency` INSERT. This binds the node to the
  // real legalization decision — deleting the PgStmt::postingIdempotency(...)
  // effectful idiom construction drops the node here (and its three lines
  // from the generated SQL) and fails this test (the governing tamper).
  std::string pkey, entry;
  check(
      anyStmt(gb, PgStmt::Kind::PostingIdempotency,
              [&](const PgStmt &s) {
                if (s.operands.size() != 2)
                  return false;
                pkey = s.operands[0];
                entry = s.operands[1];
                return true;
              }),
      "execute_ carries a typed PostingIdempotency shape (key,entry operands)");
  const std::string gatedSql = renderPostgresProjection(gated);
  check(gatedSql.find("DO UPDATE SET balance = ledger_balance.balance + (") !=
            std::string::npos,
        "LedgerUpsert renders the byte-stable assignment from its fixed column "
        "shape and finalized signedAmount operand");
  check(gatedSql.find(
            "INSERT INTO posting_idempotency(idempotency_key, entry)") !=
            std::string::npos,
        "generated SQL carries the posting_idempotency INSERT header line");
  check(gatedSql.find("VALUES (" + pkey + ", '" + entry + "')") !=
            std::string::npos,
        "generated SQL carries the posting_idempotency VALUES (key, 'entry') "
        "line built from the node operands");
  check(gatedSql.find("ON CONFLICT DO NOTHING;") != std::string::npos,
        "generated SQL carries the posting_idempotency ON CONFLICT line");
  // The replay guard banner is a typed, zero-operand comment node ( C2),
  // constructed at the legalization site immediately before the typed
  // PostingIdempotency statement. Its complete fixed syntax lives in the .td.
  check(anyStmt(gb, PgStmt::Kind::IdempotencyGuardComment,
                [](const PgStmt &s) { return s.operands.empty(); }),
        "execute_ carries a typed IdempotencyGuardComment shape (0 operands)");
  check(gatedSql.find("-- idempotency guard (replay-safe): one row per "
                      "workflow key") != std::string::npos,
        "generated SQL carries the exact idempotency-guard comment line");
  check(anyStmt(gb, PgStmt::Kind::BalancedInvariantComment,
                [](const PgStmt &s) { return s.operands.empty(); }),
        "balanced execute_ carries a typed BalancedInvariantComment shape "
        "(0 operands)");
  check(gatedSql.find("-- balanced invariant: this workflow key must net to "
                      "zero") != std::string::npos,
        "generated SQL carries the exact balanced-invariant comment line");
  // The idempotency-guard early return is a TYPED IdempotentReturn node (),
  // not a raw Line string: it is a 0-OPERAND CONSTANT node nested inside the
  // effectful `NOT FOUND` guard, and the shared generated `line` printer
  // reproduces the exact fixed line `RETURN;  -- already processed; no double
  // posting` (literal target text, no operands). This binds the node to the
  // real legalization decision — deleting the PgStmt::idempotentReturn()
  // construction inside the NOT FOUND guard drops the node
  // here (and its line from the generated SQL) and fails this test (the
  // governing tamper).
  check(anyStmt(gb, PgStmt::Kind::IdempotentReturn,
                [](const PgStmt &s) { return s.operands.empty(); }),
        "execute_ NOT FOUND guard carries a typed IdempotentReturn shape "
        "(0 operands)");
  check(gatedSql.find("RETURN;  -- already processed; no double posting") !=
            std::string::npos,
        "generated SQL carries the idempotency-guard RETURN early-return line "
        "(exact, incl. the double space after RETURN;)");
  // The quorum-accept `quorum_acceptance` INSERT is a TYPED QuorumAcceptInsert
  // node (), not two raw Line strings: buildQuorumAcceptGate builds the
  // accept_ gate (functions.front()), and the node carries the procedure
  // literal + idempotency key as its two already-lowered operands. The shared
  // generated printer reproduces the exact two-line `quorum_acceptance` INSERT,
  // including the nested observer-count subquery in the VALUES tail (literal
  // template text, not an operand). This binds the node to the real
  // legalization decision — deleting the PgStmt::quorumAcceptInsert(...)
  // construction in buildQuorumAcceptGate drops the node here (and its two
  // lines from the generated SQL) and fails this test (the governing tamper).
  const std::vector<PgStmt> &acceptBody =
      callablePart(*gatedCallables.front(), PgStmt::Kind::CallableBody).body;
  std::string qaProc, qaKey;
  check(anyStmt(acceptBody, PgStmt::Kind::QuorumAcceptInsert,
                [&](const PgStmt &s) {
                  if (s.operands.size() != 2)
                    return false;
                  qaProc = s.operands[0];
                  qaKey = s.operands[1];
                  return true;
                }),
        "accept_ gate carries a typed QuorumAcceptInsert shape (proc,key "
        "operands)");
  check(gatedSql.find("INSERT INTO quorum_acceptance(procedure, claim_id, "
                      "canonical_claim_hash, observer_count)") !=
            std::string::npos,
        "generated SQL carries the quorum_acceptance INSERT header line");
  check(gatedSql.find("VALUES (" + qaProc + ", " + qaKey +
                      ", p_canonical_claim_hash, (SELECT count(DISTINCT o.id) "
                      "FROM unnest(p_observers) o(id)));") != std::string::npos,
        "generated SQL carries the quorum_acceptance VALUES (proc, key, ...) "
        "line built from the node operands, incl. the nested observer-count "
        "subquery");

  // (2) A conditional effect: the model carries a NESTED FlatIf shape — the
  // leg's statements live inside a guarded block — proving guard lowering is a
  // typed shape, not a baked string. This spec is self-attested, so its gate is
  // attest_<proc>.
  PgProcedure guarded = materializeFile(argv[2]);
  check(!guarded.gated, "unattested spec legalizes self-attested (attest_)");
  check(callableName(*callableRoots(guarded).front()).rfind("attest_", 0) == 0,
        "the first function is the attest_ gate");
  check(anyStmt(execBody(guarded), PgStmt::Kind::FlatIf,
                [](const PgStmt &s) { return !s.body.empty(); }),
        "a conditional effect legalizes to a nested FlatIf block");

  // (3) The  temporal per-policy path: projection materialization is where
  // the migrated typed ProgressFlag node is CONSTRUCTED as a production
  // decision — `v_progress := false;` reset before the per-group commit ledger,
  // and `v_progress := true;` inside a committing group's leg. Assert the
  // legalized model carries BOTH closed operand values as typed ProgressFlag
  // statements (the operand is the already-decided literal, not printed bytes).
  // This binds the node to the real legalization decision: deleting either
  // PgStmt::progressFlag(...) call in PostgresModel.cpp drops its value here
  // and fails this test (the non-vacuity governing tamper).
  PgProcedure temporal = materializeFile(argv[3]);
  const std::vector<PgStmt> &tb = execBody(temporal);
  check(anyStmt(tb, PgStmt::Kind::ProgressFlag,
                [](const PgStmt &s) {
                  return s.operands.size() == 1 && s.operands[0] == "false";
                }),
        "temporal legalization emits the v_progress := false reset "
        "(ProgressFlag operand \"false\")");
  check(anyStmt(tb, PgStmt::Kind::ProgressFlag,
                [](const PgStmt &s) {
                  return s.operands.size() == 1 && s.operands[0] == "true";
                }),
        "temporal legalization emits the v_progress := true commit progress "
        "(ProgressFlag operand \"true\")");
  // The temporal-claim `key_claim` INSERT is a TYPED KeyClaimInsert node
  // (), not two raw Line strings: it carries the procedure + idempotency
  // key as its two already-lowered operands, and the shared generated printer
  // reproduces the exact two-line `key_claim` INSERT. This binds the node to
  // the real legalization decision — deleting the PgStmt::keyClaimInsert(...)
  // temporal idiom construction drops the node here (and its two
  // lines from the generated SQL) and fails this test (the governing tamper).
  std::string kcProc, kcKey;
  check(anyStmt(tb, PgStmt::Kind::KeyClaimInsert,
                [&](const PgStmt &s) {
                  if (s.operands.size() != 2)
                    return false;
                  kcProc = s.operands[0];
                  kcKey = s.operands[1];
                  return true;
                }),
        "temporal execute_ carries a typed KeyClaimInsert shape (proc,key "
        "operands)");
  const std::string temporalSql = renderPostgresProjection(temporal);
  check(temporalSql.find("INSERT INTO key_claim(procedure, idempotency_key, "
                         "execution_claim)") != std::string::npos,
        "generated SQL carries the key_claim INSERT header line");
  check(temporalSql.find("VALUES (" + kcProc + ", " + kcKey + ", v_claim);") !=
            std::string::npos,
        "generated SQL carries the key_claim VALUES (proc, key, v_claim) line "
        "built from the node operands");
  // The temporal-claim `committed_group` INSERT is a TYPED CommittedGroupInsert
  // node (), not two raw Line strings: it carries the procedure,
  // idempotency key, and group ordinal as its three already-lowered operands,
  // and the shared generated printer reproduces the exact two-line
  // `committed_group` INSERT. This binds the node to the real legalization
  // decision — deleting the PgStmt::committedGroupInsert(...) construction in
  // temporal idiom materialization drops the node here (and its two lines from
  // generated SQL) and fails this test (the governing tamper).
  std::string cgProc, cgKey, cgOrdinal;
  check(anyStmt(tb, PgStmt::Kind::CommittedGroupInsert,
                [&](const PgStmt &s) {
                  if (s.operands.size() != 3)
                    return false;
                  cgProc = s.operands[0];
                  cgKey = s.operands[1];
                  cgOrdinal = s.operands[2];
                  return true;
                }),
        "temporal execute_ carries a typed CommittedGroupInsert shape "
        "(proc,key,ordinal operands)");
  check(temporalSql.find("INSERT INTO committed_group(procedure, "
                         "idempotency_key, group_ordinal)") !=
            std::string::npos,
        "generated SQL carries the committed_group INSERT header line");
  check(temporalSql.find("VALUES (" + cgProc + ", " + cgKey + ", " + cgOrdinal +
                         ");") != std::string::npos,
        "generated SQL carries the committed_group VALUES (proc, key, ordinal) "
        "line built from the node operands");
  // The temporal-accept `quorum_acceptance` INSERT is a TYPED
  // TemporalAcceptInsert node () — the temporal-rail sibling of
  // QuorumAcceptInsert, not two raw Line strings: buildTemporalAcceptGate
  // builds the temporal accept_ gate (temporal.functions.front()), and the node
  // carries the procedure literal + idempotency key as its two already-lowered
  // operands. The shared generated printer reproduces the exact two-line
  // temporal `quorum_acceptance` INSERT, including the policy + execution_claim
  // columns and the nested observer-count subquery in the VALUES tail (literal
  // template text, not operands). This binds the node to the real legalization
  // decision — deleting the PgStmt::temporalAcceptInsert(...) construction in
  // buildTemporalAcceptGate drops the node here (and its two lines from the
  // generated SQL) and fails this test (the governing tamper).
  const std::vector<PgStmt> &temporalAcceptBody =
      callablePart(*callableRoots(temporal).front(), PgStmt::Kind::CallableBody)
          .body;
  std::string taProc, taKey;
  check(anyStmt(temporalAcceptBody, PgStmt::Kind::TemporalAcceptInsert,
                [&](const PgStmt &s) {
                  if (s.operands.size() != 2)
                    return false;
                  taProc = s.operands[0];
                  taKey = s.operands[1];
                  return true;
                }),
        "temporal accept_ gate carries a typed TemporalAcceptInsert shape "
        "(proc,key operands)");
  check(temporalSql.find(
            "INSERT INTO quorum_acceptance(procedure, claim_id, policy, "
            "canonical_claim_hash, execution_claim, observer_count)") !=
            std::string::npos,
        "generated SQL carries the temporal quorum_acceptance INSERT header "
        "line");
  check(
      temporalSql.find("VALUES (" + taProc + ", " + taKey +
                       ", p_policy, p_canonical_claim_hash, p_execution_claim, "
                       "(SELECT count(DISTINCT o.id) FROM unnest(p_observers) "
                       "o(id)));") != std::string::npos,
      "generated SQL carries the temporal quorum_acceptance VALUES (proc, key, "
      "...) line built from the node operands, incl. p_policy / "
      "p_execution_claim and the nested observer-count subquery");

  // (4) An evidence-only coordination materializes through its projected idiom.
  // fixed evidence-only claim comment is a TYPED EvidenceClaimComment node
  // (), not a raw Line string: a 0-OPERAND CONSTANT node whose whole single
  // fixed line is literal target text, and the shared generated `line` printer
  // reproduces the exact banner `-- Evidence-only: atomically CLAIM the
  // accepted terminal; move NO ledger value.`. This binds the node to the real
  // legalization decision — deleting the PgStmt::evidenceClaimComment()
  // evidence idiom construction drops the node here (and its line from the
  // generated SQL) and fails this test (the governing tamper).
  PgProcedure evidence = materializeFile(argv[4]);
  check(evidence.evidenceOnly,
        "evidence-only spec legalizes to an evidence-only procedure");
  const std::vector<PgStmt> &evBody = execBody(evidence);
  check(anyStmt(evBody, PgStmt::Kind::EvidenceClaimComment,
                [](const PgStmt &s) { return s.operands.empty(); }),
        "evidence-only execute_ carries a typed EvidenceClaimComment shape "
        "(0 operands)");
  const std::string evidenceSql = renderPostgresProjection(evidence);
  check(evidenceSql.find("-- Evidence-only: atomically CLAIM the accepted "
                         "terminal; move NO ledger value.") !=
            std::string::npos,
        "generated SQL carries the evidence-only claim comment line (exact)");

  if (failures == 0)
    puts("postgres-model-test OK (typed legalization model: quorum gating, "
         "replay/quorum RAISE, balanced, reconciled StatusWrite, typed params, "
         "nested guard, temporal ProgressFlag false/true, typed idempotency "
         "guard and evidence-only comments, coordination-plan-only single "
         "source)");
  return failures == 0 ? 0 : 1;
}
