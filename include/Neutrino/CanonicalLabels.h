//===- CanonicalLabels.h - stable semantic labels for a coordination plan -===//
//
// The canonical, structural labeling of a `CoordinationPlan`'s value operands,
// observer sets, and ledgers (§2.5). A declared source name is NEVER identity:
// an input name becomes `input:<n>`, an observer set / ledger becomes its
// structural index, assigned by a deterministic `CoordinationPlan` walk. Shared
// by the `coordination-plan` serializer (which established this numbering) and
// the backend projection core (which must produce the SAME canonical leaf
// values so its graph matches the bound traces).
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_CANONICAL_LABELS_H
#define NEUTRINO_CANONICAL_LABELS_H

#include "Neutrino/CoordinationPlan.h"

#include "llvm/ADT/StringRef.h"

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace neutrino {

// Assigns a stable structural label to each value / observer-set / ledger name
// the moment it is first referenced, in a fixed `CoordinationPlan` walk order.
// `value` maps a declared input to `input:<n>` and a compute to `compute:<n>`;
// `observerSet` and `ledger` map a source name to its `<n>` index; `operand`
// rewrites a
// "kind:value" operand, canonicalizing a `ref:<input>` payload. The numbering
// is a pure function of the `CoordinationPlan` and the call order.
class SemanticLabels {
public:
  explicit SemanticLabels(const CoordinationPlan &coordinationPlan)
      : coordinationPlan(coordinationPlan) {
    for (const PlanInput &input : coordinationPlan.inputs)
      inputTypes.emplace(input.name, input.type);
    for (const PlanCompute &compute : coordinationPlan.computes)
      computeNames.insert(compute.name);
  }

  std::string value(llvm::StringRef name) {
    if (name.empty())
      return "";
    if (inputTypes.count(name.str()))
      return "input:" + label(inputLabels, inputOrder, name);
    if (computeNames.count(name.str()))
      return "compute:" + label(computeLabels, computeOrder, name);
    return "unresolved:" + name.str();
  }

  std::string operand(llvm::StringRef encoded) {
    size_t separator = encoded.find(':');
    if (separator == llvm::StringRef::npos)
      return encoded.str();
    llvm::StringRef kind = encoded.take_front(separator);
    llvm::StringRef payload = encoded.drop_front(separator + 1);
    if (kind == "ref")
      return "ref:" + value(payload);
    return encoded.str();
  }

  std::string ledger(llvm::StringRef name) {
    return label(ledgerLabels, ledgerOrder, name);
  }

  std::string observerSet(llvm::StringRef name) {
    return label(observerSetLabels, observerSetOrder, name);
  }

  std::string observerRole(llvm::StringRef name) {
    if (name.empty())
      return "";
    return label(observerRoleLabels, observerRoleOrder, name);
  }

  void completeValues() {
    std::vector<std::pair<std::string, std::string>> remainingInputs;
    for (const PlanInput &input : coordinationPlan.inputs)
      if (!inputLabels.count(input.name))
        remainingInputs.push_back({input.type, input.name});
    std::sort(remainingInputs.begin(), remainingInputs.end());
    for (const auto &[type, name] : remainingInputs)
      (void)value(name);
    for (const PlanCompute &compute : coordinationPlan.computes)
      (void)value(compute.name);
  }

  const std::vector<std::string> &inputs() const { return inputOrder; }
  const std::vector<std::string> &computes() const { return computeOrder; }

private:
  static std::string label(std::map<std::string, size_t> &labels,
                           std::vector<std::string> &order,
                           llvm::StringRef name) {
    auto [it, inserted] = labels.emplace(name.str(), labels.size());
    if (inserted)
      order.push_back(name.str());
    return std::to_string(it->second);
  }

  const CoordinationPlan &coordinationPlan;
  std::map<std::string, std::string> inputTypes;
  std::set<std::string> computeNames;
  std::map<std::string, size_t> inputLabels;
  std::map<std::string, size_t> computeLabels;
  std::map<std::string, size_t> ledgerLabels;
  std::map<std::string, size_t> observerSetLabels;
  std::map<std::string, size_t> observerRoleLabels;
  std::vector<std::string> inputOrder;
  std::vector<std::string> computeOrder;
  std::vector<std::string> ledgerOrder;
  std::vector<std::string> observerSetOrder;
  std::vector<std::string> observerRoleOrder;
};

// Establish the canonical labels the backend projection needs, walking the
// `CoordinationPlan` in the SAME order the coordination-plan serializer does
// for the operand / observer / attestation labels (workflowKey, then each
// effect's operands +
// guard, groups, attestations, computes + deps), then `completeValues()`. The
// trace-relevant labels (operands, observer sets, ledgers) are assigned in this
// early walk, BEFORE any lifecycle deadline references, so this matches the
// /semantics numbering for them exactly. Deadline detail refs are labeled
// best-effort in transition order (they never precede an operand, so they never
// perturb an operand's index).
void establishProjectionLabels(const CoordinationPlan &coordinationPlan,
                               SemanticLabels &labels);

} // namespace neutrino

#endif // NEUTRINO_CANONICAL_LABELS_H
