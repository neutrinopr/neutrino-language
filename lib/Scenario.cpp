#include "Neutrino/Scenario.h"

#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"

using namespace neutrino;
using namespace llvm;

static long long asInt(const json::Value &v, const std::string &what) {
  if (auto i = v.getAsInteger())
    return *i;
  throw ScenarioError("scenario.schema", "expected integer for " + what);
}

Scenario neutrino::loadScenario(StringRef path) {
  auto buf = MemoryBuffer::getFile(path);
  if (std::error_code ec = buf.getError())
    throw ScenarioError("scenario.io", "cannot read scenario " + path.str() + ": " + ec.message());

  Expected<json::Value> parsed = json::parse((*buf)->getBuffer());
  if (!parsed)
    throw ScenarioError("scenario.parse", "invalid scenario JSON: " + toString(parsed.takeError()));

  const json::Object *root = parsed->getAsObject();
  if (!root)
    throw ScenarioError("scenario.schema", "scenario must be a JSON object");

  Scenario sc;
  if (auto s = root->getString("scenario"))
    sc.name = s->str();
  if (auto s = root->getString("procedure"))
    sc.procedure = s->str();
  else
    throw ScenarioError("scenario.schema", "scenario missing 'procedure'");

  if (const json::Object *inputs = root->getObject("inputs")) {
    for (const auto &kv : *inputs) {
      ScenarioInput in;
      if (auto i = kv.second.getAsInteger()) {
        in.isInt = true;
        in.i = *i;
      } else if (auto s = kv.second.getAsString()) {
        in.s = s->str();
      } else {
        throw ScenarioError("scenario.schema", "input '" + kv.first.str() + "' must be int or string");
      }
      sc.inputs[kv.first.str()] = in;
    }
  }

  // Per-policy quorum acceptance (). Each key names an attestation policy
  // input; a `false` value UNaccepts it (its accepted()-gated legs suppress). A
  // policy absent here is accepted (validateScenario rejects keys that do not
  // name a declared policy, so a typo cannot silently mean "accepted").
  if (const json::Object *accepted = root->getObject("accepted")) {
    for (const auto &kv : *accepted) {
      auto b = kv.second.getAsBoolean();
      if (!b)
        throw ScenarioError("scenario.schema", "accepted." + kv.first.str() +
                                                   " must be a boolean");
      sc.accepted[kv.first.str()] = *b;
    }
  }

  if (const json::Object *expect = root->getObject("expect")) {
    if (const json::Object *computed = expect->getObject("computed"))
      for (const auto &kv : *computed)
        sc.computed[kv.first.str()] = asInt(kv.second, "computed." + kv.first.str());
    if (const json::Array *events = expect->getArray("events"))
      for (const json::Value &e : *events) {
        auto s = e.getAsString();
        if (!s)
          throw ScenarioError("scenario.schema",
                              "expect.events entries must be strings");
        sc.events.push_back(s->str());
      }
    if (const json::Object *ledger = expect->getObject("ledger"))
      for (const auto &kv : *ledger)
        sc.ledger[kv.first.str()] = asInt(kv.second, "ledger." + kv.first.str());
    if (const json::Array *inv = expect->getArray("invariants"))
      for (const json::Value &e : *inv) {
        auto s = e.getAsString();
        if (!s)
          throw ScenarioError("scenario.schema",
                              "expect.invariants entries must be strings");
        sc.invariants.push_back(s->str());
      }
  }
  return sc;
}
