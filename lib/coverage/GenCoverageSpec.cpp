//===- GenCoverageSpec.cpp - language coverage + maturity (spec-driven) ---===//
//
// M5  B3 migration (): the `coverage` generation target (Phase 15,
// docs/backends/BACKEND_MATURITY_SPEC.md), reading the frozen capability-spec
// JSON (the  contract) instead of ProcedureView — so this translation unit
// includes NO View.h / Analysis.h and holds no ProcedureView. It derives,
// mechanically, which language levels (L1-L10) a procedure exercises and the
// resulting backend maturity ceiling from spec fields (trigger / effects /
// inputs / participants / invariants), and renders a deterministic
// coverage.json byte-identical to the ProcedureView path it replaces (proved by
// the committed coverage goldens). The numeric-type classification reuses the
// shared value model (ValueModel.h), the same classifier the ProcedureView path
// used, so "is this input numeric" cannot drift between them.
//
// The registry EmitFn entry (CoverageTarget.cpp) emits the spec via
// `capabilitySpecJson`, re-parses it, and calls in here.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenCoverageSpec.h"
#include "Neutrino/ValueModel.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <string>
#include <vector>

using namespace llvm;

namespace {

std::string esc(StringRef s) {
  std::string o;
  for (char c : s) {
    switch (c) {
    case '"':
      o += "\\\"";
      break;
    case '\\':
      o += "\\\\";
      break;
    case '\n':
      o += "\\n";
      break;
    default:
      o += c;
    }
  }
  return o;
}
std::string q(StringRef s) { return "\"" + esc(s) + "\""; }

// "present" is a tri-state: "true" | "false" | "partial" (JSON: bool or
// string).
struct Level {
  const char *id;
  const char *name;
  std::string present; // "true" | "false" | "\"partial\""
  std::string evidence;
  bool networkOwned = false;
};

std::string levelJson(const Level &l) {
  std::string o = "    {\n";
  o += "      \"level\": " + q(l.id) + ",\n";
  o += "      \"name\": " + q(l.name) + ",\n";
  o += "      \"present\": " + l.present + ",\n";
  if (l.networkOwned)
    o += "      \"networkOwned\": true,\n";
  o += "      \"evidence\": " +
       (l.evidence.empty() ? std::string("null") : q(l.evidence)) + "\n";
  o += "    }";
  return o;
}

std::string str(const json::Object &o, StringRef key) {
  return o.getString(key).value_or("").str();
}

} // namespace

std::string neutrino::coverageReportFromSpec(const json::Object &spec) {
  // --- derive feature presence from the capability-spec ---
  bool hasDebit = false, hasCredit = false, hasPartyOperand = false;
  if (const json::Array *effects = spec.getArray("effects"))
    for (const json::Value &ev : *effects)
      if (const json::Object *e = ev.getAsObject()) {
        std::string kind = str(*e, "kind");
        if (kind == "debit")
          hasDebit = true;
        else if (kind == "credit")
          hasCredit = true;
        // a party operand is a %ref (kind == "ref"), not an inline literal.
        if (const json::Object *party = e->getObject("party"))
          if (str(*party, "kind") == "ref" && !str(*party, "value").empty())
            hasPartyOperand = true;
      }
  bool hasValueMovement = hasDebit || hasCredit;

  bool hasNumericInput = false, hasPartyInput = false;
  if (const json::Array *inputs = spec.getArray("inputs"))
    for (const json::Value &iv : *inputs)
      if (const json::Object *in = iv.getAsObject()) {
        std::string ty = str(*in, "type");
        if (isNumericCategory(classifyValueType(ty)))
          hasNumericInput = true;
        if (ty == "party")
          hasPartyInput = true;
      }

  // Distinct declared organizations across participants (abstract topology,
  // L8), in participant-declaration order (cf. orderedNamedOrgs).
  std::vector<std::string> orgs;
  bool hasParticipants = false;
  if (const json::Array *parts = spec.getArray("participants"))
    for (const json::Value &pv : *parts)
      if (const json::Object *p = pv.getAsObject()) {
        hasParticipants = true;
        std::string org = str(*p, "org");
        if (!org.empty() &&
            std::find(orgs.begin(), orgs.end(), org) == orgs.end())
          orgs.push_back(org);
      }
  bool L8abstract = orgs.size() >= 2;

  bool hasEffects = false;
  if (const json::Array *effects = spec.getArray("effects"))
    hasEffects = !effects->empty();
  bool hasTrigger = !str(spec, "trigger").empty();

  bool balanced = false;
  if (const json::Array *invs = spec.getArray("invariants"))
    for (const json::Value &iv : *invs)
      if (const json::Object *i = iv.getAsObject())
        if (str(*i, "kind") == "balanced")
          balanced = true;

  bool L1 = hasTrigger || hasEffects;
  bool L3full = hasParticipants;
  bool L3partial = hasPartyInput || hasPartyOperand;
  bool L4 = hasNumericInput && hasValueMovement;
  bool L5 = balanced && hasDebit && hasCredit;

  // highest exercised level (excluding network-owned / absent levels).
  std::string highest = "L1";
  if (L4)
    highest = "L4";
  if (L5)
    highest = "L5";

  std::vector<Level> levels = {
      {"L1", "Agreements", L1 ? "true" : "false",
       L1 ? "trigger + ledger entries form a coordination agreement" : "",
       false},
      {"L2", "State Machines", "false",
       "no explicit state/transition construct in the current DSL", false},
      {"L3", "Participants",
       L3full ? "true" : (L3partial ? "\"partial\"" : "false"),
       L3full ? "first-class participant declarations (roles + capabilities)"
              : (L3partial ? "typed party inputs and/or party operands; no "
                             "declared roles yet"
                           : ""),
       false},
      {"L4", "Assets & Value", L4 ? "true" : "false",
       L4 ? "numeric (money/decimal) inputs moved by debit/credit legs" : "",
       false},
      {"L5", "Settlement", L5 ? "true" : "false",
       L5 ? "balanced atomic multi-leg posting + reconciliation" : "", false},
      {"L6", "Sagas", "false", "", true},
      {"L7", "Compensation", "false", "", true},
      {"L8", "Topology", L8abstract ? "\"partial\"" : "false",
       L8abstract ? "declared organization boundaries across multiple orgs; "
                    "concrete multi-org execution is network-owned"
                  : "",
       true},
      {"L9", "Capability Discovery", "false", "", true},
      {"L10", "Distributed Coordination", "false", "", true},
  };

  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.language-coverage\",\n";
  o += "  \"schemaVersion\": \"0.1.0\",\n";
  o += "  \"procedure\": " + q(str(spec, "procedure")) + ",\n";
  o += "  \"dslVersion\": " + q(str(spec, "specVersion")) + ",\n";
  o += "  \"levels\": [\n";
  for (size_t i = 0; i < levels.size(); ++i) {
    o += levelJson(levels[i]);
    o += (i + 1 < levels.size() ? ",\n" : "\n");
  }
  o += "  ],\n";
  o += "  \"highestLevel\": " + q(highest) + ",\n";
  o += "  \"networkOwned\": [\"L6\", \"L7\", \"L8\", \"L9\", \"L10\"]\n";
  o += "}\n";
  return o;
}
