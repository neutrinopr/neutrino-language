//===- CoordinationEnvelope.cpp - canonical per-invocation execution claim ---===//
//
// The domain-separated execution claim (): a hash binding a COORDINATION
// IDENTITY + workflow key + the TYPED input payload of one invocation, so the
// payload is immutable per (coordination, key) across a multi-call (temporal)
// coordination and acceptance never crosses coordinations. Mirrors
// AgreementEnvelope's explicit big-endian length framing so no field boundary
// is ambiguous; distinct DOMAINS so an execution claim / coordination identity
// can never collide with an agreement identity. MLIR-free; the reference
// evaluator and every rail derive the SAME values from one normalized
// coordination + its payload.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationEnvelope.h"

#include "Neutrino/Expr.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/ValueModel.h"

#include <algorithm>
#include <cstdint>
#include <tuple>
#include <vector>

using namespace llvm;

namespace neutrino {

namespace {
// frame(x) = BE64(byteLength(x)) ‖ x — mirrors AgreementEnvelope::appendFramed.
void appendFramed(std::string &out, StringRef field) {
  uint64_t n = field.size();
  for (int shift = 56; shift >= 0; shift -= 8)
    out.push_back(static_cast<char>((n >> shift) & 0xFF));
  out.append(field.data(), field.size());
}
constexpr StringRef kCoordinationEnvelopeDomain = "neutrino.coordination-envelope.v1";
constexpr StringRef kCoordinationIdentityDomain =
    "neutrino.coordination-identity.v1";

// A STABLE cross-implementation wire tag for an expression node kind. Explicit
// protocol values, NOT the C++ enum ordinal — so reordering the enum, or a rail
// (Solidity/PostgreSQL/…) reproducing the same encoding, cannot change the
// identity while the domain stays v1.
StringRef exprKindTag(ExprNode::Kind k) {
  switch (k) {
  case ExprNode::Num:
    return "num";
  case ExprNode::Var:
    return "var";
  case ExprNode::Bin:
    return "bin";
  case ExprNode::Call:
    return "call";
  case ExprNode::Cmp:
    return "cmp";
  }
  return "?"; // unreachable — the switch is total over the closed vocabulary
}

// A complete structural serialization of a typed expression AST (compute or
// guard): a stable kind tag, literal, name, operator, the stable value-category
// NAME (not the enum ordinal), then children — so two differently-meaning
// expressions never frame identically, and the encoding is reproducible by any
// rail.
void appendExpr(std::string &out, const ExprNode *n) {
  if (!n) {
    appendFramed(out, "\x00"); // an absent child, distinct from any real node
    return;
  }
  appendFramed(out, exprKindTag(n->kind));
  appendFramed(out, std::to_string(n->num));
  appendFramed(out, n->name);
  appendFramed(out, std::string(1, n->op));
  appendFramed(out, categoryName(n->dtype));
  appendExpr(out, n->lhs.get());
  appendExpr(out, n->rhs.get());
  appendFramed(out, std::to_string(n->args.size()));
  for (const auto &a : n->args)
    appendExpr(out, a.get());
}
} // namespace

std::string coordinationIdentityHash(const CoordinationPlan &coordinationPlan) {
  std::string p;
  appendFramed(p, kCoordinationIdentityDomain);
  // Procedure-level identity + lifecycle/replay/balance obligations.
  appendFramed(p, coordinationPlan.procedure);
  appendFramed(p, coordinationPlan.workflowKey);
  appendFramed(p, coordinationPlan.explicitInstanceKey);
  appendFramed(p, coordinationPlan.evidenceOnly ? "1" : "0");
  appendFramed(p, coordinationPlan.balanced ? "1" : "0");
  appendFramed(p, coordinationPlan.replay.key);
  appendFramed(p, coordinationPlan.replay.idempotent ? "1" : "0");
  appendFramed(p, coordinationPlan.terminal.success);
  appendFramed(p, coordinationPlan.terminal.aborted);
  appendFramed(p, coordinationPlan.terminal.contested);
  // Declared, typed input inventory in declaration order.
  appendFramed(p, std::to_string(coordinationPlan.inputs.size()));
  for (const PlanInput &pin : coordinationPlan.inputs) {
    appendFramed(p, pin.name);
    appendFramed(p, pin.type);
  }
  // Computes: name, category, dependency set, and the full typed expression.
  appendFramed(p, std::to_string(coordinationPlan.computes.size()));
  for (const PlanCompute &pc : coordinationPlan.computes) {
    appendFramed(p, pc.name);
    appendFramed(p, pc.category);
    appendFramed(p, std::to_string(pc.deps.size()));
    for (const std::string &d : pc.deps)
      appendFramed(p, d);
    appendExpr(p, pc.expr.get());
  }
  // Effects: posting identity, the STRUCTURAL guard key + full guard AST, and
  // the gating policy binding.
  appendFramed(p, std::to_string(coordinationPlan.effects.size()));
  for (const PlanEffect &e : coordinationPlan.effects) {
    appendFramed(p, e.name);
    appendFramed(p, e.kind);
    appendFramed(p, e.ledger);
    appendFramed(p, e.party);
    appendFramed(p, e.amount);
    appendFramed(p, e.currency);
    appendFramed(p, e.guardKey);
    appendFramed(p, e.attestationInput);
    appendExpr(p, e.guard.get());
  }
  // Effect groups: the per-group balance obligation.
  appendFramed(p, std::to_string(coordinationPlan.effectGroups.size()));
  for (const PlanEffectGroup &g : coordinationPlan.effectGroups) {
    appendFramed(p, g.guardKey);
    appendFramed(p, g.attestationInput);
    appendFramed(p, g.mustBalance ? "1" : "0");
    appendFramed(p, std::to_string(g.debitCount));
    appendFramed(p, std::to_string(g.creditCount));
  }
  // Attestation policies: every declared field.
  appendFramed(p, std::to_string(coordinationPlan.attestations.size()));
  for (const AttestationPolicy &a : coordinationPlan.attestations) {
    appendFramed(p, a.input);
    appendFramed(p, std::to_string(a.quorum));
    appendFramed(p, a.observerSet);
    appendFramed(p, a.observerRole);
    appendFramed(p, a.canonicalization);
    appendFramed(p, a.tolerance);
    appendFramed(p, a.timeout);
    appendFramed(p, a.fallback);
    appendFramed(p, a.assurance);
    appendFramed(p, a.independence);
  }
  // Obligations ( P1-1): a first-class undertaking is part of the
  // coordination's IDENTITY — the identity every rail and the evaluator's
  // replay claim binds — not only of the capability-spec hash. Every semantic
  // field is framed: the representation version, identity, obligor/scope, the
  // structural predicate key + full typed predicate AST, the ORDERED effect
  // references, and the lifecycle statuses. OMITTED ENTIRELY when there are no
  // obligations, so every existing obligation-free coordination plan's identity
  // stays byte-identical (the same omit-when-empty discipline as semanticCore);
  // when present the block is length-framed and self-describing, so it cannot
  // be confused with the preceding fields.
  if (!coordinationPlan.obligations.empty()) {
    appendFramed(p, std::to_string(coordinationPlan.obligations.size()));
    for (const PlanObligation &o : coordinationPlan.obligations) {
      appendFramed(p, std::to_string(o.version));
      appendFramed(p, o.name);
      appendFramed(p, o.obligor);
      appendFramed(p, o.beneficiary);
      appendFramed(p, o.authority);
      appendFramed(p, o.guardKey);
      appendExpr(p, o.when.get());
      appendFramed(p, std::to_string(o.effects.size()));
      for (const std::string &en : o.effects)
        appendFramed(p, en);
      appendFramed(p, std::to_string(o.statuses.size()));
      for (const std::string &st : o.statuses)
        appendFramed(p, st);
    }
  }
  return sha256Hex(p);
}

std::string executionClaimHash(StringRef coordinationIdentity,
                               StringRef workflowKey,
                               ArrayRef<ExecutionInput> canonicalInputs) {
  // Canonical ORDER by (name, category, value): the payload is a set, so its
  // claim must not depend on the caller's insertion order.
  std::vector<ExecutionInput> sorted(canonicalInputs.begin(),
                                     canonicalInputs.end());
  std::sort(sorted.begin(), sorted.end(),
            [](const ExecutionInput &a, const ExecutionInput &b) {
              return std::tie(a.name, a.category, a.value) <
                     std::tie(b.name, b.category, b.value);
            });
  std::string preimage;
  appendFramed(preimage, kCoordinationEnvelopeDomain);
  appendFramed(preimage, coordinationIdentity);
  appendFramed(preimage, workflowKey);
  // Frame the pair COUNT so a differing arity cannot collide with a different
  // partition of the same bytes.
  appendFramed(preimage, std::to_string(sorted.size()));
  for (const ExecutionInput &in : sorted) {
    appendFramed(preimage, in.name);
    appendFramed(preimage, in.category);
    appendFramed(preimage, in.value);
  }
  return sha256Hex(preimage);
}

} // namespace neutrino
