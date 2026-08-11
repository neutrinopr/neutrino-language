//===- solidity_recipe_render_referee.cpp -  R5b A.1 render referee ---===//
//
// A dialect-free REFEREE for the Solidity recipe provider's finalized-view trio
// project() / slotExtent() / slotItemOrder() (SolidityRecipeProvider.cpp).
//
// R5b will retire those three handwritten overrides to generated dispatch — a
// byte-affecting change whose mandated referee is "one representative byte
// render at the changed seam." But no prior dialect-free test exercised them:
// the smoke test + SolidityTarget render via the legacy GenSoliditySpec leaf
// path, and the provider unit test only drives guard-consumer literal builders.
// The trio is reachable only as anon-namespace TargetRecipeProvider overrides
// invoked by the shared RecipeInterpreter (executeRecipe / materializeRecipe in
// NeutrinoRecipe).
//
// This harness builds each fixture through assemblePlan — the ONE normalization
// + verification seam production uses (dialect-free: NeutrinoSpecContract links
// only MLIRSupport, and is already transitively linked here). So the referee
// drives the provider off LEGITIMATE, verified CoordinationPlans, not
// hand-assembled ones that could bypass the declared-input / balanced-group /
// binding checks: every effect operand references a DECLARED input, so nothing
// renders as a canonical `input:N` label, and every balanced group provably
// conserves value. The verified plan is projected (projectBackendGraph -> the
// closed graph verifier -> consumeFinalizedProjectionSequence), then the REAL
// provider is driven through the shared interpreter via the already-exposed
// materialize*ContractRecipe entry points. Those call materializeRecipe, which
// walks the generated recipe module and invokes the provider's
// project/slotExtent/slotItemOrder to project every finalized field, resolve
// every slot extent, and order every repeated slot. The resulting
// SolidityContract is rendered to bytes via renderSolidityProjection, and the
// concatenated render is compared to a committed, deterministic golden.
//
// Before comparing, a leak guard (findInvalidIdentifier) rejects any render
// carrying a canonical projection label as an invalid Solidity identifier — so
// the pinned golden A.2 byte-proves against can only ever be valid, compilable
// Solidity, never the `u_input:N` residue a plan that bypassed assemblePlan
// leaks.
//
// It exercises the trio's arms across four verified sequences:
//   * evidence + params  — the evidenceParams vector AND the  instance-key
//                          sub-read (name projected iff ordinal == the finalized
//                          instanceKeyParam's ordinal).
//   * effectful/atomic   — params, a compute + its expression leaf, ledger
//                          postings, an atomic-refuse effect group, group-posting
//                          navigation, semantic ordinals.
//   * effectful/guarded  — [] the SOURCE-NEUTRAL comparison-guard witness:
//                          unattested balanced pairs carrying an equality and a
//                          relational `when` comparison guard, so the
//                          PresenceGuard optional slot fires and the guard
//                          CONDITION is projected as a PREDICATE leaf, lowered
//                          through guardToSolidity. It carries no token,
//                          domain, pack or corpus identity — only declared
//                          inputs and neutral ledger/effect names — so the
//                          supported path is pinned independently of any
//                          published example.
//   * temporal/multi     — mirrors the accepted_multi_policy production spec: two
//                          accepted(policy) suppress groups, the temporalPolicies
//                          vector, and the two-level groupPostings navigation.
//
//===----------------------------------------------------------------------===//

#include "SolidityRecipeProvider.h"

#include "Neutrino/BackendProjection.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/Expr.h"

#include "llvm/Support/Error.h"

#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <map>
#include <string>
#include <utility>

using namespace neutrino;
using namespace neutrino::projection;
using namespace neutrino::solidity_model;

namespace {

// Assemble + VERIFY a fixture through the single production normalization seam.
// A fixture that fails assemblePlan is a harness bug (a malformed plan), not a
// render to pin — abort loudly rather than pin invalid output.
CoordinationPlan assemble(PlanInputs in) {
  llvm::Expected<CoordinationPlan> plan = assemblePlan(std::move(in));
  if (!plan) {
    fprintf(stderr, "referee: assemblePlan rejected a fixture: %s\n",
            llvm::toString(plan.takeError()).c_str());
    std::exit(2);
  }
  return std::move(*plan);
}

LifecycleTransitionPolicy closeToClosed() {
  LifecycleTransitionPolicy close;
  close.name = "CLOSE";
  close.from = "OPEN";
  close.to = "CLOSED";
  close.idempotency = "reject";
  return close;
}

// The typed `accepted(<policy>)` guard AST: a Call to `accepted` over one Var.
// Its structural canonicalGuardKey is what assemblePlan partitions effect groups
// on, so two policies yield two distinct groups (mirrors the real per-policy
// binding). No dtype needed — the temporal render reads the resolved gate
// binding, never re-lowers the guard.
ExprPtr acceptedGuard(const char *policy) {
  auto call = std::make_unique<ExprNode>();
  call->kind = ExprNode::Call;
  call->name = "accepted";
  auto arg = std::make_unique<ExprNode>();
  arg->kind = ExprNode::Var;
  arg->name = policy;
  call->args.push_back(std::move(arg));
  return call;
}

// evidence + declared params, one of which IS the instance key: exercises the
// evidenceParams vector arm and the  instance-key sub-read. Effectless — an
// attestation policy with an explicit instance key + a success terminal is the
// evidence-acceptance coordination assemblePlan derives as evidenceOnly.
CoordinationPlan evidenceWithKeyParam() {
  PlanInputs in;
  in.procedure = "shipment_evidence_anchor";
  in.terminal.success = "CLOSED";
  in.lifecycleInitialState = "OPEN";
  in.lifecycleStates = {"OPEN", "CLOSED"};
  in.lifecycleTransitions.push_back(closeToClosed());
  in.explicitInstanceKey = "shipment_ref";
  in.inputs = {{"shipment_ref", "string"}, {"carrier", "string"}};
  AttestationPolicy a;
  a.input = "delivery";
  a.quorum = 2;
  a.observerSet = "0";
  a.canonicalization = "exact";
  a.timeout = "PT48H";
  a.fallback = "abort";
  in.attestations.push_back(a);
  return assemble(std::move(in));
}

// balanced atomic-refuse effectful coordination + declared inputs + a compute:
// exercises the effectful params / computes / expression / ledger-posting
// project arms. Every operand references a DECLARED input, so the render carries
// only valid `u_<input>` identifiers.
CoordinationPlan effectfulWithComputes() {
  PlanInputs in;
  in.procedure = "oracle_delivery";
  in.balanced = true;
  in.terminal.success = "CLOSED";
  in.lifecycleInitialState = "OPEN";
  in.lifecycleStates = {"OPEN", "QUORUM_MET", "CLOSED"};
  LifecycleTransitionPolicy commit;
  commit.name = "COMMIT";
  commit.from = "QUORUM_MET";
  commit.to = "CLOSED";
  commit.effects = {"post"};
  commit.idempotency = "reject";
  in.lifecycleTransitions.push_back(commit);
  in.explicitInstanceKey = "order_id";
  in.inputs = {{"amount", "money"},  {"rate", "number"},
               {"order_id", "string"}, {"payer", "party"},
               {"payee", "party"},     {"currency", "currency"}};
  AttestationPolicy a;
  a.input = "delivery";
  a.quorum = 2;
  a.observerSet = "0";
  a.canonicalization = "exact";
  a.timeout = "PT24H";
  a.fallback = "abort";
  in.attestations.push_back(a);
  auto leg = [](const char *kind, const char *ledger, const char *party) {
    PlanEffectInput e;
    e.kind = kind;
    e.ledger = ledger;
    e.party = party;
    e.amount = "ref:amount";
    e.currency = "ref:currency";
    e.idempotencyKind = "ref";
    e.idempotencyValue = "order_id";
    return e;
  };
  in.effects.push_back(leg("debit", "0", "ref:payer"));
  in.effects.push_back(leg("credit", "1", "ref:payee"));
  PlanCompute fee;
  fee.name = "fee";
  fee.category = "money";
  fee.deps = {"amount", "rate"};
  fee.expr = parseExpr("amount + rate");
  typeExpr(*fee.expr, {{"amount", ValueCategory::Money},
                       {"rate", ValueCategory::Decimal}});
  in.computes.push_back(std::move(fee));
  return assemble(std::move(in));
}

// [] SOURCE-NEUTRAL comparison-guard witness. An unattested coordination
// with TWO balanced debit/credit pairs, each pair carrying one comparison
// guard, so assemblePlan partitions them into two guarded balanced groups. That
// makes every finalized posting carry FinalizedPostingGuardKind::Comparison,
// which fires the effectful recipe's PresenceGuard optional slot and projects
// the guard CONDITION — the arm that used to hand a `Cmp` node to the VALUE
// emitter and refuse with `expr.type: a comparison predicate is not a value
// expression`.
//
// The two guards cover BOTH comparison shapes the language admits at a guard
// top: an EQUALITY against a literal (`approval == 1`) and a RELATIONAL
// comparison of two declared inputs (`amount >= floor_amount`). The lowering
// under test never reads the operator or the operand kinds — it lowers whatever
// the projection categorised as a predicate — and this witness is what pins
// that, so a future fix tuned to one operator shape would fail here.
//
// Deliberately identity-free: neutral procedure/ledger/effect/input names and a
// generic numeric approval flag. It shares only the EXPRESSION SHAPE with the
// published corpus rows, never their identity, so this witness — not a pack —
// is what pins the supported path.
CoordinationPlan effectfulComparisonGuard() {
  PlanInputs in;
  in.procedure = "guarded_pair";
  in.balanced = true;
  in.terminal.success = "CLOSED";
  in.lifecycleInitialState = "OPEN";
  in.lifecycleStates = {"OPEN", "CLOSED"};
  LifecycleTransitionPolicy commit;
  commit.name = "COMMIT";
  commit.from = "OPEN";
  commit.to = "CLOSED";
  commit.effects = {"post"};
  commit.idempotency = "reject";
  in.lifecycleTransitions.push_back(commit);
  in.explicitInstanceKey = "pair_id";
  in.inputs = {{"pair_id", "string"},      {"source_party", "party"},
               {"target_party", "party"},  {"amount", "money"},
               {"currency", "currency"},   {"approval", "number"},
               {"floor_amount", "money"}};
  // The typed guard predicates, built through the shared parse+type seam (no
  // hand-built AST), so the referee lowers exactly the nodes the production
  // spec path reconstructs.
  const std::map<std::string, ValueCategory> env{
      {"approval", ValueCategory::Decimal},
      {"amount", ValueCategory::Money},
      {"floor_amount", ValueCategory::Money}};
  auto guardAst = [&](const char *text) {
    ExprPtr g = parseGuard(text);
    typeGuard(*g, env);
    return g;
  };
  auto leg = [&](const char *name, const char *kind, const char *ledger,
                 const char *party, const char *guardText) {
    PlanEffectInput e;
    e.name = name;
    e.kind = kind;
    e.ledger = ledger;
    e.party = party;
    e.amount = "ref:amount";
    e.currency = "ref:currency";
    e.idempotencyKind = "ref";
    e.idempotencyValue = "pair_id";
    e.canonicalGuard = guardText;
    e.guard = guardAst(guardText);
    return e;
  };
  // pair 1 — equality guard against a literal.
  in.effects.push_back(leg("reserve_debit", "debit", "source.reserve",
                           "ref:source_party", "approval == 1"));
  in.effects.push_back(leg("holding_credit", "credit", "target.holding",
                           "ref:target_party", "approval == 1"));
  // pair 2 — relational guard between two declared inputs.
  in.effects.push_back(leg("buffer_debit", "debit", "source.buffer",
                           "ref:source_party", "amount >= floor_amount"));
  in.effects.push_back(leg("settled_credit", "credit", "target.settled",
                           "ref:target_party", "amount >= floor_amount"));
  return assemble(std::move(in));
}

// multi-policy temporal-suppress: mirrors the accepted_multi_policy production
// spec — two accepted(policy) groups (alpha/beta), each a balanced debit+credit
// pair keyed on the settlement id. Exercises temporalPolicies, two effect
// groups, and the two-level groupPostings navigation. The DISTINCT effect names
// give distinct event declarations (no duplicate `Debited`/`Credited`), and
// every operand references a declared input.
CoordinationPlan multiPolicyTemporal() {
  PlanInputs in;
  in.procedure = "accepted_multi_policy";
  in.balanced = true;
  in.terminal.success = "CLOSED";
  in.lifecycleInitialState = "OPEN";
  in.lifecycleStates = {"OPEN", "CLOSED"};
  in.lifecycleTransitions.push_back(closeToClosed());
  in.inputs = {{"settlement_id", "string"}, {"payer_id", "party"},
               {"payee_id", "party"},       {"amount", "money"},
               {"currency", "currency"}};
  auto policy = [](const char *input, int quorum, const char *observers) {
    AttestationPolicy a;
    a.input = input;
    a.quorum = quorum;
    a.observerSet = observers;
    a.canonicalization = "exact";
    a.fallback = "abort";
    return a;
  };
  in.attestations.push_back(policy("alpha_proof", 2, "alpha_oracles"));
  in.attestations.push_back(policy("beta_proof", 3, "beta_oracles"));
  auto leg = [](const char *name, const char *kind, const char *ledger,
                const char *party, const char *pol) {
    PlanEffectInput e;
    e.name = name;
    e.kind = kind;
    e.ledger = ledger;
    e.party = party;
    e.amount = "ref:amount";
    e.currency = "ref:currency";
    e.idempotencyKind = "ref";
    e.idempotencyValue = "settlement_id";
    e.guardAcceptedInput = pol;
    e.canonicalGuard = std::string("accepted(") + pol + ")";
    e.guard = acceptedGuard(pol);
    return e;
  };
  in.effects.push_back(
      leg("alpha_debit", "debit", "payer.alpha", "ref:payer_id", "alpha_proof"));
  in.effects.push_back(
      leg("beta_debit", "debit", "payer.beta", "ref:payer_id", "beta_proof"));
  in.effects.push_back(leg("alpha_credit", "credit", "payee.alpha",
                           "ref:payee_id", "alpha_proof"));
  in.effects.push_back(
      leg("beta_credit", "credit", "payee.beta", "ref:payee_id", "beta_proof"));
  return assemble(std::move(in));
}

// Drive one sequence through the REAL provider (via the shared interpreter) and
// render it. `driver` is one of the exposed materialize*ContractRecipe entries,
// each of which resolves an exact key and runs materializeRecipe over the
// generated module -> the provider's project/slotExtent/slotItemOrder fire.
using ContractDriver =
    SolidityContract (*)(const FinalizedProjectionSequence &);

std::string renderSequence(const CoordinationPlan &plan, ContractDriver driver) {
  llvm::Expected<BackendProjectionGraph> graph = projectBackendGraph(plan);
  if (!graph) {
    fprintf(stderr, "referee: projectBackendGraph failed: %s\n",
            llvm::toString(graph.takeError()).c_str());
    std::exit(2);
  }
  llvm::Expected<FinalizedProjectionSequence> sequence =
      consumeFinalizedProjectionSequence(*graph);
  if (!sequence) {
    fprintf(stderr, "referee: consumeFinalizedProjectionSequence failed: %s\n",
            llvm::toString(sequence.takeError()).c_str());
    std::exit(2);
  }
  SolidityContract contract = driver(*sequence);
  return renderSolidityProjection(contract);
}

// Fail if any canonical projection label leaked into the render as an invalid
// Solidity identifier. A verified source operand renders as `u_<name>`; a
// canonical `input:N` label (or any emitted identifier carrying a ':') is not a
// legal Solidity identifier and would make the pinned golden uncompilable — the
// exact residue a plan that bypassed assemblePlan's declared-input verification
// produces (a dangling / canonical `input:N` operand). Returns a description of
// the first offender, or "" when the render is clean.
std::string findInvalidIdentifier(const std::string &render) {
  // (a) the raw canonical label must never appear in a valid render.
  if (render.find("input:") != std::string::npos)
    return "canonical label 'input:'";
  // (b) a `u_`-prefixed operand identifier must be a run of [A-Za-z0-9_] never
  // immediately followed by ':' (a colon inside an emitted identifier).
  for (size_t i = 0; (i = render.find("u_", i)) != std::string::npos;) {
    size_t j = i + 2;
    while (j < render.size() &&
           (std::isalnum((unsigned char)render[j]) || render[j] == '_'))
      ++j;
    if (j < render.size() && render[j] == ':')
      return "emitted identifier '" + render.substr(i, j - i) +
             "' carries a ':' (canonical label)";
    i = j;
  }
  return "";
}

// Concatenate every driven render under a stable section banner. The banner is
// harness text, not a provider byte; the render bytes between banners are the
// referee A.2 byte-proves against.
std::string capture() {
  struct Case {
    const char *label;
    CoordinationPlan plan;
    ContractDriver driver;
  };
  const Case cases[] = {
      // The evidence contract recipe requires >=1 accept param, so the
      // instance-key-bearing evidence coordination is the evidence representative
      // (it also exercises the  instance-key sub-read).
      {"evidence+params( instance-key)", evidenceWithKeyParam(),
       materializeEvidenceContractRecipe},
      {"effectful/atomic+computes", effectfulWithComputes(),
       materializeEffectfulWithAttestationContractRecipe},
      // [] the unattested comparison-guard witness: the PresenceGuard arm
      // + the predicate-category expression leaf.
      {"effectful/comparison-guard()", effectfulComparisonGuard(),
       materializeEffectfulWithoutAttestationContractRecipe},
      {"temporal/multi-policy", multiPolicyTemporal(),
       materializeTemporalContractRecipe},
  };
  std::string out;
  bool first = true;
  for (const Case &c : cases) {
    // Blank-line separator BETWEEN sections only — each render ends in its own
    // trailing newline, so adding one after the last too would leave a blank
    // line at EOF (git diff --check).
    if (!first)
      out += "\n";
    first = false;
    out += "// ==== recipe-provider render referee: ";
    out += c.label;
    out += " ====\n";
    out += renderSequence(c.plan, c.driver);
  }
  return out;
}

} // namespace

int main(int argc, char **argv) {
  if (argc < 2) {
    fprintf(stderr, "usage: %s <golden.txt> [--emit]\n", argv[0]);
    return 2;
  }
  const std::string rendered = capture();

  // Leak guard runs BEFORE both --emit and compare, so a leaky render can never
  // be written to (or matched against) the golden.
  if (std::string bad = findInvalidIdentifier(rendered); !bad.empty()) {
    fprintf(stderr,
            "referee: rendered output contains an invalid Solidity identifier "
            "(%s) — a plan that bypassed assemblePlan leaked a canonical "
            "projection label into the render\n",
            bad.c_str());
    return 3;
  }

  const std::string goldenPath = argv[1];
  const bool emit = argc >= 3 && std::string(argv[2]) == "--emit";

  if (emit) {
    std::ofstream out(goldenPath, std::ios::binary);
    if (!out) {
      fprintf(stderr, "referee: cannot open golden for write: %s\n",
              goldenPath.c_str());
      return 2;
    }
    out << rendered;
    printf("referee: wrote %zu bytes to %s\n", rendered.size(),
           goldenPath.c_str());
    return 0;
  }

  std::ifstream in(goldenPath, std::ios::binary);
  if (!in) {
    fprintf(stderr, "referee: cannot open golden: %s\n", goldenPath.c_str());
    return 2;
  }
  std::stringstream ss;
  ss << in.rdbuf();
  if (ss.str() != rendered) {
    fprintf(stderr,
            "referee: rendered recipe-provider output differs from the pinned "
            "golden %s\n(the finalized-view trio render changed; if intended, "
            "re-emit the golden)\n",
            goldenPath.c_str());
    return 1;
  }
  puts("solidity-recipe-render-referee OK (real provider project/slotExtent/"
       "slotItemOrder drove the pinned render)");
  return 0;
}
