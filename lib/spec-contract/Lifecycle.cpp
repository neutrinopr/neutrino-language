//===- Lifecycle.cpp - the canonical coordination lifecycle machine -------===//
//
// M5 WP3 (): the single OPEN..CLOSE machine the capability spec and the
// slot artifacts both project from. See Neutrino/Lifecycle.h.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Lifecycle.h"

#include <algorithm>
#include <set>

using namespace llvm;

namespace neutrino {

std::vector<std::string> LifecycleModel::operationNames() const {
  std::vector<std::string> out;
  for (const LifecycleTransition &t : transitions)
    if (std::find(out.begin(), out.end(), t.name) == out.end())
      out.push_back(t.name);
  return out;
}

std::vector<std::string>
LifecycleModel::operationsWithEffect(llvm::StringRef effect) const {
  std::vector<std::string> out;
  for (const LifecycleTransition &t : transitions)
    for (const std::string &e : t.effects)
      if (e == effect && std::find(out.begin(), out.end(), t.name) == out.end())
        out.push_back(t.name);
  return out;
}

std::string LifecycleModel::requiresPrior(llvm::StringRef op) const {
  // The from-states `op` departs from.
  std::set<std::string> froms;
  for (const LifecycleTransition &t : transitions)
    if (t.name == op)
      froms.insert(t.from);
  // An entry op (from the initial state) or a multi-source op (e.g. CLOSE) has
  // no single required predecessor.
  if (froms.size() != 1 || *froms.begin() == initialState)
    return "";
  // The unique operation that produces that from-state.
  const std::string &s = *froms.begin();
  std::string producer;
  for (const LifecycleTransition &t : transitions)
    if (t.to == s) {
      if (!producer.empty() && producer != t.name)
        return ""; // ambiguous producer -> no single predecessor
      producer = t.name;
    }
  return producer;
}

LifecycleModel lifecycleModelFromSpec(const json::Object &spec) {
  LifecycleModel m;
  const json::Object *lc = spec.getObject("lifecycle");
  if (!lc)
    return m;

  if (const json::Object *ik = lc->getObject("instanceKey"))
    if (const json::Array *fields = ik->getArray("fields"))
      for (const json::Value &f : *fields)
        m.instanceKeyFields.push_back(f.getAsString().value_or("").str());

  m.initialState = lc->getString("initialState").value_or("").str();

  if (const json::Array *states = lc->getArray("states"))
    for (const json::Value &sv : *states) {
      const json::Object *s = sv.getAsObject();
      if (!s)
        continue;
      m.states.push_back({s->getString("name").value_or("").str(),
                          s->getBoolean("terminal").value_or(false),
                          s->getString("terminalKind").value_or("").str()});
    }

  if (const json::Array *transitions = lc->getArray("transitions"))
    for (const json::Value &tv : *transitions) {
      const json::Object *t = tv.getAsObject();
      if (!t)
        continue;
      LifecycleTransition tr;
      tr.name = t->getString("name").value_or("").str();
      tr.from = t->getString("from").value_or("").str();
      tr.to = t->getString("to").value_or("").str();
      tr.idempotency = t->getString("idempotency").value_or("reject").str();
      if (const json::Array *effs = t->getArray("effects"))
        for (const json::Value &e : *effs)
          tr.effects.push_back(e.getAsString().value_or("").str());
      m.transitions.push_back(std::move(tr));
    }

  if (const json::Object *term = lc->getObject("terminalStates")) {
    m.successState = term->getString("success").value_or("").str();
    m.abortedState = term->getString("aborted").value_or("").str();
    m.contestedState = term->getString("contested").value_or("").str();
  }
  return m;
}

} // namespace neutrino
