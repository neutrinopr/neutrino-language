//===- postgres_stmt_shell_render_harness.cpp - .td->render->golden proof =//
//
// Renders a migrated PostgreSQL typed-.td node through a GENERATED printer
// handler and compares the bytes to the exact line(s) a byte-faithful golden
// fixture carries. The generated include is selected via -DNODE_INC and the
// node under proof via -DHARNESS_POSTING_IDEMPOTENCY / -DHARNESS_KEY_CLAIM /
// -DHARNESS_COMMITTED_GROUP / -DHARNESS_QUORUM_ACCEPT /
// -DHARNESS_TEMPORAL_ACCEPT / -DHARNESS_IDEMPOTENT_RETURN /
// -DHARNESS_EVIDENCE_CLAIM_COMMENT / -DHARNESS_IDEMPOTENCY_GUARD_COMMENT, so
// the SAME harness runs against:
//   * the COMMITTED PostgresPrinterHandlers.inc -> must MATCH the golden
//   line(s)
//   * a .td-MUTATED regenerated include (a token in the node's Syntax record
//     mutated) -> must NOT match (the mutation changes production output)
// Eleven profiles share this source:
//   * default            -> ProgressFlag: `v_progress := ${value};` (one Line)
//   * POSTING_IDEMPOTENCY -> PostingIdempotency: the fixed three-line
//     `posting_idempotency` INSERT (a `lines` LineGroup — N flat siblings)
//   * KEY_CLAIM          -> KeyClaimInsert: the fixed two-line `key_claim`
//     INSERT (a `lines` LineGroup — N flat siblings)
//   * COMMITTED_GROUP    -> CommittedGroupInsert: the fixed two-line
//     `committed_group` INSERT (a `lines` LineGroup — N flat siblings)
//   * QUORUM_ACCEPT      -> QuorumAcceptInsert: the fixed two-line
//     `quorum_acceptance` INSERT (a `lines` LineGroup — N flat siblings)
//   * TEMPORAL_ACCEPT    -> TemporalAcceptInsert: the fixed two-line temporal
//     `quorum_acceptance` INSERT (a `lines` LineGroup — N flat siblings)
//   * IDEMPOTENT_RETURN  -> IdempotentReturn: the fixed single-line
//     idempotency-guard early return (a 0-operand constant `line`)
//   * EVIDENCE_CLAIM_COMMENT -> EvidenceClaimComment: the fixed single-line
//     evidence-only claim comment (a 0-operand constant `line`)
//   * IDEMPOTENCY_GUARD_COMMENT -> IdempotencyGuardComment: the fixed replay
//     guard banner (a 0-operand constant `line`)
// A minimal PgStmt shim stands in for the backend model, so the harness
// compiles against the generated include ALONE (linking only NeutrinoCodeText)
// — no backend link, so the mutated include's generated_printer::render is the
// one that runs (no ODR tie to the committed handler compiled into the
// backend). This is the PostgreSQL parallel of
// solidity_stmt_shell_render_harness.cpp ().
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CodeText.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <variant>
#include <vector>

namespace neutrino {
namespace postgres_model {
// The unified PostgreSQL registry also emits the disjoint schema carrier into
// this include. Declare its closed shape so PgStmt-focused harness builds still
// compile every model-qualified handler without linking the backend.
struct PgSchemaDecl {
  enum class Kind {
    AuthorizedObserverTable = 0,
    CoordinationStatusTable = 1,
    LedgerBalanceTable = 2,
    PostingIdempotencyTable = 3,
    CommittedGroupTable = 4
  };
  Kind kind;
  std::vector<std::string> operands;
};

// Minimal stand-in for the backend PgStmt: the generated printer include only
// needs the Kind enum (ordinals identical to PostgresTargetNodes.td) and the
// ordered operands the arity-generic projection reads.
struct PgStmt {
  enum class Kind {
    Line = 0,
    Blank,
    Raise,
    Assign,
    If,
    FlatIf,
    StatusWrite,
    LedgerUpsert,
    PostingInsert,
    ProgressFlag,
    PostingIdempotency,
    KeyClaimInsert,
    CommittedGroupInsert,
    QuorumAcceptInsert,
    TemporalAcceptInsert,
    IdempotentReturn,
    EvidenceClaimComment,
    PolicyCaseSelect,
    EffectLedgerComment,
    IdempotencyGuardComment,
    BalancedInvariantComment
  };
  Kind kind;
  std::vector<std::string> operands;
  // The repeated per-item tuples a framed-lines handler projects (one tuple per
  // rendered item line); empty for the scalar-only nodes.
  std::vector<std::vector<std::string>> group;
};
} // namespace postgres_model
} // namespace neutrino

#include NODE_INC // the generated printer handlers (committed or mutated)

using namespace neutrino;

#if defined(HARNESS_POSTING_IDEMPOTENCY)
// : the effectful replay-guard `posting_idempotency` INSERT — a FIXED
// three-line statement whose ${key}/${entry} VALUES are the model operands.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::PostingIdempotency;
static const std::vector<std::string> kOperands = {"p_workflow_key",
                                                   "demo_procedure"};
static const std::vector<std::string> kGoldenLines = {
    "INSERT INTO posting_idempotency(idempotency_key, entry)",
    "VALUES (p_workflow_key, 'demo_procedure')", "ON CONFLICT DO NOTHING;"};
#elif defined(HARNESS_KEY_CLAIM)
// : the temporal-claim `key_claim` INSERT — a FIXED two-line statement
// whose
// ${proc}/${key} VALUES are the model operands; `v_claim` is a literal PL/pgSQL
// variable name owned by the .td template, not an operand.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::KeyClaimInsert;
static const std::vector<std::string> kOperands = {"p_proc", "p_key"};
static const std::vector<std::string> kGoldenLines = {
    "INSERT INTO key_claim(procedure, idempotency_key, execution_claim)",
    "VALUES (p_proc, p_key, v_claim);"};
#elif defined(HARNESS_COMMITTED_GROUP)
// : the temporal-claim `committed_group` INSERT — a FIXED two-line
// statement whose ${proc}/${key}/${ordinal} VALUES are the model operands.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::CommittedGroupInsert;
static const std::vector<std::string> kOperands = {"p_proc", "p_key", "0"};
static const std::vector<std::string> kGoldenLines = {
    "INSERT INTO committed_group(procedure, idempotency_key, group_ordinal)",
    "VALUES (p_proc, p_key, 0);"};
#elif defined(HARNESS_QUORUM_ACCEPT)
// : the quorum-accept `quorum_acceptance` INSERT — a FIXED two-line
// statement whose ${proc}/${key} VALUES are the model operands;
// `p_canonical_claim_hash` and the nested `(SELECT count(DISTINCT o.id) FROM
// unnest(p_observers) o(id))` observer-count subquery are literal template text
// owned by the .td, not operands.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::QuorumAcceptInsert;
static const std::vector<std::string> kOperands = {"p_proc", "p_key"};
static const std::vector<std::string> kGoldenLines = {
    "INSERT INTO quorum_acceptance(procedure, claim_id, canonical_claim_hash, "
    "observer_count)",
    "VALUES (p_proc, p_key, p_canonical_claim_hash, (SELECT count(DISTINCT "
    "o.id) FROM unnest(p_observers) o(id)));"};
#elif defined(HARNESS_TEMPORAL_ACCEPT)
// : the temporal-accept `quorum_acceptance` INSERT — the temporal-rail
// sibling of QuorumAcceptInsert. A FIXED two-line statement whose
// ${proc}/${key} VALUES are the model operands; `p_policy`,
// `p_canonical_claim_hash`, `p_execution_claim` and the nested `(SELECT
// count(DISTINCT o.id) FROM unnest(p_observers) o(id))` observer-count subquery
// are literal template text owned by the .td, not operands.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::TemporalAcceptInsert;
static const std::vector<std::string> kOperands = {"p_proc", "p_key"};
static const std::vector<std::string> kGoldenLines = {
    "INSERT INTO quorum_acceptance(procedure, claim_id, policy, "
    "canonical_claim_hash, execution_claim, observer_count)",
    "VALUES (p_proc, p_key, p_policy, p_canonical_claim_hash, "
    "p_execution_claim, "
    "(SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id)));"};
#elif defined(HARNESS_IDEMPOTENT_RETURN)
// : the idempotency-guard early return — a 0-OPERAND CONSTANT node whose
// whole single fixed `line` is literal target text owned by the .td (no
// operands, no ${...} placeholders). The generated `line`/codetext::Line
// handler renders exactly this one line.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::IdempotentReturn;
static const std::vector<std::string> kOperands = {};
static const std::vector<std::string> kGoldenLines = {
    "RETURN;  -- already processed; no double posting"};
#elif defined(HARNESS_EVIDENCE_CLAIM_COMMENT)
// : the evidence-only claim comment — a 0-OPERAND CONSTANT node whose whole
// single fixed `line` is literal target text owned by the .td (no operands, no
// ${...} placeholders). The generated `line`/codetext::Line handler renders
// exactly this one line.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::EvidenceClaimComment;
static const std::vector<std::string> kOperands = {};
static const std::vector<std::string> kGoldenLines = {
    "-- Evidence-only: atomically CLAIM the accepted terminal; move NO ledger "
    "value."};
#elif defined(HARNESS_POLICY_CASE)
// : the temporal-accept per-policy resolver `CASE p_policy … END CASE;` — a
// framed-lines node: a FIXED header (`CASE p_policy`), one `WHEN` item line
// repeated ONCE PER declared attestation policy (each projecting its
// [input, observerSet, quorum] tuple), and a FIXED footer (the unknown-policy
// `ELSE RAISE …` guard + `END CASE;`). The per-policy tuples are the model
// `group`; header/footer/item shape are owned by the .td.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::PolicyCaseSelect;
static const std::vector<std::string> kOperands = {};
static const std::vector<std::vector<std::string>> kGroup = {
    {"'attest_primary'", "'observers_primary'", "2"},
    {"'attest_backup'", "'observers_backup'", "3"}};
static const std::vector<std::string> kGoldenLines = {
    "CASE p_policy",
    "WHEN 'attest_primary' THEN v_set := 'observers_primary'; v_m := 2;",
    "WHEN 'attest_backup' THEN v_set := 'observers_backup'; v_m := 3;",
    "ELSE RAISE EXCEPTION 'unknown attestation policy %', p_policy;",
    "END CASE;"};
#elif defined(HARNESS_EFFECT_LEDGER_COMMENT)
//  C1: the per-effect ledger comment header
// `-- <kind> <name> (<ledger>)<suffix>` — a projected `line` whose
// ${kind}/${name}/${ledger} are dense operands and ${suffix} is the
// already-decided guard clause (empty, or " when <guardSql>"), computed
// upstream and carried verbatim. The node never branches on the suffix.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::EffectLedgerComment;
static const std::vector<std::string> kOperands = {"credit", "settle_fee",
                                                   "escrow", " when v_ok"};
static const std::vector<std::string> kGoldenLines = {
    "-- credit settle_fee (escrow) when v_ok"};
#elif defined(HARNESS_IDEMPOTENCY_GUARD_COMMENT)
//  C2: the replay/idempotency guard banner is a 0-OPERAND CONSTANT node;
// the complete line is fixed syntax owned by the .td record.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::IdempotencyGuardComment;
static const std::vector<std::string> kOperands = {};
static const std::vector<std::string> kGoldenLines = {
    "-- idempotency guard (replay-safe): one row per workflow key"};
#elif defined(HARNESS_BALANCED_INVARIANT_COMMENT)
//  C3: the balanced-workflow invariant banner is a 0-OPERAND CONSTANT
// node; the complete line is fixed syntax owned by the .td record.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::BalancedInvariantComment;
static const std::vector<std::string> kOperands = {};
static const std::vector<std::string> kGoldenLines = {
    "-- balanced invariant: this workflow key must net to zero"};
#else
// : the temporal per-(key,group) progress-flag assign `v_progress :=
// ${value};` with the CLOSED boolean literal operand {true,false}.
static const postgres_model::PgStmt::Kind kKind =
    postgres_model::PgStmt::Kind::ProgressFlag;
static const std::vector<std::string> kOperands = {"false"};
static const std::vector<std::string> kGoldenLines = {"v_progress := false;"};
#endif

// The per-item tuples are only meaningful for the framed-lines profile; every
// other profile renders from scalar operands and leaves the group empty.
#if !defined(HARNESS_POLICY_CASE)
static const std::vector<std::vector<std::string>> kGroup = {};
#endif

static std::string trim(const std::string &s) {
  size_t b = s.find_first_not_of(" \t\r\n");
  if (b == std::string::npos)
    return "";
  size_t e = s.find_last_not_of(" \t\r\n");
  return s.substr(b, e - b + 1);
}

// Split a rendered/golden blob into its ordered, trimmed, NON-EMPTY lines.
static std::vector<std::string> nonEmptyLines(const std::string &text) {
  std::vector<std::string> out;
  std::istringstream ls(text);
  std::string line;
  while (std::getline(ls, line)) {
    std::string t = trim(line);
    if (!t.empty())
      out.push_back(t);
  }
  return out;
}

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: postgres-stmt-shell-render <golden.sql>\n");
    return 2;
  }

  // Render the production statement through the GENERATED handler. A Lines node
  // returns a LineGroup (N flat siblings); Document::print owns every
  // structural newline, so validate() stays clean (no embedded newline in any
  // line).
  postgres_model::PgStmt s{kKind, kOperands, kGroup};
  codetext::Document doc;
  doc.add(postgres_model::generated_printer::render(s));
  if (!doc.validate().empty()) {
    fprintf(stderr, "render-harness: document malformed: %s\n",
            doc.validate().c_str());
    return 2;
  }
  std::string renderedText = doc.print();
  printf("rendered=[%s]\n", renderedText.c_str());
  std::vector<std::string> rendered = nonEmptyLines(renderedText);

  // The byte-faithful golden fixture must carry EVERY expected line, so the
  // comparison pins the generated grammar to real output (not a private
  // string). Absence is a VACUOUS harness, not a pass.
  std::ifstream in(argv[1]);
  std::stringstream ss;
  ss << in.rdbuf();
  std::vector<std::string> goldenLines = nonEmptyLines(ss.str());
  for (const std::string &exp : kGoldenLines) {
    bool found = false;
    for (const std::string &gl : goldenLines)
      if (gl == exp)
        found = true;
    if (!found) {
      fprintf(stderr,
              "render-harness VACUOUS: golden %s no longer carries [%s]\n",
              argv[1], exp.c_str());
      return 2;
    }
  }

  // Exit 0 iff the generated handler reproduces the golden line(s) exactly.
  if (rendered != kGoldenLines) {
    fprintf(stderr,
            "render does not match the golden line(s):\n"
            "  rendered: [%s]\n",
            renderedText.c_str());
    return 1;
  }
  return 0;
}
