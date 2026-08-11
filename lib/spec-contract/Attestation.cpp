//===- Attestation.cpp - the attestation-policy contract leaf -------------===//
//
// M5 oracle S1 (): the spec-declared oracle-consensus policy on an
// `evidence` input — (de)serialization + fail-closed validation. See
// Neutrino/Attestation.h. Everything downstream in  renders FROM this.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Attestation.h"

#include "Neutrino/Expr.h"

#include <algorithm>
#include <string>

using namespace llvm;

namespace neutrino {

ArrayRef<StringRef> attestationCanonicalizationModes() {
  static const StringRef kModes[] = {"exact", "median"};
  return kModes;
}

ArrayRef<StringRef> attestationFallbacks() {
  // `abort` ends the coordination; `escalate` hands off to a declared
  // escalation path. `degrade` ("continue on a reduced guarantee") is deferred
  // (/S1 review): it is under-specified — degrade to WHAT — and would need
  // precise, rendered semantics before slice 2 emits it, or it becomes
  // fail-open with extra steps. Add it back only with an explicit reduced
  // target.
  static const StringRef kFallbacks[] = {"abort", "escalate"};
  return kFallbacks;
}

ArrayRef<StringRef> attestationAssuranceTiers() {
  // Mirrors the Trust lane's A1-A4 ladder
  // (docs/binding/TRUST_LATE_BINDING_CONTRACT.md): A1 compiler attestation, A2
  // realization, A3 runtime evidence, A4 proof.
  static const StringRef kTiers[] = {"A1", "A2", "A3", "A4"};
  return kTiers;
}

ArrayRef<StringRef> attestationIndependenceModes() {
  static const StringRef kModes[] = {"independent", "correlated"};
  return kModes;
}

static bool isOneOf(StringRef v, ArrayRef<StringRef> set) {
  return std::find(set.begin(), set.end(), v) != set.end();
}

std::string validateAttestationPolicy(const AttestationPolicy &p) {
  // M-of-N: only the threshold M is spec-level (concrete N is binding-level),
  // so all we can check here is that M is a positive integer.
  if (p.quorum <= 0)
    return "attestation quorum must be a positive integer (the M-of-N "
           "threshold), got " +
           std::to_string(p.quorum);
  if (p.observerSet.empty())
    return "attestation policy requires an observer-set reference";
  if (p.canonicalization.empty())
    return "attestation policy requires a canonicalization mode (one of: "
           "exact, median)";
  if (!isOneOf(p.canonicalization, attestationCanonicalizationModes()))
    return "unsupported attestation canonicalization mode '" +
           p.canonicalization + "' (expected one of: exact, median)";
  if (p.fallback.empty() || !isOneOf(p.fallback, attestationFallbacks()))
    return "unsupported attestation fallback '" + p.fallback +
           "' (expected one of: abort, escalate)";
  // Trust-surfacing metadata (oracle S6, ) is OPTIONAL — an undeclared
  // ("") tier/posture is valid (the security spec surfaces it as an advisory);
  // a DECLARED one must be from the accepted set.
  if (!p.assurance.empty() &&
      !isOneOf(p.assurance, attestationAssuranceTiers()))
    return "unsupported observer-set assurance tier '" + p.assurance +
           "' (expected one of: A1, A2, A3, A4)";
  if (!p.independence.empty() &&
      !isOneOf(p.independence, attestationIndependenceModes()))
    return "unsupported observer-set independence '" + p.independence +
           "' (expected one of: independent, correlated)";
  return "";
}

// A trimmed string as a JSON value, or null when empty — keeps optional fields
// (role/tolerance/timeout) explicit and absent-as-null in the frozen shape.
static json::Value orNull(const std::string &s) {
  return s.empty() ? json::Value(nullptr) : json::Value(s);
}

json::Value attestationPolicyJson(const AttestationPolicy &p) {
  json::Object observerSet{{"ref", p.observerSet},
                           {"role", orNull(p.observerRole)}};
  // assurance/independence (oracle S6, ) are properties OF the observer set
  // — declared trust metadata surfaced by the security spec. Present ONLY when
  // declared (unlike role/tolerance/timeout, which predate the frozen
  // shape and stay null-when-absent): a pre-S6 attestation that omits them
  // keeps its exact {ref, role} shape, so `attestations` — and thus the
  // capabilityHash that covers the semantic core — is byte-identical, additive
  // like the top-level `attestations` array itself.
  if (!p.assurance.empty())
    observerSet["assurance"] = p.assurance;
  if (!p.independence.empty())
    observerSet["independence"] = p.independence;
  return json::Object{
      {"input", p.input},
      // M is spec; N/members are binding-level () — deliberately absent.
      {"quorum", json::Object{{"threshold", p.quorum}}},
      {"observerSet", std::move(observerSet)},
      {"canonicalization", json::Object{{"mode", p.canonicalization},
                                        {"tolerance", orNull(p.tolerance)}}},
      {"timeout", orNull(p.timeout)},
      {"fallback", p.fallback}};
}

std::vector<AttestationPolicy>
attestationPoliciesFromSpec(const json::Object &spec) {
  std::vector<AttestationPolicy> out;
  const json::Array *arr = spec.getArray("attestations");
  if (!arr)
    return out;
  for (const json::Value &v : *arr) {
    const json::Object *o = v.getAsObject();
    if (!o)
      continue;
    AttestationPolicy p;
    p.input = o->getString("input").value_or("").str();
    if (const json::Object *q = o->getObject("quorum"))
      p.quorum = (int)q->getInteger("threshold").value_or(0);
    if (const json::Object *os = o->getObject("observerSet")) {
      p.observerSet = os->getString("ref").value_or("").str();
      p.observerRole = os->getString("role").value_or("").str();
      p.assurance = os->getString("assurance").value_or("").str();
      p.independence = os->getString("independence").value_or("").str();
    }
    if (const json::Object *c = o->getObject("canonicalization")) {
      p.canonicalization = c->getString("mode").value_or("").str();
      p.tolerance = c->getString("tolerance").value_or("").str();
    }
    p.timeout = o->getString("timeout").value_or("").str();
    p.fallback = o->getString("fallback").value_or("").str();
    out.push_back(std::move(p));
  }
  return out;
}

void requireSingleAttestationPolicy(
    const std::vector<AttestationPolicy> &policies, StringRef railLowering) {
  if (policies.size() <= 1)
    return;
  throw ExprError(
      "attest.multi_policy.unsupported",
      "spec declares " + std::to_string(policies.size()) +
          " attestation policies; " + railLowering.str() +
          " gates exactly ONE per procedure — refusing to render a guard that "
          "would leave all but the first policy UNGATED (fail-open). "
          "Multi-policy binding (one acceptance per policy) is a follow-up");
}

} // namespace neutrino
