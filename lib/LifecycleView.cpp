//===- LifecycleView.cpp - the ProcedureView adapter for the lifecycle machine
//---===//
//
// The View.h/ProcedureView adapter for the canonical lifecycle machine ().
// Split out of Lifecycle.cpp so the lifecycle CONTRACT (Neutrino/Lifecycle.h +
// the leaf) stays View.h-free; this adapter lives ABOVE the
// NeutrinoSpecContract leaf, in NeutrinoAnalysis. See Neutrino/LifecycleView.h.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/LifecycleView.h"

#include <set>
#include <string>

namespace neutrino {

LifecycleModel lifecycleModel(const ProcedureView &view) {
  LifecycleModel m;

  // The instance/workflow key: the non-literal idempotency keys of the legs, as
  // a sorted, de-duplicated set (the spec's prior behavior).
  std::set<std::string> keyFields;
  for (const EntryView &e : view.entries)
    if (!e.idempotency_key.first && !e.idempotency_key.second.empty())
      keyFields.insert(e.idempotency_key.second);
  m.instanceKeyFields.assign(keyFields.begin(), keyFields.end());

  m.initialState = "INITIAL";
  m.successState = "CLOSED";
  m.abortedState = "REJECTED";

  // Oracle-consensus gate (M5 oracle S3, ): when the spec carries an
  // attestation policy, the guarded post is gated by an M-of-N quorum, so the
  // machine gains explicit quorum states instead of hiding the check inside a
  // boolean. The post (COMMIT) departs ONLY from QUORUM_MET, and QUORUM_MET is
  // reachable ONLY via REACH_QUORUM from QUORUM_PENDING — there is NO
  // PROPOSED/QUORUM_PENDING -> COMMITTED edge, so a leg can never fire on < M
  // (fail-closed by construction). On deadline the machine takes the DECLARED
  // fallback (rendered from the policy): `escalate` -> a `contested` terminal,
  // otherwise `abort` -> the aborted terminal; the guarded leg still never
  // fires. Additive: a non-oracle spec keeps the exact OPEN..CLOSE machine
  // below (byte-identical lifecycle).
  if (!view.attestations.empty()) {
    // `escalate` only when EVERY policy declares it; a single `abort` forces
    // the fail-closed abort target (conservative for the one shared machine).
    bool escalate = true;
    for (const AttestationPolicy &a : view.attestations)
      if (a.fallback != "escalate") {
        escalate = false;
        break;
      }

    m.states = {
        {"INITIAL", false, ""},        {"NEW", false, ""},
        {"NEGOTIATED", false, ""},     {"PROPOSED", false, ""},
        {"QUORUM_PENDING", false, ""}, {"QUORUM_MET", false, ""},
        {"QUORUM_TIMEOUT", false, ""}, {"COMMITTED", false, ""},
        {"REJECTED", true, "aborted"}, {"COMPENSATED", false, ""},
        {"CLOSED", true, "success"},
    };
    if (escalate)
      m.states.push_back({"ESCALATED", true, "contested"});

    m.transitions = {
        {"OPEN", "INITIAL", "NEW", {}, "reject"},
        {"NEGOTIATE", "NEW", "NEGOTIATED", {}, "reject"},
        {"PROPOSE", "NEGOTIATED", "PROPOSED", {}, "reject"},
        {"REJECT", "PROPOSED", "REJECTED", {}, "reject"},
        {"AWAIT_QUORUM", "PROPOSED", "QUORUM_PENDING", {}, "reject"},
        {"REACH_QUORUM", "QUORUM_PENDING", "QUORUM_MET", {}, "reject"},
        {"TIMEOUT", "QUORUM_PENDING", "QUORUM_TIMEOUT", {}, "reject"},
        {"COMMIT", "QUORUM_MET", "COMMITTED", {"post"}, "reject"},
        {escalate ? "ESCALATE" : "ABORT",
         "QUORUM_TIMEOUT",
         escalate ? "ESCALATED" : "REJECTED",
         {},
         "reject"},
        {"COMPENSATE", "COMMITTED", "COMPENSATED", {"compensate"}, "reject"},
        {"CLOSE", "COMMITTED", "CLOSED", {}, "reject"},
        {"CLOSE", "COMPENSATED", "CLOSED", {}, "reject"},
    };
    if (escalate)
      m.contestedState = "ESCALATED";
    return m;
  }

  m.states = {
      {"INITIAL", false, ""},     {"NEW", false, ""},
      {"NEGOTIATED", false, ""},  {"PROPOSED", false, ""},
      {"COMMITTED", false, ""},   {"REJECTED", true, "aborted"},
      {"COMPENSATED", false, ""}, {"CLOSED", true, "success"},
  };

  // The fixed OPEN..CLOSE transitions. COMMIT posts; COMPENSATE reverses; CLOSE
  // is reachable from BOTH committed and compensated (so COMPENSATED is not a
  // dead-end non-terminal sink — the exit-completeness the  kernel verifier
  // reserves). Both CLOSE transitions share the operation name, so the
  // operation vocabulary still de-duplicates to one CLOSE.
  m.transitions = {
      {"OPEN", "INITIAL", "NEW", {}, "reject"},
      {"NEGOTIATE", "NEW", "NEGOTIATED", {}, "reject"},
      {"PROPOSE", "NEGOTIATED", "PROPOSED", {}, "reject"},
      {"COMMIT", "PROPOSED", "COMMITTED", {"post"}, "reject"},
      {"REJECT", "PROPOSED", "REJECTED", {}, "reject"},
      {"COMPENSATE", "COMMITTED", "COMPENSATED", {"compensate"}, "reject"},
      {"CLOSE", "COMMITTED", "CLOSED", {}, "reject"},
      {"CLOSE", "COMPENSATED", "CLOSED", {}, "reject"},
  };
  return m;
}

} // namespace neutrino
