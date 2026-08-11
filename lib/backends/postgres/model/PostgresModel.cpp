//===- PostgresModel.cpp - PostgreSQL projection adapter + renderer -------===//
//
// Traverses the verified, domain-blind BackendProjectionGraph and materializes
// target idioms into a typed PgProcedure. The renderer performs layout only.
// This file has no coordination/spec/L2 intake or compatibility fallback entry.
// The coordination constructs are typed (Raise/Assign/If/FlatIf/StatusWrite,
// the LedgerUpsert/PostingInsert effect DML, typed params); only the
// SECURITY-REVIEWED M-of-N quorum guard (accept_<proc>) is reproduced
// BYTE-FOR-BYTE from the reviewed reference — the model carries the reviewed
// guard, it does not diverge from it. Output is byte-identical to the pre-split
// renderer (the PG goldens prove it). Consumes only the typed coordination
// leaf, never View.h.
//
//===----------------------------------------------------------------------===//

#include "PostgresModel.h"

#include "Neutrino/BackendProjectionDriver.h"
#include "PgSqlSyntax.h"
#include "PgSqlText.h"

#include "Neutrino/Attestation.h"
#include "Neutrino/BackendProjection.h"
#include "Neutrino/Expr.h"
#include "Neutrino/ValueModel.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/Error.h"

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

#include "PostgresPrinterHandlers.inc"

// : the generated recipe node builders (construction dispatch + per-node
// emit entries). Construction is generated, not handwritten; the census
// recognizes it by this file's registered generated-output provenance. The
// completed-recipe-root renderer (NEUTRINO_PG_DEFINE_RENDERER) is no longer
// requested here —  relocated the whole render/materialize orchestration to
// the recipe-provider TU; this model only builds the typed PgProcedure.
#include "PostgresRecipeBuilders.inc"

// : the evidence-idiom recipe provider entry + the finalized-value inputs
// it consumes. computeEvidenceInputs (below) synthesizes those inputs here,
// where the finalized-value helpers live.
#include "PostgresEvidenceInputs.h"

using namespace llvm;

namespace neutrino {
namespace postgres_model {

using postgres_detail::sqlEsc;
using postgres_detail::sqlQuote;
using postgres_detail::sqlType;

pgddl::RawSql renderSchemaDecl(const pgddl::DdlCap &cap,
                               const PgSchemaDecl &declaration) {
  codetext::Document document;
  document.add(generated_printer::render(declaration));
  return pgddl::rawSql(cap, document.print(""));
}

// The single failure site — one throw, so the  throw-debt ratchet stays
// honest as fail-closed checks are added. `code` is the taxonomy diagnostic.
[[noreturn]] void fail(const char *code, const std::string &msg) {
  throw ExprError(code, msg);
}

namespace {

//  G1-S1: spell a coordination_status role by CONSUMING the projected
// (mode, role) — the legalizer names only the ROLE its site needs; the
// execution MODE comes from the verified projection (never re-derived here),
// and the atom comes from the generated idiom table. This is the ONLY way a
// legalizer obtains a status atom, so no rail selects a lowering family
// locally. A role the projection did not emit fails closed (an unmapped marker
// the goldens reject).
std::string projectedStatusAtom(const projection::BackendProjectionGraph &proj,
                                projection::LifecycleRole role) {
  for (const projection::ProjectedLifecycleRole &r :
       proj.projectedLifecycleRoles)
    if (r.role == role)
      return pgStatusAtom(r.mode, role);
  return "<no-projected-role>"; // fail closed
}

// The reviewed  coordination-envelope SQL (neu_frame + neu_execution_claim),
// embedded verbatim from the reference (a domain-framed SHA-256, byte-identical
// to lib/spec-contract/CoordinationEnvelope.cpp — verified against the committed
// cross-impl vector). A temporal per-policy coordination emits it so the
// procedure recomputes the execution claim in-database and binds it to the
// accepted claim. The framing is the reviewed reference's, not the renderer's;
// the schema golden pins these bytes — do not edit them here.
const char *const kCoordinationEnvelopeSql =
#include "CoordinationEnvelope.sql.inc"
    ;

// A ledger-delta operand as the coordinationPlan carries it ("kind:value") ->
// the SAME SQL operandSql produces from the spec operand object: a literal is a
// quoted SQL string, a ref is p_<input> (a declared input) or v_<compute>.
std::string operandSqlOf(const std::string &id,
                         const std::set<std::string> &inputs) {
  size_t c = id.find(':');
  std::string kind = id.substr(0, c == std::string::npos ? id.size() : c);
  std::string value = c == std::string::npos ? std::string() : id.substr(c + 1);
  if (kind == "literal")
    return sqlQuote(value);
  return (inputs.count(value) ? "p_" : "v_") + value;
}

// The reviewed accept_ REVOKE trailer (): Postgres grants EXECUTE to PUBLIC
// by default and observer ids are not secret, so a PUBLIC-callable accept_ is
// forgeable — REVOKE it (fail-safe). Verbatim reviewed reference.
// ( slice 2) returns a fail-closed RawSql; DdlCap proves an authorized
// caller.
pgddl::RawSql quorumAcceptRevoke(const pgddl::DdlCap &cap,
                                 const std::string &name,
                                 const std::string &keyType) {
  auto R = [&](std::string s) { return pgddl::rawSql(cap, std::move(s)); };
  return R("\n-- Admission control (): accept_ is the quorum guard. "
           "Postgres "
           "grants EXECUTE to PUBLIC\n-- by default and the observer ids are "
           "not "
           "secret, so a PUBLIC-callable accept_ is forgeable.\n-- REVOKE it "
           "(no-access-by-default / fail-safe); the deployer MUST then GRANT "
           "it "
           "to "
           "ONLY the\n-- off-chain aggregator role, e.g.:  GRANT EXECUTE ON "
           "FUNCTION accept_") +
         R(name) + R("(") + R(keyType) +
         R(", text, text[]) TO <aggregator_role>;\nREVOKE EXECUTE ON FUNCTION "
           "accept_") +
         R(name) + R("(") + R(keyType) + R(", text, text[]) FROM PUBLIC;\n");
}

// The M-of-N acceptance model bound from the coordination's single attestation
// policy (fail closed on multiple policies / unsupported canonicalization).
struct QuorumBinding {
  int quorumM = 0;
  std::string observerSet;
};

const projection::PostingValueProjection &
postingValues(const projection::TypedValueProjection &values,
              size_t effectIndex) {
  const auto posting =
      llvm::find_if(values.postings, [&](const auto &candidate) {
        return candidate.effectIndex == static_cast<int>(effectIndex);
      });
  if (posting == values.postings.end())
    fail("spec.ast", "projected posting value binding is missing");
  return *posting;
}

QuorumBinding
bindProjectedQuorum(const projection::FinalizedProjectionSequence &sequence) {
  const projection::AttestationBinding &policy =
      sequence.attestation.policies.front();
  return {policy.threshold, policy.observerSetBinding};
}

std::string keyTypeOf(const projection::TypedValueProjection &values,
                      const std::string &key) {
  for (const auto &in : values.params)
    if (in.name == key)
      return sqlType(in.type);
  fail("spec.ast", "projected instance-key parameter is missing");
}

std::vector<PgParam> paramsOf(const projection::TypedValueProjection &values) {
  std::vector<PgParam> params;
  for (const auto &in : values.params)
    params.push_back({"p_" + in.name, sqlType(in.type)});
  return params;
}

//===----------------------------------------------------------------------===//
// Effectful legalization.
//===----------------------------------------------------------------------===//

//===----------------------------------------------------------------------===//
// Evidence-only legalization.
//===----------------------------------------------------------------------===//

} // namespace

//  endpoint: the raw Line kind is unauthorable regardless of enum spelling.
void PgStmt::ensureAuthorable(Kind k) {
  if (k == Kind::Line)
    fail("postgres.syntax.raw",
         "PgStmt: raw Line statement authoring is prohibited; build a typed "
         "PostgresTargetNodes.td node instead");
}

bool PgStmt::rejectsAtConstructionForTest(Kind k) {
  try {
    (void)PgStmt(k, {}, {}, {}, false, {}, {});
  } catch (const ExprError &) {
    return true;
  }
  return false;
}

namespace {

// The reviewed M-of-N quorum acceptance guard `accept_<proc>` (Oracle S2d,
// ), shared by the effectful coordination and the evidence-only lowering
// () so both rails gate on the SAME admission logic. Reproduced byte-for-
// byte from the reviewed reference: records that >= M DISTINCT AUTHORIZED
// observers attested the SAME canonical claim, at most once; fail closed on
// unauthorized/duplicate/<M/replay.
PgFunction buildQuorumAcceptGate(const std::string &name,
                                 const std::string &pkey,
                                 const std::string &keyType,
                                 const std::string &observerSet, int quorumM) {
  PgFunction gate;
  gate.name = "accept_" + name;
  gate.params = {{pkey, keyType},
                 {"p_canonical_claim_hash", "text"},
                 {"p_observers", "text[]"}};
  std::string proc = sqlQuote(name);
  gate.body = std::vector<PgStmt>{
      PgStmt::ifThen(
          "EXISTS (SELECT 1 FROM quorum_acceptance WHERE claim_id = " + pkey +
              " AND procedure = " + proc + ")",
          {PgStmt::raise("already accepted")}),
      PgStmt::ifThen(
          "EXISTS (SELECT 1 FROM unnest(p_observers) o(id) WHERE NOT EXISTS "
          "(SELECT 1 FROM authorized_observer a WHERE a.observer_set = " +
              sqlQuote(observerSet) + " AND a.observer_id = o.id))",
          {PgStmt::raise("unauthorized observer")}),
      PgStmt::ifThen("(SELECT count(*) FROM unnest(p_observers)) <> (SELECT "
                     "count(DISTINCT o.id) FROM unnest(p_observers) o(id))",
                     {PgStmt::raise("duplicate observer")}),
      PgStmt::ifThen(
          "(SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id)) < " +
              std::to_string(quorumM),
          {PgStmt::raise("quorum not met")}),
      PgStmt::quorumAcceptInsert(proc, pkey)};
  return gate;
}

// : `materializeEvidenceIdiom` retired — the evidence rail is lowered by
// the declarative recipe (postgres.evidence.procedure.v1) through the
// registered PostgreSQL recipe provider. Its construction authority now lives
// in the generated recipe adapter + the package-local  security resolvers;
// the call site synthesizes the finalized inputs via `computeEvidenceInputs`.

//===----------------------------------------------------------------------===//
// Temporal per-policy legalization ( activation).
//===----------------------------------------------------------------------===//

// The declared inputs, sorted by name (unique), rendered as the SQL arrays the
//  execution claim is recomputed over: names, category names, and value
// expressions (a numeric input is cast ::text to its decimal minor-units
// string; a symbolic one is the p_<name> text). The claim's workflow-key arg is
// p_<key>.
struct ClaimArrays {
  std::string identity, names, cats, vals;
};
ClaimArrays
buildClaimArrays(const projection::ExecutionIdentity &executionIdentity,
                 const projection::TypedValueProjection &values) {
  ClaimArrays c;
  c.identity = executionIdentity.coordinationIdentity;
  // The execution-claim identity remains  authority: retain the normalized
  // projected name/type ordering while validating each runtime binding
  // against 's typed projection.
  std::vector<projection::ExecutionClaimInput> sorted =
      executionIdentity.claimInputs;
  std::stable_sort(
      sorted.begin(), sorted.end(),
      [](const auto &a, const auto &b) { return a.name < b.name; });
  std::string n, ca, v;
  for (size_t i = 0; i < sorted.size(); ++i) {
    const auto projected = llvm::find_if(values.params, [&](const auto &param) {
      return param.name == sorted[i].name;
    });
    if (projected == values.params.end() || projected->name != sorted[i].name)
      fail("spec.ast", "projected execution-claim binding is missing");
    ValueCategory cat = classifyValueType(sorted[i].type);
    std::string sep = (i + 1 < sorted.size() ? ", " : "");
    n += sqlQuote(sorted[i].name) + sep;
    ca += sqlQuote(categoryName(cat).str()) + sep;
    v += (isNumericCategory(cat) ? "(p_" + sorted[i].name + ")::text"
                                 : "p_" + sorted[i].name) +
         sep;
  }
  c.names = "ARRAY[" + n + "]::text[]";
  c.cats = "ARRAY[" + ca + "]::text[]";
  c.vals = "ARRAY[" + v + "]::text[]";
  return c;
}

CoordinationPlan
projectedPolicyCarrier(const projection::AttestationProjection &att) {
  CoordinationPlan carrier;
  for (const projection::AttestationBinding &binding : att.policies) {
    AttestationPolicy policy;
    policy.input = binding.inputBinding;
    policy.quorum = binding.threshold;
    policy.observerSet = binding.observerSetBinding;
    carrier.attestations.push_back(std::move(policy));
  }
  return carrier;
}

// The temporal M-of-N accept gate: PER-POLICY (accept_<proc>(key, p_policy,
// ...)) so each declared policy's quorum admits independently. It CO-RECORDS
// the  executionClaim alongside the canonical claim (the Solidity guard's
// acceptedExecutionClaim analogue), so execute_ can bind a group's commit to
// the exact accepted payload.
PgFunction buildTemporalAcceptGate(const CoordinationPlan &coordinationPlan,
                                   const std::string &name,
                                   const std::string &pkey,
                                   const std::string &keyType) {
  PgFunction gate;
  gate.name = "accept_" + name;
  gate.params = {{pkey, keyType},
                 {"p_policy", "text"},
                 {"p_canonical_claim_hash", "text"},
                 {"p_execution_claim", "text"},
                 {"p_observers", "text[]"}};
  gate.declare = true;
  gate.declarations = {{"v_set", "text", ""}, {"v_m", "int", ""}};
  std::string proc = sqlQuote(name);
  std::vector<PgStmt> body;
  // Resolve the policy's observer set + threshold M (per-policy config, baked
  // from the coordination's attestation policies — the deployment seeds the
  // members). The `CASE p_policy … END CASE;` frame is a typed framed-lines
  // node
  // (): the header/footer/item SHAPE is owned by PostgresTargetNodes.td;
  // here we supply one already-lowered [input, observerSet, quorum] tuple per
  // declared policy (byte-identical to the retired per-line pgLine sites).
  std::vector<std::vector<std::string>> policyTuples;
  for (const AttestationPolicy &p : coordinationPlan.attestations)
    policyTuples.push_back(
        {sqlQuote(p.input), sqlQuote(p.observerSet), std::to_string(p.quorum)});
  body.push_back(PgStmt::policyCaseSelect(std::move(policyTuples)));
  body.push_back(PgStmt::ifThen(
      "EXISTS (SELECT 1 FROM quorum_acceptance WHERE claim_id = " + pkey +
          " AND procedure = " + proc + " AND policy = p_policy)",
      {PgStmt::raise("already accepted")}));
  body.push_back(PgStmt::ifThen(
      "EXISTS (SELECT 1 FROM unnest(p_observers) o(id) WHERE NOT EXISTS "
      "(SELECT "
      "1 FROM authorized_observer a WHERE a.observer_set = v_set AND "
      "a.observer_id = o.id))",
      {PgStmt::raise("unauthorized observer")}));
  body.push_back(PgStmt::ifThen("(SELECT count(*) FROM unnest(p_observers)) <> "
                                "(SELECT count(DISTINCT o.id) FROM "
                                "unnest(p_observers) o(id))",
                                {PgStmt::raise("duplicate observer")}));
  body.push_back(PgStmt::ifThen(
      "(SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id)) < v_m",
      {PgStmt::raise("quorum not met")}));
  body.push_back(PgStmt::temporalAcceptInsert(proc, pkey));
  gate.body = std::move(body);
  return gate;
}

// The temporal accept_ REVOKE trailer (its signature carries the extra p_policy
// / p_execution_claim params).
// ( slice 2) returns a fail-closed RawSql; DdlCap proves an authorized
// caller.
pgddl::RawSql temporalAcceptRevoke(const pgddl::DdlCap &cap,
                                   const std::string &name,
                                   const std::string &keyType) {
  auto R = [&](std::string s) { return pgddl::rawSql(cap, std::move(s)); };
  return R("\n-- Admission control (): accept_ is the per-policy quorum "
           "guard — "
           "REVOKE from PUBLIC\n-- (no-access-by-default); the deployer GRANTs "
           "it "
           "only to the aggregator role.\nREVOKE EXECUTE ON FUNCTION accept_") +
         R(name) + R("(") + R(keyType) +
         R(", text, text, text, text[]) FROM PUBLIC;\n");
}

struct PostgresTemporalBindings {
  projection::AttestationProjection attestation;
  std::vector<std::string> groupPolicies;
};

PostgresTemporalBindings finalizedPostgresTemporalBindings(
    const projection::FinalizedProjectionSequence &sequence) {
  PostgresTemporalBindings out;
  out.attestation = sequence.attestation;
  for (const projection::FinalizedEffectGroupProjection &group :
       sequence.effectGroups)
    out.groupPolicies.push_back(group.guard.policyInputBinding);
  return out;
}

} // namespace

// : synthesize the evidence procedure's decided target VALUES from the
// verified projection at the finalized-value boundary (the
// computeEvidenceContractInputs analog). Applies the exact same lowerings the
// retired materializeEvidenceIdiom did (sqlQuote, keyTypeOf,
// bindProjectedQuorum, projectedStatusAtom, the `p_`/`execute_` prefixes, the
// NOT EXISTS predicate) — but constructs NO target node; only already-lowered
// strings the recipe binds.
EvidenceProcedureInputs
computeEvidenceInputs(const projection::FinalizedProjectionSequence &sequence) {
  const projection::BackendProjectionGraph &proj = *sequence.graph;
  const projection::ExecutionIdentity &exec = proj.executionIdentities.front();
  const std::string name = exec.procedureNamespace;
  const std::string pkey = "p_" + exec.replayKey;
  const std::string proc = sqlQuote(name);
  const QuorumBinding q = bindProjectedQuorum(sequence);
  const projection::TypedValueProjection &values = sequence.values;

  EvidenceProcedureInputs in;
  in.name = name;
  in.executeName = "execute_" + name;
  in.procLiteral = proc;
  in.key = pkey;
  in.keyType = keyTypeOf(values, exec.replayKey);
  in.observerSet = q.observerSet;
  in.quorumM = std::to_string(q.quorumM);
  in.quorumPredicate = "NOT EXISTS (SELECT 1 FROM quorum_acceptance WHERE "
                       "claim_id = " +
                       pkey + " AND procedure = " + proc + ")";
  in.replayPredicate = "NOT FOUND";
  in.statusAtom = projectedStatusAtom(proj, projection::LifecycleRole::Success);
  uint64_t ordinal = 0;
  for (const projection::TypedParamProjection &p : values.params)
    in.params.push_back({"p_" + p.name, sqlType(p.type), ordinal++});
  return in;
}

//  package-local security resolvers: the recipe provider invokes these
// during typed node construction to obtain the reviewed  PG-QUORUM-SINGLE
// gate and its REVOKE trailer. They are the sole seam the provider crosses to
// the reviewed primitives — whose bodies stay unmoved in this TU — so the
// evidence recipe orders gate -> execute -> revoke declaratively while the
// security-critical generation stays the exact reviewed carve-out.
PgFunction resolveQuorumGate(const std::string &name, const std::string &pkey,
                             const std::string &keyType,
                             const std::string &observerSet, int quorumM) {
  return buildQuorumAcceptGate(name, pkey, keyType, observerSet, quorumM);
}

pgddl::RawSql resolveQuorumRevoke(const pgddl::DdlCap &cap,
                                  const std::string &name,
                                  const std::string &keyType) {
  return quorumAcceptRevoke(cap, name, keyType);
}

// : synthesize the temporal procedure's decided target VALUES from the
// verified projection at the finalized-value boundary. Applies the EXACT same
// lowerings the retired materializeTemporalIdiom did (reusing the file-local
// helpers) so the recipe renders byte-identical SQL — but constructs NO target
// node; only already-lowered strings + the DECLARE block the recipe binds.
TemporalProcedureInputs
computeTemporalInputs(const projection::FinalizedProjectionSequence &sequence) {
  const projection::BackendProjectionGraph &proj = *sequence.graph;
  const projection::ExecutionIdentity &exec = proj.executionIdentities.front();
  const std::string name = exec.procedureNamespace;
  const PostgresTemporalBindings bindings =
      finalizedPostgresTemporalBindings(sequence);
  const projection::TypedValueProjection &values = sequence.values;

  std::set<std::string> inputNames, computeNames;
  for (const auto &in : values.params)
    inputNames.insert(in.name);
  for (const auto &pc : values.computes)
    computeNames.insert(pc.name);
  Resolver resolve = [inputNames, computeNames](StringRef n) -> std::string {
    std::string s = n.str();
    if (inputNames.count(s))
      return "p_" + s;
    if (computeNames.count(s))
      return "v_" + s;
    return s;
  };

  const std::string key = exec.replayKey;
  const std::string pkey = "p_" + key;
  const std::string statusSuccess =
      projectedStatusAtom(proj, projection::LifecycleRole::Success);
  const std::string proc = sqlQuote(name);
  const std::string keyType = keyTypeOf(values, key);
  ClaimArrays ca = buildClaimArrays(exec, values);
  auto committed = [&](size_t gi) {
    return "EXISTS (SELECT 1 FROM committed_group WHERE procedure = " + proc +
           " AND idempotency_key = " + pkey +
           " AND group_ordinal = " + std::to_string(gi) + ")";
  };

  TemporalProcedureInputs t;
  t.name = name;
  t.executeName = "execute_" + name;
  t.proc = proc;
  t.key = pkey;
  t.rawKey = key;
  t.keyType = keyType;
  t.statusSuccess = statusSuccess;
  t.replayPredicate =
      "EXISTS (SELECT 1 FROM coordination_status WHERE idempotency_key = " +
      pkey + " AND procedure = " + proc + " AND " + statusSuccess + ")";
  t.claimVar = "v_claim";
  t.claimExpr = "neu_execution_claim(" + sqlQuote(ca.identity) + ", " + pkey +
                ", " + ca.names + ", " + ca.cats + ", " + ca.vals + ")";
  t.claimMismatchPredicate =
      "EXISTS (SELECT 1 FROM key_claim WHERE procedure = " + proc +
      " AND idempotency_key = " + pkey + " AND execution_claim <> v_claim)";
  t.keyClaimPredicate =
      "v_progress AND NOT EXISTS (SELECT 1 FROM key_claim WHERE procedure = " +
      proc + " AND idempotency_key = " + pkey + ")";
  t.balancePredicate =
      "(SELECT COALESCE(SUM(signed_amount), 0) FROM postings WHERE procedure "
      "= " +
      proc + " AND idempotency_key = " + pkey + ") <> 0";

  uint64_t ordinal = 0;
  for (const projection::TypedParamProjection &p : values.params)
    t.params.push_back({"p_" + p.name, sqlType(p.type), ordinal++});

  ordinal = 0;
  for (const auto &pc : values.computes)
    t.computes.push_back(
        {"v_" + pc.name, toSql(*pc.expression, resolve), ordinal++});

  std::vector<std::string> doneTerms;
  for (size_t gi = 0; gi < sequence.effectGroups.size(); ++gi) {
    const projection::FinalizedEffectGroupProjection &group =
        sequence.effectGroups[gi];
    const std::string holds =
        "EXISTS (SELECT 1 FROM quorum_acceptance WHERE procedure = " + proc +
        " AND claim_id = " + pkey +
        " AND policy = " + sqlQuote(bindings.groupPolicies[gi]) +
        " AND execution_claim = v_claim)";
    TemporalProcedureInputs::Group g;
    g.holdsPredicate = "(" + holds + ") AND NOT " + committed(gi);
    g.committedOrdinal = std::to_string(gi);
    g.ordinal = gi;
    uint64_t pord = 0;
    for (const projection::LedgerPosting *posting : group.postings) {
      const auto &pv = postingValues(values, posting->effectIndex);
      std::string amount = operandSqlOf(posting->amount, inputNames);
      std::string party = operandSqlOf(posting->party, inputNames);
      std::string currency = operandSqlOf(posting->currency, inputNames);
      std::string signed_ =
          posting->direction == "credit" ? amount : ("-(" + amount + ")");
      TemporalProcedureInputs::Posting p;
      p.negativePredicate = "(" + amount + ") < 0";
      p.negativeMessage = "negative money for " + sqlEsc(posting->name);
      p.ledger = posting->ledger;
      p.party = party;
      p.currency = currency;
      p.signedAmount = signed_;
      p.entry = posting->name;
      p.amount = amount;
      p.memo = pv.memo;
      p.ordinal = pord++;
      g.postings.push_back(std::move(p));
    }
    doneTerms.push_back(committed(gi));
    t.groups.push_back(std::move(g));
  }

  std::string done;
  for (size_t i = 0; i < doneTerms.size(); ++i)
    done += (i ? " AND " : "") + doneTerms[i];
  t.donePredicate = done;

  uint64_t bord = 0;
  for (const projection::BalanceAssertion *assertion :
       sequence.balanceAssertions) {
    (void)assertion;
    t.balances.push_back({bord++});
  }

  t.attestation = bindings.attestation;
  return t;
}

// : synthesize the effectful procedure's decided target VALUES from the
// verified projection at the finalized-value boundary. Applies the EXACT same
// lowerings the retired materializeEffectfulIdiom did (reusing the file-local
// helpers) so the recipe renders byte-identical SQL — but constructs NO target
// node; only already-lowered strings the recipe binds. The reachable variant is
// read from the finalized `attestationKind` (not a backend flag) purely to
// shape the precomposed requirement predicate / quorum operands; the recipe key
// and the optional-slot presence are the finalized facts (owned by the caller /
// read from the sequence in the provider), not this local.
EffectfulProcedureInputs computeEffectfulInputs(
    const projection::FinalizedProjectionSequence &sequence) {
  const projection::BackendProjectionGraph &proj = *sequence.graph;
  const projection::ExecutionIdentity &exec = proj.executionIdentities.front();
  const std::string name = exec.procedureNamespace;
  const projection::TypedValueProjection &values = sequence.values;

  std::set<std::string> inputNames, computeNames;
  for (const auto &in : values.params)
    inputNames.insert(in.name);
  for (const auto &pc : values.computes)
    computeNames.insert(pc.name);
  Resolver resolve = [inputNames, computeNames](StringRef n) -> std::string {
    std::string s = n.str();
    if (inputNames.count(s))
      return "p_" + s;
    if (computeNames.count(s))
      return "v_" + s;
    return s;
  };

  const std::string key = exec.replayKey;
  const std::string pkey = "p_" + key;
  const std::string proc = sqlQuote(name);
  const std::string statusSuccess =
      projectedStatusAtom(proj, projection::LifecycleRole::Success);
  const std::string statusAttest =
      projectedStatusAtom(proj, projection::LifecycleRole::AcceptedOrAttested);

  EffectfulProcedureInputs in;
  in.name = name;
  in.executeName = "execute_" + name;
  in.attestName = "attest_" + name;
  in.proc = proc;
  in.key = pkey;
  in.rawKey = key;
  in.keyType = keyTypeOf(values, key);
  in.statusSuccess = statusSuccess;
  in.statusAttest = statusAttest;
  in.replayPredicate =
      "EXISTS (SELECT 1 FROM coordination_status WHERE idempotency_key = " +
      pkey + " AND procedure = " + proc + " AND " + statusSuccess + ")";
  // Both requirement predicates are precomposed unconditionally; the recipe's
  // WithAttestation / WithoutAttestation arm (finalized attestation fact)
  // selects which one is emitted — no backend Boolean here.
  in.quorumRequirementPredicate =
      "NOT EXISTS (SELECT 1 FROM quorum_acceptance WHERE claim_id = " + pkey +
      " AND procedure = " + proc + ")";
  in.selfRequirementPredicate =
      "NOT EXISTS (SELECT 1 FROM coordination_status WHERE idempotency_key = " +
      pkey + " AND procedure = " + proc + " AND " + statusAttest + ")";
  in.notFoundPredicate = "NOT FOUND";
  in.idempotencyEntry = sqlEsc(name);
  in.balancePredicate =
      "(SELECT COALESCE(SUM(signed_amount), 0) FROM postings WHERE procedure "
      "= " +
      proc + " AND idempotency_key = " + pkey + ") <> 0";
  // The attestation optional-slot presence is a finalized fact; decide the
  // mutually-exclusive extents once here so the render boundary only returns a
  // precomputed value (no backend Boolean lives on the render path).
  const bool withAttestation =
      sequence.attestationKind == projection::FinalizedAttestationKind::Single;
  in.withAttestationExtent = withAttestation ? 1u : 0u;
  in.withoutAttestationExtent = withAttestation ? 0u : 1u;

  uint64_t ordinal = 0;
  for (const projection::TypedParamProjection &p : values.params)
    in.params.push_back({"p_" + p.name, sqlType(p.type), ordinal++});

  ordinal = 0;
  for (const auto &pc : values.computes)
    in.computes.push_back(
        {"v_" + pc.name, toSql(*pc.expression, resolve), ordinal++});

  uint64_t pord = 0;
  for (const projection::FinalizedPostingProjection &finalized :
       sequence.postings) {
    const projection::LedgerPosting *posting = finalized.posting;
    const auto &pv = postingValues(values, posting->effectIndex);
    std::string amount = operandSqlOf(posting->amount, inputNames);
    std::string party = operandSqlOf(posting->party, inputNames);
    std::string currency = operandSqlOf(posting->currency, inputNames);
    std::string signed_ =
        posting->direction == "credit" ? amount : ("-(" + amount + ")");
    // Precompose the (debt) guard VALUE strings from the finalized
    // applicability fact — the guard SQL and its `when <guard>` comment suffix.
    // The optional- slot PRESENCE (whether the leg is flat-IF wrapped) is NOT
    // decided here; the provider reads it from the finalized
    // `posting.guardKind`.
    bool comparisonGuarded = false;
    std::string guardSql;
    projection_driver::visitFinalizedPostingGuard(
        sequence, finalized, [] {},
        [&](const ExprNode &guard) {
          comparisonGuarded = true;
          guardSql = guardToSql(guard, resolve);
        },
        [](const projection::GroupGuardProjection &) {},
        [&] {
          fail("spec.ast",
               "effectful PostgreSQL idiom received an invalid group guard");
        });
    EffectfulProcedureInputs::Posting p;
    p.negativePredicate = "(" + amount + ") < 0";
    p.negativeMessage = "negative money for " + sqlEsc(posting->name);
    p.ledger = posting->ledger;
    p.party = party;
    p.currency = currency;
    p.signedAmount = signed_;
    p.entry = posting->name;
    p.amount = amount;
    p.memo = pv.memo;
    p.direction = posting->direction;
    p.commentSuffix = comparisonGuarded ? (" when " + guardSql) : std::string();
    p.guard = guardSql;
    p.ordinal = pord++;
    in.postings.push_back(std::move(p));
  }

  uint64_t bord = 0;
  for (const projection::BalanceAssertion *assertion :
       sequence.balanceAssertions) {
    (void)assertion;
    in.balances.push_back({bord++});
  }
  return in;
}

//  package-local security resolvers: the recipe provider invokes these
// during typed node construction to obtain the reviewed  PG-QUORUM-TEMPORAL
// per-policy gate and its REVOKE trailer. The per-policy carrier is built here
// (beside the reviewed primitives, whose bodies stay unmoved) from the
// finalized attestation — the recipe/provider path never touches a
// CoordinationPlan.
PgFunction resolveTemporalGate(const std::string &name, const std::string &pkey,
                               const std::string &keyType,
                               const projection::AttestationProjection &att) {
  return buildTemporalAcceptGate(projectedPolicyCarrier(att), name, pkey,
                                 keyType);
}

pgddl::RawSql resolveTemporalRevoke(const pgddl::DdlCap &cap,
                                    const std::string &name,
                                    const std::string &keyType) {
  return temporalAcceptRevoke(cap, name, keyType);
}

//  B3: the reviewed  coordination-envelope exact-body leaf. This
// allowed-consumer TU emits the byte-identical blob (kCoordinationEnvelopeSql,
// #included from the reviewed CoordinationEnvelope.sql.inc); the schema recipe
// only composes it.
pgddl::RawSql resolveSchemaEnvelope(const pgddl::DdlCap &cap) {
  return pgddl::rawSql(cap, std::string(kCoordinationEnvelopeSql));
}

// : `materializePostgresProjection`, `materializePostgresSchema`, and
// `renderPostgresProjection` no longer live in this model TU — they moved to
// the recipe-provider TU (recipe-provider-plumbing). The two materialize
// orchestrators are thin dispatch over the generated `materializeRecipe`
// runtime; the completed-recipe-root renderer only recurses the
// already-composed typed nodes through the generic printer. This model builds
// the typed PgProcedure and composes no rendered output of its own.

} // namespace postgres_model

} // namespace neutrino
