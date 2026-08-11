//===- CapabilitySpecTarget.cpp - compiled capability-spec target -------===//
//
// Emit the canonical compiled capability-spec — the ONLY
// frozen external contract of the architecture. A deterministic,
// canonical (sorted-key) JSON serialization of the semantic model that every
// renderer consumes instead of re-deriving from ProcedureView. Emitted from
// source alone; the Scenario is ignored (D2). Byte-reproducible (no
// timestamps/sha), so capability-spec.json is fixture-comparable and
// hash-stable. Schema: docs/schemas/capability-spec.schema.json.
//
// NOTE: the translator emits a compiled *capability-spec* from this explicit
// target entry. "spec" is a network/runtime orchestration concept, NOT a
// translator artifact.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSpec.h"

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/CoordinationPlanBuild.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/Lifecycle.h"
#include "Neutrino/LifecycleView.h"
#include "Neutrino/ValueModel.h"

#include "llvm/Support/Error.h"

#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <filesystem>
#include <fstream>
#include <set>
#include <string>
#include <vector>

using namespace llvm;

namespace neutrino {

namespace {

std::string categoryOf(llvm::StringRef type) {
  return categoryName(classifyValueType(type)).str();
}

std::string valueRequirementOf(llvm::StringRef type) {
  if (classifyValueType(type) == ValueCategory::Extension &&
      isTemporalType(type))
    return "value_extension:temporal";
  return "value_category:" + categoryOf(type);
}

// The compact, sorted-key canonical form of a value — the hash preimage. llvm's
// JSON printer sorts object keys; `{0}` selects the no-indent (compact) form.
// This matches Python's json.dumps(sort_keys=True, separators=(",", ":")), so
// the C++ emitter and the stdlib validator agree on the hash byte-for-byte.
std::string compactOf(const json::Object &o) {
  return compactJson(json::Value(json::Object(o)));
}

json::Value operand(const Ref &r) {
  // Ref = (isLiteral, text): a %reference to a declared input/compute, or a
  // constant.
  return json::Object{{"kind", r.first ? "literal" : "ref"},
                      {"value", r.second}};
}

json::Array inputsArray(const ProcedureView &v) {
  json::Array a;
  for (const auto &in : v.inputs)
    a.push_back(json::Object{{"name", in.first},
                             {"type", in.second},
                             {"category", categoryOf(in.second)}});
  return a;
}

json::Array computesArray(const ProcedureView &v) {
  json::Array a;
  for (const auto &c : v.computes) {
    json::Array deps;
    for (const auto &d : c.deps)
      deps.push_back(d);
    json::Object o{
        {"name", c.name},
        {"expr", c.expr},
        {"category", c.ast ? categoryName(c.ast->dtype).str() : "extension"},
        {"deps", std::move(deps)}};
    o["ast"] = c.ast ? exprToJson(*c.ast) : json::Value(nullptr);
    a.push_back(std::move(o));
  }
  return a;
}

json::Array effectsArray(const ProcedureView &v,
                         const CoordinationPlan &coordinationPlan) {
  json::Array a;
  for (size_t i = 0; i < v.entries.size(); ++i) {
    const EntryView &e = v.entries[i];
    const PlanEffect &planEffect = coordinationPlan.effects[i];
    json::Object o{
        {"kind", e.kind},
        {"name", e.name},
        {"ledger", e.ledger},
        {"owner", e.owner},
        {"participant", planEffect.participant.empty()
                            ? json::Value(nullptr)
                            : json::Value(planEffect.participant)},
        {"party", operand(e.party)},
        {"amount", operand(e.amount)},
        {"currency", operand(e.currency)},
        // The workflow key is serialized FROM the normalized coordinationPlan
        // () — the coordinationPlan is the source of this normalized
        // decision, not each effect's raw key (they are verified equal).
        {"idempotencyKey", operand(Ref{false, coordinationPlan.workflowKey})}};
    // Optional conditional guard (): a `when` predicate is emitted ONLY
    // when present, so unguarded specs are byte-identical. A spec carrying any
    // `when` bumps to schemaVersion 2 (see capabilitySpecSchemaVersion) — a
    // v1 consumer must refuse it, not silently post the leg unconditionally.
    // Carries the guard source text + the serialized comparison AST, mirroring
    // how a compute carries its.
    if (e.guardAst)
      o["when"] =
          json::Object{{"expr", e.guard}, {"ast", exprToJson(*e.guardAst)}};
    // Optional effect metadata: the free-text
    // memo/reference, emitted ONLY when present so an effect without a memo is
    // byte-identical and its capabilityHash is unchanged.
    if (!e.memo.empty())
      o["memo"] = e.memo;
    a.push_back(std::move(o));
  }
  return a;
}

json::Array participantsArray(const ProcedureView &v,
                              const CoordinationPlan &coordinationPlan) {
  json::Array a;
  for (size_t i = 0; i < coordinationPlan.participants.size(); ++i) {
    const PlanParticipant &p = coordinationPlan.participants[i];
    const ParticipantView &realization = v.participants[i];
    json::Array caps;
    for (const auto &c : realization.capabilities)
      caps.push_back(c);
    json::Array runtimes;
    for (const auto &r : realization.bindRuntimes)
      runtimes.push_back(r);
    a.push_back(json::Object{
        {"name", p.name},
        {"role", p.role},
        {"org", p.org.empty() ? json::Value(nullptr) : json::Value(p.org)},
        {"capabilities", std::move(caps)},
        {"binding", realization.isFlexible() ? "to_be_bound" : "fixed"},
        {"bindRuntimes", std::move(runtimes)},
        {"bindMinAssurance", realization.bindMinAssurance}});
  }
  return a;
}

json::Value topologyObj(const CoordinationPlan &coordinationPlan) {
  json::Array pairs;
  for (const PlanOrgPolicy &op : coordinationPlan.allowedOrgPairs)
    pairs.push_back(json::Object{{"orgA", op.orgA},
                                 {"orgB", op.orgB},
                                 {"roleA", op.roleA},
                                 {"roleB", op.roleB}});
  return json::Object{{"allowedOrgPairs", std::move(pairs)}};
}

json::Array invariantsArray(const CoordinationPlan &coordinationPlan) {
  json::Array a;
  // The balanced obligation is serialized FROM the normalized coordinationPlan
  // ().
  if (coordinationPlan.balanced)
    a.push_back(json::Object{{"kind", "balanced"}});
  return a;
}

// Attestation policies (oracle S1, ): the M-of-N oracle-consensus policy on
// evidence inputs. Serialized via the leaf contract (attestationPolicyJson) so
// the downstream renderers () reconstruct the same shape. Emitted only when
// a policy is declared (semanticCore omits the key otherwise), so specs with no
// attestation stay byte-identical.
json::Array attestationsArray(const ProcedureView &v) {
  json::Array a;
  for (const AttestationPolicy &p : v.attestations)
    a.push_back(attestationPolicyJson(p));
  return a;
}

// The one canonical coordination lifecycle machine. Today it is the fixed
// OPEN..CLOSE machine GenSlot emits (the DSL has no author-defined state
// machines yet, L2), so the transition NAMES equal GenSlot's operations and the
// effect-bearing transitions carry the spec's posted/compensated effects — the
// single machine both the slot lifecycle and the on-chain surface project from
// (acceptance). instanceKey composes the leg idempotency keys.
json::Value lifecycleObj(const ProcedureView &v) {
  // Serialize the ONE canonical machine — the same LifecycleModel
  // the slot artifacts project from, so a slot cannot drift from the spec's
  // lifecycle.
  const LifecycleModel m = lifecycleModel(v);

  json::Array fields;
  for (const std::string &k : m.instanceKeyFields)
    fields.push_back(k);

  // The instance-key object carries the derived key `fields`, plus — when the
  // procedure declares an explicit instance key — an additive `declared` field
  // (absent for a legacy effect-keyed coordination, so its bytes are stable).
  json::Object instanceKey{{"fields", std::move(fields)}};
  if (v.instanceKey)
    instanceKey["declared"] = *v.instanceKey;

  json::Array states;
  for (const LifecycleState &s : m.states) {
    json::Object o{{"name", s.name}, {"terminal", s.terminal}};
    if (!s.terminalKind.empty())
      o["terminalKind"] = s.terminalKind;
    states.push_back(std::move(o));
  }

  json::Array transitions;
  for (const LifecycleTransition &t : m.transitions) {
    json::Array effects;
    for (const std::string &e : t.effects)
      effects.push_back(e);
    transitions.push_back(json::Object{{"name", t.name},
                                       {"from", t.from},
                                       {"to", t.to},
                                       {"effects", std::move(effects)},
                                       {"guards", json::Array{}},
                                       {"idempotency", t.idempotency},
                                       {"evidence", nullptr}});
  }

  return json::Object{
      {"instanceKey", std::move(instanceKey)},
      {"initialState", m.initialState},
      {"states", std::move(states)},
      {"transitions", std::move(transitions)},
      {"terminalStates",
       json::Object{{"success", m.successState},
                    {"aborted", m.abortedState},
                    // contested = the oracle `escalate` timeout terminal (S3,
                    // ); null for every other shape.
                    {"contested", m.contestedState.empty()
                                      ? json::Value(nullptr)
                                      : json::Value(m.contestedState)}}}};
}

// 1-based source location, or null. The lexer is line-oriented, so column is
// always 1.
json::Value sourceJson(int line) {
  return line > 0 ? json::Value(json::Object{{"line", line}, {"column", 1}})
                  : json::Value(nullptr);
}

int at(const std::vector<int> &lines, size_t i) {
  return i < lines.size() ? lines[i] : 0;
}

// Structured target requirements ( F4 / AD3): one record per semantic
// primitive the spec needs a target to support — `feature`, the originating
// `primitive`, its `source` span, the `requirement` level, and a `fallback` —
// so a legality diagnostic can name the exact line that produced a
// requirement the target can't meet. Everything today is `required` with no
// `fallback` (both are forward space). Matching is set-intersection over
// `feature`.
json::Value targetRequirementsObj(const ProcedureView &v) {
  json::Array reqs;
  auto req = [&](const std::string &feature, const std::string &primitive,
                 int line) {
    reqs.push_back(json::Object{{"feature", feature},
                                {"primitive", primitive},
                                {"source", sourceJson(line)},
                                {"requirement", "required"},
                                {"fallback", nullptr}});
  };
  // Value requirements — one per distinct category or narrow extension,
  // sourced to the FIRST construct that introduces it (input, then compute),
  // in declaration order. Unknown extensions retain the generic fail-closed
  // value_category:extension requirement.
  std::set<std::string> seenValueRequirements;
  for (size_t i = 0; i < v.inputs.size(); ++i) {
    std::string feature = valueRequirementOf(v.inputs[i].second);
    if (seenValueRequirements.insert(feature).second)
      req(feature, "input " + v.inputs[i].first, at(v.inputLines, i));
  }
  for (size_t i = 0; i < v.computes.size(); ++i) {
    std::string cat = v.computes[i].ast
                          ? categoryName(v.computes[i].ast->dtype).str()
                          : "extension";
    std::string feature = "value_category:" + cat;
    if (seenValueRequirements.insert(feature).second)
      req(feature, "compute " + v.computes[i].name, at(v.computeLines, i));
  }
  // effect kinds — one per distinct kind, sourced to the first such leg.
  std::set<std::string> seenEff;
  for (size_t i = 0; i < v.entries.size(); ++i)
    if (seenEff.insert(v.entries[i].kind).second)
      req("effect:" + v.entries[i].kind,
          v.entries[i].kind + " " + v.entries[i].name, at(v.entryLines, i));
  // conditional guard (): a leg-level `when` predicate is a target-support
  // requirement — the backend must be able to conditionally apply the effect
  // (SQL `IF`, Solidity `if`). Sourced to the first guarded leg.
  for (size_t i = 0; i < v.entries.size(); ++i)
    if (!v.entries[i].guard.empty()) {
      req("guard:conditional", "when " + v.entries[i].name,
          at(v.entryLines, i));
      break;
    }
  if (v.balanced)
    req("invariant:balanced", "assert balanced", v.assertLine);
  // Attestation policy (): a declared M-of-N oracle policy is a real
  // target-support requirement — a target must be able to render the on-chain
  // acceptance guard ( slice 2). Until that slice + a supporting profile
  // land, NO profile advertises `attestation:quorum`, so the legality gate
  // fails closed: a target cannot silently drop the policy and render the
  // evidence as if it were unattested. One requirement per
  // attested input.
  for (size_t i = 0; i < v.attestations.size(); ++i)
    req("attestation:quorum", "attest " + v.attestations[i].input,
        at(v.attestationLines, i));
  // structural requirements.
  for (size_t i = 0; i < v.participants.size(); ++i)
    if (v.participants[i].isFlexible()) {
      req("binding:flexible", "participant " + v.participants[i].name,
          at(v.participantLines, i));
      break;
    }
  if (!v.participants.empty())
    req("topology:participants", "participant " + v.participants[0].name,
        at(v.participantLines, 0));
  if (!v.allowedOrgPairs.empty())
    req("topology:org_coordination",
        "allow " + v.allowedOrgPairs[0].orgA + " with " +
            v.allowedOrgPairs[0].orgB,
        at(v.allowLines, 0));

  return json::Object{{"requirements", std::move(reqs)},
                      {"evidenceStyle", "single_hash"},
                      {"unsupportedConstructs", json::Array{}}};
}

json::Array sourceMapArray(const ProcedureView &v) {
  // Real 1-based source lines from the frontend's FileLineColLoc/FusedLoc (
  // F3). source is null only when an op carries no file location.
  // capabilityHash excludes sourceMap, so line shifts (reformatting) leave the
  // capability identity stable while specHash tracks them.
  json::Array a;
  auto add = [&](const std::string &path, const std::string &construct,
                 int line) {
    a.push_back(json::Object{{"specPath", path},
                             {"construct", construct},
                             {"source", sourceJson(line)}});
  };
  for (size_t i = 0; i < v.inputs.size(); ++i)
    add("inputs[" + std::to_string(i) + "]", "input " + v.inputs[i].first,
        at(v.inputLines, i));
  for (size_t i = 0; i < v.computes.size(); ++i)
    add("computes[" + std::to_string(i) + "]", "compute " + v.computes[i].name,
        at(v.computeLines, i));
  for (size_t i = 0; i < v.entries.size(); ++i)
    add("effects[" + std::to_string(i) + "]",
        v.entries[i].kind + " " + v.entries[i].name, at(v.entryLines, i));
  for (size_t i = 0; i < v.participants.size(); ++i)
    add("participants[" + std::to_string(i) + "]",
        "participant " + v.participants[i].name, at(v.participantLines, i));
  for (size_t i = 0; i < v.allowedOrgPairs.size(); ++i)
    add("topology.allowedOrgPairs[" + std::to_string(i) + "]",
        "allow " + v.allowedOrgPairs[i].orgA + " with " +
            v.allowedOrgPairs[i].orgB,
        at(v.allowLines, i));
  if (v.balanced)
    add("invariants[0]", "assert balanced", v.assertLine);
  return a;
}

// The semantic core — the `capabilityHash` preimage. It is the PRIMARY semantic
// content ONLY: `specVersion`, the procedure, and the typed inputs / computes /
// effects / invariants / participants / topology / lifecycle. Deliberately
// EXCLUDED: the envelope discriminators `kind` and
// `schemaVersion` — a `kind` is a document tag (constant) and `schemaVersion`
// is a derived flag (its guard semantics are already hashed via the effects'
// `when`), so neither is capability *meaning*. Also excluded (as before):
// `identity`, `sourceMap`, and `targetRequirements` — the last two are derived,
// line-bearing projections. The result: `capabilityHash` is a PURE semantic
// identity, so an envelope-only change (a future `kind`/`schemaVersion`/`$id`
// bump) never moves it — the whole corpus of derived artifacts (views,
// realizations) that cross-check it stays stable across envelope renames.
// Obligations for the HASH preimage (): identity + obligor/scope + the
// ORDERED effect references + the typed activation predicate. Ordered (effect
// order is part of the obligation identity, and assemblePlan requires it to
// agree with executable order); present only when the coordination plan carries
// an obligation. `statuses` is version-derived and NOT on the wire (P1-3).
json::Array obligationsArray(const CoordinationPlan &p) {
  json::Array out;
  for (const PlanObligation &o : p.obligations) {
    json::Array effs;
    for (const std::string &en : o.effects)
      effs.push_back(en);
    // `statuses` is DERIVED from `version` (kObligationPlanVersion), so it is
    // NOT serialized on the wire ( P1-3): the version alone defines the
    // lifecycle vocabulary, leaving no independent field an ingested spec can
    // tamper. planFromSpec re-derives it via obligationStatusVocabulary.
    json::Object obj{
        {"version", (int64_t)o.version}, {"name", o.name},
        {"obligor", o.obligor},          {"beneficiary", o.beneficiary},
        {"authority", o.authority},      {"effects", std::move(effs)}};
    // The activation predicate: source text + the serialized typed comparison
    // AST, mirroring an effect's `when` — so it joins the hash and is
    // reconstructable by planFromSpec (round-trip).
    if (o.when)
      obj["when"] = json::Object{{"expr", o.canonicalGuard},
                                 {"ast", exprToJson(*o.when)}};
    out.push_back(std::move(obj));
  }
  return out;
}

json::Object semanticCore(const ProcedureView &v,
                          const CoordinationPlan &coordinationPlan) {
  json::Object o;
  o["specVersion"] = v.version;
  o["procedure"] = v.name;
  o["trigger"] = v.trigger ? json::Value(*v.trigger) : json::Value(nullptr);
  o["inputs"] = inputsArray(v);
  o["computes"] = computesArray(v);
  o["effects"] = effectsArray(v, coordinationPlan);
  o["invariants"] = invariantsArray(coordinationPlan);
  o["participants"] = participantsArray(v, coordinationPlan);
  o["topology"] = topologyObj(coordinationPlan);
  o["lifecycle"] = lifecycleObj(v);
  // Additive (): present only when the spec declares an attestation policy,
  // so an unattested spec's semantic core — and thus its capabilityHash — is
  // byte-identical to before this feature.
  if (!v.attestations.empty())
    o["attestations"] = attestationsArray(v);
  // Additive (): present only when the coordination plan has an obligation,
  // so an obligation-free spec's semantic core — and thus its capabilityHash —
  // is byte-identical. Obligation identity + ordered effects join the hash
  // here.
  if (!coordinationPlan.obligations.empty())
    o["obligations"] = obligationsArray(coordinationPlan);
  return o;
}

// The full serialized core = the envelope discriminators (`kind`,
// `schemaVersion`) over the semantic core. Emitted (minus identity/sourceMap/
// targetRequirements) as the artifact body; the envelope fields are present in
// the bytes and covered by `specHash`, but NOT by `capabilityHash`.
json::Object specCore(const ProcedureView &v,
                      const CoordinationPlan &coordinationPlan) {
  json::Object o = semanticCore(v, coordinationPlan);
  o["schemaVersion"] = capabilitySpecSchemaVersion(v);
  o["kind"] = "neutrino.capability-spec";
  return o;
}

} // namespace

std::string canonicalSemanticBytes(const ProcedureView &view,
                                   const CoordinationPlan &coordinationPlan) {
  return compactOf(semanticCore(view, coordinationPlan));
}

std::string capabilityHashOf(const ProcedureView &view,
                             const CoordinationPlan &coordinationPlan) {
  return sha256Hex(canonicalSemanticBytes(view, coordinationPlan));
}

int capabilitySpecSchemaVersion(const ProcedureView &view) {
  // : an obligation-bearing spec is schemaVersion 4 and validates against
  // the NEW `capability-spec/v2` contract (docs/schemas/capability-spec-v2),
  // which admits the top-level `obligations` section the frozen v1 contract
  // does not. A pre-4 consumer must REFUSE it rather than silently drop the
  // undertaking — the discriminator the reviewer required (P1-2). Obligation
  // subsumes attestation/guard (4 > 3 > 2), and the obligation ALSO carries its
  // own representation `version` for intra-section evolution. Adding v2 is a
  // COMPATIBLE bundle evolution (a new contract; v1 stays byte-identical), the
  // same shape as the l2-domain-semantics v2→v3 split ().
  if (!view.obligations.empty())
    return 4;
  // An attestation policy is schemaVersion 3: it is the
  // first point where a consumer that IGNORES the policy is UNSAFE — the S2
  // lowering () renders the on-chain M-of-N acceptance guard FROM the
  // policy, so a backend that skips it would deploy the coordination WITHOUT
  // the quorum check (a leg firing on unattested evidence). A pre-3 consumer
  // must refuse such a spec rather than silently drop the guard. Attestation
  // subsumes the guard bump (3 > 2), so an attested spec is 3 whether or not it
  // also carries `when`.
  if (!view.attestations.empty())
    return 3;
  // Conditional guards () are a semantics-changing feature: a spec carrying
  // any effect `when` is schemaVersion 2, so a v1 consumer refuses it rather
  // than silently posting a guarded leg unconditionally. An unguarded spec
  // stays 1 (byte-identical to before this feature).
  for (const auto &e : view.entries)
    if (!e.guard.empty())
      return 2;
  return 1;
}

int capabilitySpecSchemaVersion() { return 3; }

std::string capabilitySpecJson(const ProcedureView &view,
                               const CoordinationPlan &coordinationPlan) {
  std::string capHash = capabilityHashOf(view, coordinationPlan);

  // specHash covers the whole capability-spec (primary + derived projections),
  // so it DOES move with source lines — that is the whole-artifact digest,
  // distinct from the semantic capabilityHash.
  json::Object body = specCore(view, coordinationPlan);
  body["targetRequirements"] = targetRequirementsObj(view);
  body["sourceMap"] = sourceMapArray(view);
  body["identity"] = json::Object{{"capabilityHash", capHash}};
  std::string specHash = sha256Hex(compactOf(body));
  body["identity"] =
      json::Object{{"capabilityHash", capHash}, {"specHash", specHash}};

  return formatv("{0:2}", json::Value(std::move(body))).str() + "\n";
}

SelfEmittedSpec
ingestSelfEmittedSpec(const ProcedureView &view,
                      const CoordinationPlan &coordinationPlan) {
  // Emit our own spec then ingest it through the shared adapter — a prvalue, so
  // C++17 guaranteed copy elision initializes the caller's SelfEmittedSpec
  // directly (the type is non-movable).
  return SelfEmittedSpec(SelfEmittedSpec::FromOwnOutput{},
                         capabilitySpecJson(view, coordinationPlan));
}

std::vector<std::string>
emitCapabilitySpec(const ProcedureView &view, const Scenario &,
                   const std::string &outDir,
                   const CoordinationPlan &coordinationPlan) {
  namespace fs = std::filesystem;
  fs::create_directories(outDir);
  std::string path = (fs::path(outDir) / "capability-spec.json").string();
  std::ofstream os(path);
  os << capabilitySpecJson(view, coordinationPlan);
  return {path};
}

} // namespace neutrino
