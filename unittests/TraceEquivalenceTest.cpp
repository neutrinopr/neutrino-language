// SPDX-License-Identifier: Apache-2.0
//===- TraceEquivalenceTest.cpp - the normalized-trace comparator ---------===//
//
// Direct assertions on compareTraces (observable agreement + first-divergence
// coordinates) and applyTamper (every defect class the equivalence gate must
// detect surfaces as a divergence — the non-vacuous self-test), plus
// observedFromTransition projecting a real reference trace.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/TraceEquivalence.h"

#include "Neutrino/CoordinationEval.h"

#include "gtest/gtest.h"

using namespace neutrino;

namespace {

// A representative observable trace: two events, two ledgers, one compute, a
// posted key, a success terminal.
ObservedTrace sample() {
  ObservedTrace t;
  t.outcome = "committed";
  t.computed["bonus"] = 101;
  t.events = {"PayOutDebited", "PayInCredited", "ProbeReconciled"};
  t.ledger["a.src"] = -1000;
  t.ledger["b.dst"] = 1000;
  t.terminal = "CLOSED";
  t.postedKeys = {"F-1"};
  return t;
}

} // namespace

TEST(TraceEquivalence, IdenticalTracesAgree) {
  EXPECT_FALSE(compareTraces(sample(), sample()).diverged);
}

TEST(TraceEquivalence, EveryTamperClassDiverges) {
  struct Case {
    TamperKind kind;
    const char *token;
    const char *field;
  };
  for (const Case &c :
       {Case{TamperKind::DropEffect, "drop_effect", "events"},
        Case{TamperKind::AlterAmount, "alter_amount", "ledger"},
        Case{TamperKind::ReorderObs, "reorder_obs", "events"},
        Case{TamperKind::WrongTerminal, "wrong_terminal", "terminal"},
        Case{TamperKind::ReplayOmission, "replay_omission", "postedKeys"},
        Case{TamperKind::PartialCommit, "partial_commit", "ledger"},
        Case{TamperKind::AlterComputed, "alter_computed", "computed"},
        Case{TamperKind::AlterOutcome, "alter_outcome", "outcome"}}) {
    // The CLI token round-trips to the kind.
    TamperKind parsed;
    EXPECT_TRUE(parseTamperKind(c.token, parsed)) << c.token;
    EXPECT_EQ(parsed, c.kind) << c.token;
    // The tamper breaks the trace, and the comparison detects it in the
    // expected field.
    ObservedTrace tampered = sample();
    applyTamper(tampered, c.kind);
    TraceDivergence d = compareTraces(sample(), tampered);
    EXPECT_TRUE(d.diverged) << c.token;
    EXPECT_EQ(d.field, c.field) << c.token;
  }
}

TEST(TraceEquivalence, UnknownTamperTokenRejected) {
  TamperKind k;
  EXPECT_FALSE(parseTamperKind("bogus", k));
}

TEST(TraceEquivalence, DivergenceCarriesCoordinates) {
  ObservedTrace ref = sample();
  ObservedTrace cand = sample();
  cand.ledger["a.src"] = -999; // altered net
  TraceDivergence d = compareTraces(ref, cand);
  EXPECT_TRUE(d.diverged);
  EXPECT_EQ(d.field, "ledger");
  EXPECT_EQ(d.locator, "a.src");
  EXPECT_EQ(d.expected, "-1000");
  EXPECT_EQ(d.actual, "-999");
}

TEST(TraceEquivalence, ProjectsAReferenceTransition) {
  // A minimal balanced coordination, evaluated, then projected: the projection
  // recovers the events + net ledger + committed outcome.
  CoordinationPlan p;
  p.procedure = "probe";
  p.workflowKey = "flow_id";
  p.terminal.success = "CLOSED";
  auto eff = [](const char *name, const char *kind, const char *ledger) {
    PlanEffect e;
    e.name = name;
    e.kind = kind;
    e.ledger = ledger;
    e.amount = "ref:amount";
    e.currency = "ref:currency";
    e.party = "ref:payer";
    return e;
  };
  p.effects.push_back(eff("pay_out", "debit", "a.src"));
  p.effects.push_back(eff("pay_in", "credit", "b.dst"));

  TransitionInput in;
  in.numeric["amount"] = 1000;
  in.symbols["flow_id"] = "F-1";
  in.symbols["payer"] = "buyer";
  in.symbols["currency"] = "EUR";

  ObservedTrace o =
      observedFromTransition(evaluateTransition(p, EvalState{}, in));
  EXPECT_EQ(o.outcome, "committed");
  EXPECT_EQ(o.ledger["a.src"], -1000);
  EXPECT_EQ(o.ledger["b.dst"], 1000);
  EXPECT_EQ(o.terminal, "CLOSED");
  EXPECT_EQ(o.postedKeys.count("F-1"), 1u);
  ASSERT_FALSE(o.events.empty());
  EXPECT_EQ(o.events.front(), "PayOutDebited");
}
