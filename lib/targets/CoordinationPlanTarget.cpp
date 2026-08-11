//===- CoordinationPlanTarget.cpp - serialize the normalized plan -------===//
//
// The `coordination-plan` target (). It emits the target-neutral
// CoordinationPlan the renderers consume, built DIRECTLY from the verified MLIR
// (normalizePlan) — the single normalized semantic source — as a deterministic
// JSON artifact, so the normalization is observable + FileCheck-pinnable.
// coordinationPlanToText is reused by the --from-spec path so a plan
// reconstructed from an external spec serializes identically.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenCoordinationPlan.h"

#include "Neutrino/BackendProjection.h"
#include "Neutrino/CanonicalLabels.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/CoordinationPlanBuild.h"
#include "Neutrino/ValueModel.h"

#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <set>
#include <tuple>

using namespace llvm;

namespace neutrino {

namespace {
// The observable spelling of the attestation gate mode (): HOW a policy
// gates, decided once in the plan. Emitted so the coordination-plan artifact
// can distinguish an atomic-refuse global gate from a per-policy
// temporal-suppress binding — a distinction `attestation` alone (the bound
// input) cannot show.
const char *gateModeStr(PlanGateMode m) {
  switch (m) {
  case PlanGateMode::None:
    return "none";
  case PlanGateMode::AtomicRefuse:
    return "atomic-refuse";
  case PlanGateMode::TemporalSuppress:
    return "temporal-suppress";
  }
  return "none";
}

json::Value canonicalAuthorizationTopology(const CoordinationPlan &p) {
  std::map<std::string, std::vector<size_t>> participantEffects;
  for (const PlanParticipant &participant : p.participants)
    participantEffects.emplace(participant.name, std::vector<size_t>{});
  for (size_t i = 0; i < p.effects.size(); ++i)
    if (!p.effects[i].participant.empty())
      participantEffects[p.effects[i].participant].push_back(i);

  auto encode = [](const std::vector<size_t> &values) {
    std::string out = std::to_string(values.size()) + ":";
    for (size_t value : values)
      out += std::to_string(value) + ",";
    return out;
  };

  auto colorsFor = [&](const std::string &label, bool organization,
                       const std::vector<size_t> &colors) {
    std::vector<size_t> members;
    if (label.empty())
      return members;
    for (size_t i = 0; i < p.participants.size(); ++i) {
      const PlanParticipant &participant = p.participants[i];
      const std::string &candidate =
          organization ? participant.org : participant.role;
      if (candidate == label)
        members.push_back(colors[i]);
    }
    std::sort(members.begin(), members.end());
    return members;
  };

  // Color refinement uses only fixed effect positions and equality/topology
  // structure. It splits obvious graph positions cheaply; unresolved cells are
  // handled by exact tie backtracking below rather than declaration order.
  std::vector<std::string> initialSignatures;
  for (const PlanParticipant &participant : p.participants)
    initialSignatures.push_back(
        encode(participantEffects.at(participant.name)));
  auto colorize = [](const std::vector<std::string> &signatures) {
    std::map<std::string, size_t> ids;
    for (const std::string &signature : signatures)
      ids.emplace(signature, 0);
    size_t next = 0;
    for (auto &entry : ids)
      entry.second = next++;
    std::vector<size_t> result;
    for (const std::string &signature : signatures)
      result.push_back(ids.at(signature));
    return result;
  };
  std::vector<size_t> colors = colorize(initialSignatures);
  while (true) {
    std::vector<std::string> signatures;
    for (size_t i = 0; i < p.participants.size(); ++i) {
      const PlanParticipant &participant = p.participants[i];
      std::string signature = "C" + std::to_string(colors[i]);
      signature += "|E" + encode(participantEffects.at(participant.name));
      signature +=
          participant.org.empty()
              ? "|ON"
              : "|O" + encode(colorsFor(participant.org, true, colors));
      signature +=
          participant.role.empty()
              ? "|RN"
              : "|R" + encode(colorsFor(participant.role, false, colors));
      std::vector<std::string> incidents;
      auto addIncident = [&](const PlanOrgPolicy &edge, bool atA) {
        const std::string &otherOrg = atA ? edge.orgB : edge.orgA;
        const std::string &ownRole = atA ? edge.roleA : edge.roleB;
        const std::string &otherRole = atA ? edge.roleB : edge.roleA;
        incidents.push_back(
            encode(colorsFor(otherOrg, true, colors)) + "/" +
            (ownRole.empty() ? "N"
                             : encode(colorsFor(ownRole, false, colors))) +
            "/" +
            (otherRole.empty() ? "N"
                               : encode(colorsFor(otherRole, false, colors))));
      };
      for (const PlanOrgPolicy &edge : p.allowedOrgPairs) {
        if (edge.orgA == participant.org)
          addIncident(edge, true);
        if (edge.orgB == participant.org)
          addIncident(edge, false);
      }
      std::sort(incidents.begin(), incidents.end());
      for (const std::string &incident : incidents)
        signature += "|I" + incident;
      signatures.push_back(std::move(signature));
    }
    std::vector<size_t> refined = colorize(signatures);
    if (refined == colors)
      break;
    colors = std::move(refined);
  }

  using Actor =
      std::tuple<std::optional<size_t>, std::optional<size_t>>; // org, role
  using Binding = std::pair<size_t, size_t>;                    // effect, actor
  using Edge =
      std::tuple<size_t, size_t, std::optional<size_t>, std::optional<size_t>>;
  using Projection =
      std::tuple<std::vector<Actor>, std::vector<Binding>, std::vector<Edge>>;

  auto project = [&](const std::vector<size_t> &order) {
    std::map<std::string, size_t> participantIds;
    for (size_t i = 0; i < order.size(); ++i)
      participantIds[p.participants[order[i]].name] = i;

    std::map<std::string, std::vector<size_t>> organizationMembers;
    for (const PlanParticipant &participant : p.participants)
      if (!participant.org.empty())
        organizationMembers[participant.org].push_back(
            participantIds.at(participant.name));
    std::vector<std::pair<std::vector<size_t>, std::string>> organizations;
    for (auto &entry : organizationMembers) {
      std::sort(entry.second.begin(), entry.second.end());
      organizations.push_back({entry.second, entry.first});
    }
    std::sort(organizations.begin(), organizations.end(),
              [](const auto &a, const auto &b) { return a.first < b.first; });
    std::map<std::string, size_t> orgIds;
    for (size_t i = 0; i < organizations.size(); ++i)
      orgIds[organizations[i].second] = i;

    using RoleKey =
        std::tuple<std::vector<size_t>, std::vector<std::pair<size_t, size_t>>>;
    std::map<std::string, RoleKey> roleKeys;
    for (const PlanParticipant &participant : p.participants)
      if (!participant.role.empty())
        std::get<0>(roleKeys[participant.role])
            .push_back(participantIds.at(participant.name));
    for (const PlanOrgPolicy &edge : p.allowedOrgPairs) {
      size_t orgA = orgIds.at(edge.orgA);
      size_t orgB = orgIds.at(edge.orgB);
      if (!edge.roleA.empty())
        std::get<1>(roleKeys[edge.roleA]).push_back({orgA, orgB});
      if (!edge.roleB.empty())
        std::get<1>(roleKeys[edge.roleB]).push_back({orgB, orgA});
    }
    std::vector<std::pair<RoleKey, std::string>> roles;
    for (auto &entry : roleKeys) {
      std::sort(std::get<0>(entry.second).begin(),
                std::get<0>(entry.second).end());
      std::sort(std::get<1>(entry.second).begin(),
                std::get<1>(entry.second).end());
      roles.push_back({entry.second, entry.first});
    }
    std::sort(roles.begin(), roles.end(),
              [](const auto &a, const auto &b) { return a.first < b.first; });
    std::map<std::string, size_t> roleIds;
    for (size_t i = 0; i < roles.size(); ++i)
      roleIds[roles[i].second] = i;

    std::vector<Actor> actors;
    for (size_t index : order) {
      const PlanParticipant &participant = p.participants[index];
      std::optional<size_t> org;
      std::optional<size_t> role;
      if (!participant.org.empty())
        org = orgIds.at(participant.org);
      if (!participant.role.empty())
        role = roleIds.at(participant.role);
      actors.emplace_back(org, role);
    }
    std::vector<Binding> bindings;
    for (size_t i = 0; i < p.effects.size(); ++i)
      if (!p.effects[i].participant.empty())
        bindings.push_back({i, participantIds.at(p.effects[i].participant)});

    std::vector<Edge> edges;
    for (const PlanOrgPolicy &edge : p.allowedOrgPairs) {
      size_t orgA = orgIds.at(edge.orgA);
      size_t orgB = orgIds.at(edge.orgB);
      std::optional<size_t> roleA;
      std::optional<size_t> roleB;
      if (!edge.roleA.empty())
        roleA = roleIds.at(edge.roleA);
      if (!edge.roleB.empty())
        roleB = roleIds.at(edge.roleB);
      if (std::tie(orgB, roleB) < std::tie(orgA, roleA)) {
        std::swap(orgA, orgB);
        std::swap(roleA, roleB);
      }
      edges.emplace_back(orgA, orgB, roleA, roleB);
    }
    std::sort(edges.begin(), edges.end());
    return Projection{std::move(actors), std::move(bindings), std::move(edges)};
  };

  std::map<size_t, std::vector<size_t>> cells;
  for (size_t i = 0; i < colors.size(); ++i)
    cells[colors[i]].push_back(i);
  std::vector<std::vector<size_t>> orderedCells;
  for (auto &entry : cells) {
    std::sort(entry.second.begin(), entry.second.end());
    orderedCells.push_back(std::move(entry.second));
  }

  std::optional<Projection> best;
  std::vector<size_t> order;
  std::function<void(size_t)> search = [&](size_t cellIndex) {
    if (cellIndex == orderedCells.size()) {
      Projection candidate = project(order);
      if (!best || candidate < *best)
        best = std::move(candidate);
      return;
    }
    std::vector<size_t> permutation = orderedCells[cellIndex];
    do {
      order.insert(order.end(), permutation.begin(), permutation.end());
      search(cellIndex + 1);
      order.resize(order.size() - permutation.size());
    } while (std::next_permutation(permutation.begin(), permutation.end()));
  };
  search(0);
  if (!best)
    best = project({});

  json::Array participants;
  const std::vector<Actor> &actors = std::get<0>(*best);
  for (size_t i = 0; i < actors.size(); ++i) {
    auto [org, role] = actors[i];
    participants.push_back(json::Object{
        {"actor", (int64_t)i},
        {"org", org ? json::Value((int64_t)*org) : json::Value(nullptr)},
        {"role", role ? json::Value((int64_t)*role) : json::Value(nullptr)}});
  }
  json::Array effectBindings;
  for (const Binding &binding : std::get<1>(*best))
    effectBindings.push_back(json::Object{{"effect", (int64_t)binding.first},
                                          {"actor", (int64_t)binding.second}});
  json::Array allowedEdges;
  for (const Edge &edge : std::get<2>(*best)) {
    auto [orgA, orgB, roleA, roleB] = edge;
    allowedEdges.push_back(json::Object{
        {"orgA", (int64_t)orgA},
        {"orgB", (int64_t)orgB},
        {"roleA", roleA ? json::Value((int64_t)*roleA) : json::Value(nullptr)},
        {"roleB",
         roleB ? json::Value((int64_t)*roleB) : json::Value(nullptr)}});
  }
  return json::Object{{"actors", std::move(participants)},
                      {"effectBindings", std::move(effectBindings)},
                      {"allowedOrgEdges", std::move(allowedEdges)}};
}

// SemanticLabels now lives in Neutrino/CanonicalLabels.h (shared with the
// backend projection core so both use the SAME canonical numbering).

json::Value semanticExpr(const ExprNode *node, SemanticLabels &labels) {
  if (!node)
    return nullptr;
  json::Object result{{"dtype", categoryName(node->dtype).str()}};
  switch (node->kind) {
  case ExprNode::Num:
    result["kind"] = "number";
    result["value"] = node->num;
    break;
  case ExprNode::Var:
    result["kind"] = "value";
    result["value"] = labels.value(node->name);
    break;
  case ExprNode::Bin:
    result["kind"] = "binary";
    result["operator"] = std::string(1, node->op);
    result["left"] = semanticExpr(node->lhs.get(), labels);
    result["right"] = semanticExpr(node->rhs.get(), labels);
    break;
  case ExprNode::Cmp:
    result["kind"] = "compare";
    result["operator"] = node->name;
    result["left"] = semanticExpr(node->lhs.get(), labels);
    result["right"] = semanticExpr(node->rhs.get(), labels);
    break;
  case ExprNode::Call: {
    result["kind"] = "call";
    result["function"] = node->name;
    json::Array args;
    for (const auto &arg : node->args)
      args.push_back(semanticExpr(arg.get(), labels));
    result["arguments"] = std::move(args);
    break;
  }
  }
  return result;
}

void appendKey(std::string &key, llvm::StringRef value) {
  key += std::to_string(value.size());
  key += ':';
  key += value.str();
}

std::string inputType(const CoordinationPlan &plan, llvm::StringRef name) {
  for (const PlanInput &input : plan.inputs)
    if (input.name == name)
      return input.type;
  return "<unresolved>";
}

std::string transitionPayloadKey(const CoordinationPlan &plan,
                                 const LifecycleTransitionPolicy &transition) {
  std::string key;
  for (const std::string &effect : transition.effects)
    appendKey(key, effect);
  key += '|';
  for (const LifecycleTransitionGuardPolicy &guard : transition.guards) {
    appendKey(key, guard.kind);
    // A deadline detail is a value identity. Use its verified type while
    // ordering the graph; the identity itself is structurally assigned after
    // the graph order is known. Other closed-vocabulary details are semantic
    // literals and remain exact.
    appendKey(key, guard.kind == "deadline" && !guard.detail.empty()
                       ? inputType(plan, guard.detail)
                       : guard.detail);
  }
  key += '|';
  appendKey(key, transition.idempotency);
  key += '|';
  if (transition.evidence) {
    appendKey(key, transition.evidence->style);
    key += transition.evidence->chained ? '1' : '0';
  } else {
    key += '-';
  }
  return key;
}

std::vector<size_t>
canonicalColors(const std::vector<std::string> &signatures) {
  std::vector<std::string> ordered = signatures;
  std::sort(ordered.begin(), ordered.end());
  ordered.erase(std::unique(ordered.begin(), ordered.end()), ordered.end());
  std::vector<size_t> colors;
  colors.reserve(signatures.size());
  for (const std::string &signature : signatures)
    colors.push_back(
        std::lower_bound(ordered.begin(), ordered.end(), signature) -
        ordered.begin());
  return colors;
}

std::string jsonKey(const json::Value &value) {
  std::string text;
  raw_string_ostream os(text);
  os << formatv("{0}", value);
  return os.str();
}

struct LifecycleCandidate {
  std::string key;
  std::vector<size_t> stateOrder;
  std::vector<size_t> stateIds;
  std::vector<size_t> operationIds;
  std::vector<size_t> transitionOrder;
  std::vector<std::string> deadlineOrder;
};

json::Value encodeLifecycle(const CoordinationPlan &plan,
                            const LifecycleCandidate &candidate,
                            SemanticLabels &labels) {
  for (const std::string &deadline : candidate.deadlineOrder)
    (void)labels.value(deadline);

  json::Array transitions;
  std::vector<std::pair<std::string, json::Value>> orderedTransitions;
  for (size_t transitionIndex : candidate.transitionOrder) {
    const LifecycleTransitionPolicy &transition =
        plan.lifecycleTransitions[transitionIndex];
    json::Array effects;
    for (const std::string &effect : transition.effects)
      effects.push_back(effect);
    json::Array guards;
    for (const LifecycleTransitionGuardPolicy &guard : transition.guards) {
      std::string detail = guard.detail;
      if (guard.kind == "deadline" && !guard.detail.empty())
        detail = labels.value(guard.detail);
      guards.push_back(json::Object{{"kind", guard.kind}, {"detail", detail}});
    }
    json::Object encoded{
        {"operation", (int64_t)candidate.operationIds[transitionIndex]},
        {"from", (int64_t)candidate.stateIds.at(
                     std::find(plan.lifecycleStates.begin(),
                               plan.lifecycleStates.end(), transition.from) -
                     plan.lifecycleStates.begin())},
        {"to", (int64_t)candidate.stateIds.at(
                   std::find(plan.lifecycleStates.begin(),
                             plan.lifecycleStates.end(), transition.to) -
                   plan.lifecycleStates.begin())},
        {"effects", std::move(effects)},
        {"guards", std::move(guards)},
        {"idempotency", transition.idempotency}};
    if (transition.evidence)
      encoded["evidence"] =
          json::Object{{"style", transition.evidence->style},
                       {"chained", transition.evidence->chained}};
    json::Value encodedValue(std::move(encoded));
    std::string key = jsonKey(encodedValue);
    orderedTransitions.push_back({std::move(key), std::move(encodedValue)});
  }
  std::sort(orderedTransitions.begin(), orderedTransitions.end(),
            [](const auto &left, const auto &right) {
              return left.first < right.first;
            });
  for (auto &entry : orderedTransitions)
    transitions.push_back(std::move(entry.second));

  auto stateId = [&](llvm::StringRef name) -> json::Value {
    if (name.empty())
      return nullptr;
    auto it = std::find(plan.lifecycleStates.begin(),
                        plan.lifecycleStates.end(), name);
    return (int64_t)candidate.stateIds.at(it - plan.lifecycleStates.begin());
  };
  json::Array states;
  for (size_t id = 0; id < candidate.stateOrder.size(); ++id) {
    size_t source = candidate.stateOrder[id];
    const std::string &name = plan.lifecycleStates[source];
    states.push_back(
        json::Object{{"id", (int64_t)id},
                     {"initial", name == plan.lifecycleInitialState},
                     {"success", name == plan.terminal.success},
                     {"aborted", name == plan.terminal.aborted},
                     {"contested", name == plan.terminal.contested}});
  }
  return json::Object{
      {"initialState", stateId(plan.lifecycleInitialState)},
      {"states", std::move(states)},
      {"terminal",
       json::Object{{"success", stateId(plan.terminal.success)},
                    {"aborted", stateId(plan.terminal.aborted)},
                    {"contested", stateId(plan.terminal.contested)}}},
      {"transitions", std::move(transitions)}};
}

Expected<json::Value> canonicalLifecycle(const CoordinationPlan &plan,
                                         SemanticLabels &labels) {
  if (plan.lifecycleStates.empty())
    return json::Object{{"initialState", nullptr},
                        {"states", json::Array()},
                        {"terminal", json::Object{{"success", nullptr},
                                                  {"aborted", nullptr},
                                                  {"contested", nullptr}}},
                        {"transitions", json::Array()}};

  std::map<std::string, size_t> stateIndices;
  for (size_t i = 0; i < plan.lifecycleStates.size(); ++i)
    stateIndices.emplace(plan.lifecycleStates[i], i);
  std::map<std::string, size_t> operationIndices;
  for (const LifecycleTransitionPolicy &transition : plan.lifecycleTransitions)
    operationIndices.emplace(transition.name, operationIndices.size());

  std::vector<std::string> payloads;
  std::vector<size_t> transitionOperations;
  for (const LifecycleTransitionPolicy &transition :
       plan.lifecycleTransitions) {
    payloads.push_back(transitionPayloadKey(plan, transition));
    transitionOperations.push_back(operationIndices.at(transition.name));
  }

  std::vector<std::string> baseStateSignatures;
  for (const std::string &state : plan.lifecycleStates) {
    std::string signature;
    signature += state == plan.lifecycleInitialState ? '1' : '0';
    signature += state == plan.terminal.success ? '1' : '0';
    signature += state == plan.terminal.aborted ? '1' : '0';
    signature += state == plan.terminal.contested ? '1' : '0';
    baseStateSignatures.push_back(std::move(signature));
  }
  std::vector<size_t> stateColors = canonicalColors(baseStateSignatures);
  std::vector<size_t> operationColors(operationIndices.size(), 0);
  while (true) {
    std::vector<std::vector<std::string>> operationEdges(
        operationIndices.size());
    for (size_t i = 0; i < plan.lifecycleTransitions.size(); ++i) {
      const LifecycleTransitionPolicy &transition =
          plan.lifecycleTransitions[i];
      std::string edge = payloads[i];
      edge +=
          "|f" + std::to_string(stateColors[stateIndices.at(transition.from)]);
      edge +=
          "|t" + std::to_string(stateColors[stateIndices.at(transition.to)]);
      operationEdges[transitionOperations[i]].push_back(std::move(edge));
    }
    std::vector<std::string> operationSignatures(operationIndices.size());
    for (size_t i = 0; i < operationEdges.size(); ++i) {
      // Operation identity is an equality relation over edges, not its source
      // spelling. Sorting the per-operation edge multiset makes it canonical.
      // The outer refinement will distinguish otherwise different groups.
      std::sort(operationEdges[i].begin(), operationEdges[i].end());
      for (const std::string &edge : operationEdges[i])
        appendKey(operationSignatures[i], edge);
    }
    std::vector<size_t> nextOperationColors =
        canonicalColors(operationSignatures);

    std::vector<std::vector<std::string>> stateEdges(stateColors.size());
    for (size_t i = 0; i < plan.lifecycleTransitions.size(); ++i) {
      const LifecycleTransitionPolicy &transition =
          plan.lifecycleTransitions[i];
      size_t from = stateIndices.at(transition.from);
      size_t to = stateIndices.at(transition.to);
      std::string out =
          "o" + std::to_string(nextOperationColors[transitionOperations[i]]) +
          ":" + std::to_string(stateColors[to]) + ":" + payloads[i];
      std::string in =
          "i" + std::to_string(nextOperationColors[transitionOperations[i]]) +
          ":" + std::to_string(stateColors[from]) + ":" + payloads[i];
      stateEdges[from].push_back(std::move(out));
      stateEdges[to].push_back(std::move(in));
    }
    std::vector<std::string> stateSignatures = baseStateSignatures;
    for (size_t i = 0; i < stateEdges.size(); ++i) {
      std::sort(stateEdges[i].begin(), stateEdges[i].end());
      for (const std::string &edge : stateEdges[i])
        appendKey(stateSignatures[i], edge);
    }
    std::vector<size_t> nextStateColors = canonicalColors(stateSignatures);
    if (nextStateColors == stateColors &&
        nextOperationColors == operationColors)
      break;
    stateColors = std::move(nextStateColors);
    operationColors = std::move(nextOperationColors);
  }

  std::map<size_t, std::vector<size_t>> cells;
  for (size_t i = 0; i < stateColors.size(); ++i)
    cells[stateColors[i]].push_back(i);
  std::vector<std::vector<size_t>> orderedCells;
  for (auto &entry : cells)
    orderedCells.push_back(std::move(entry.second));

  // Exact tie handling is deliberately bounded. The committed generated
  // corpus refines every lifecycle state to a singleton; allowing up to 4096
  // candidate labelings leaves ample forward room while refusing an external
  // graph before factorial backtracking can become an availability attack.
  constexpr size_t kMaxCanonicalLifecyclePermutations = 4096;
  size_t permutations = 1;
  for (const std::vector<size_t> &cell : orderedCells)
    for (size_t factor = 2; factor <= cell.size(); ++factor) {
      if (permutations > kMaxCanonicalLifecyclePermutations / factor)
        return createStringError(
            inconvertibleErrorCode(),
            "lifecycle graph requires more than %zu canonical tie "
            "permutations",
            kMaxCanonicalLifecyclePermutations);
      permutations *= factor;
    }

  std::optional<LifecycleCandidate> best;
  std::vector<size_t> stateOrder;
  std::function<void(size_t)> search = [&](size_t cellIndex) {
    if (cellIndex != orderedCells.size()) {
      std::vector<size_t> permutation = orderedCells[cellIndex];
      do {
        stateOrder.insert(stateOrder.end(), permutation.begin(),
                          permutation.end());
        search(cellIndex + 1);
        stateOrder.resize(stateOrder.size() - permutation.size());
      } while (std::next_permutation(permutation.begin(), permutation.end()));
      return;
    }

    LifecycleCandidate candidate;
    candidate.stateOrder = stateOrder;
    candidate.stateIds.resize(stateOrder.size());
    for (size_t i = 0; i < stateOrder.size(); ++i)
      candidate.stateIds[stateOrder[i]] = i;

    std::vector<std::vector<std::string>> operationEdges(
        operationIndices.size());
    for (size_t i = 0; i < plan.lifecycleTransitions.size(); ++i) {
      const LifecycleTransitionPolicy &transition =
          plan.lifecycleTransitions[i];
      std::string edge = payloads[i];
      edge += "|f" + std::to_string(
                         candidate.stateIds[stateIndices.at(transition.from)]);
      edge += "|t" + std::to_string(
                         candidate.stateIds[stateIndices.at(transition.to)]);
      operationEdges[transitionOperations[i]].push_back(std::move(edge));
    }
    std::vector<std::string> operationSignatures(operationIndices.size());
    for (size_t i = 0; i < operationEdges.size(); ++i) {
      std::sort(operationEdges[i].begin(), operationEdges[i].end());
      for (const std::string &edge : operationEdges[i])
        appendKey(operationSignatures[i], edge);
    }
    std::vector<std::pair<std::string, size_t>> orderedOperations;
    for (size_t i = 0; i < operationSignatures.size(); ++i)
      orderedOperations.push_back({operationSignatures[i], i});
    std::sort(orderedOperations.begin(), orderedOperations.end());
    std::vector<size_t> operationIds(operationIndices.size());
    for (size_t i = 0; i < orderedOperations.size(); ++i)
      operationIds[orderedOperations[i].second] = i;
    candidate.operationIds.resize(plan.lifecycleTransitions.size());

    std::vector<std::pair<std::string, size_t>> orderedTransitions;
    for (size_t i = 0; i < plan.lifecycleTransitions.size(); ++i) {
      const LifecycleTransitionPolicy &transition =
          plan.lifecycleTransitions[i];
      candidate.operationIds[i] = operationIds[transitionOperations[i]];
      std::string edge =
          std::to_string(candidate.operationIds[i]) + ":" +
          std::to_string(candidate.stateIds[stateIndices.at(transition.from)]) +
          ":" +
          std::to_string(candidate.stateIds[stateIndices.at(transition.to)]) +
          ":" + payloads[i];
      orderedTransitions.push_back({std::move(edge), i});
    }
    std::sort(orderedTransitions.begin(), orderedTransitions.end());
    for (const auto &entry : orderedTransitions)
      candidate.transitionOrder.push_back(entry.second);

    std::map<std::string, std::vector<std::string>> deadlineUses;
    for (size_t transitionIndex : candidate.transitionOrder) {
      const LifecycleTransitionPolicy &transition =
          plan.lifecycleTransitions[transitionIndex];
      for (size_t guardIndex = 0; guardIndex < transition.guards.size();
           ++guardIndex) {
        const LifecycleTransitionGuardPolicy &guard =
            transition.guards[guardIndex];
        if (guard.kind == "deadline" && !guard.detail.empty())
          deadlineUses[guard.detail].push_back(
              std::to_string(candidate.operationIds[transitionIndex]) + ":" +
              std::to_string(
                  candidate.stateIds[stateIndices.at(transition.from)]) +
              ":" +
              std::to_string(
                  candidate.stateIds[stateIndices.at(transition.to)]) +
              ":" + std::to_string(guardIndex));
      }
    }
    std::vector<std::pair<std::string, std::string>> orderedDeadlines;
    for (auto &entry : deadlineUses) {
      std::sort(entry.second.begin(), entry.second.end());
      std::string signature;
      for (const std::string &use : entry.second)
        appendKey(signature, use);
      orderedDeadlines.push_back({std::move(signature), entry.first});
    }
    std::sort(orderedDeadlines.begin(), orderedDeadlines.end());
    for (const auto &entry : orderedDeadlines)
      candidate.deadlineOrder.push_back(entry.second);

    SemanticLabels candidateLabels = labels;
    json::Value encoded = encodeLifecycle(plan, candidate, candidateLabels);
    candidate.key = jsonKey(encoded);
    if (!best || candidate.key < best->key)
      best = std::move(candidate);
  };
  search(0);
  return encodeLifecycle(plan, *best, labels);
}

Expected<json::Value> canonicalPlanSemanticsImpl(const CoordinationPlan &p) {
  SemanticLabels labels(p);
  std::string workflowKey = labels.value(p.workflowKey);
  std::string explicitInstanceKey =
      p.explicitInstanceKey.empty() ? "" : labels.value(p.explicitInstanceKey);

  json::Array effects;
  for (const PlanEffect &effect : p.effects) {
    json::Object encoded{
        {"kind", effect.kind},
        {"ledger", labels.ledger(effect.ledger)},
        {"party", labels.operand(effect.party)},
        {"amount", labels.operand(effect.amount)},
        {"currency", labels.operand(effect.currency)},
        {"memo", effect.memo},
        {"guard", semanticExpr(effect.guard.get(), labels)},
        {"gateMode", gateModeStr(effect.gateMode)},
        {"gatePolicy",
         effect.gatePolicy.empty() ? "" : labels.value(effect.gatePolicy)},
        {"attestation", effect.attestationInput.empty()
                            ? ""
                            : labels.value(effect.attestationInput)}};
    effects.push_back(std::move(encoded));
  }

  json::Array groups;
  for (const PlanEffectGroup &group : p.effectGroups) {
    json::Array members;
    for (size_t effect : group.effectIndices)
      members.push_back((int64_t)effect);
    json::Value guard = nullptr;
    if (!group.effectIndices.empty())
      guard = semanticExpr(p.effects[group.effectIndices.front()].guard.get(),
                           labels);
    groups.push_back(json::Object{
        {"effects", std::move(members)},
        {"guard", std::move(guard)},
        {"gateMode", gateModeStr(group.gateMode)},
        {"gatePolicy",
         group.gatePolicy.empty() ? "" : labels.value(group.gatePolicy)},
        {"attestation", group.attestationInput.empty()
                            ? ""
                            : labels.value(group.attestationInput)},
        {"mustBalance", group.mustBalance},
        {"debits", (int64_t)group.debitCount},
        {"credits", (int64_t)group.creditCount}});
  }

  json::Array attestations;
  for (const AttestationPolicy &policy : p.attestations) {
    attestations.push_back(
        json::Object{{"input", labels.value(policy.input)},
                     {"quorum", policy.quorum},
                     {"observerSet", labels.observerSet(policy.observerSet)},
                     {"observerRole", labels.observerRole(policy.observerRole)},
                     {"assurance", policy.assurance},
                     {"independence", policy.independence},
                     {"canonicalization", policy.canonicalization},
                     {"tolerance", policy.tolerance},
                     {"timeout", policy.timeout},
                     {"fallback", policy.fallback}});
  }

  std::map<std::string, const PlanCompute *> computesByName;
  for (const PlanCompute &compute : p.computes) {
    computesByName.emplace(compute.name, &compute);
    (void)labels.value(compute.name);
  }
  json::Array computes;
  for (size_t i = 0; i < labels.computes().size(); ++i) {
    const PlanCompute &compute = *computesByName.at(labels.computes()[i]);
    json::Array deps;
    for (const std::string &dep : compute.deps)
      deps.push_back(labels.value(dep));
    computes.push_back(
        json::Object{{"id", (int64_t)i},
                     {"category", compute.category},
                     {"dependencies", std::move(deps)},
                     {"expression", semanticExpr(compute.expr.get(), labels)}});
  }

  Expected<json::Value> lifecycle = canonicalLifecycle(p, labels);
  if (!lifecycle)
    return lifecycle.takeError();

  // Complete the inventory only after every semantic operand (including
  // compute and lifecycle deadline references) has had a chance to establish
  // its structural label. Remaining unused declarations are indistinguishable
  // except for their type and therefore cannot influence another field.
  labels.completeValues();
  std::map<std::string, const PlanInput *> inputsByName;
  for (const PlanInput &input : p.inputs)
    inputsByName.emplace(input.name, &input);
  json::Array inputs;
  for (size_t i = 0; i < labels.inputs().size(); ++i) {
    const PlanInput &input = *inputsByName.at(labels.inputs()[i]);
    ValueCategory category = classifyValueType(input.type);
    inputs.push_back(json::Object{{"id", (int64_t)i},
                                  {"type", input.type},
                                  {"category", categoryName(category).str()},
                                  {"temporal", isTemporalType(input.type)}});
  }

  return json::Object{
      {"schemaVersion", 1},
      {"inputs", std::move(inputs)},
      {"authorizationTopology", canonicalAuthorizationTopology(p)},
      {"workflowKey", workflowKey},
      {"explicitInstanceKey", explicitInstanceKey},
      {"evidenceOnly", p.evidenceOnly},
      {"balanced", p.balanced},
      {"replay", json::Object{{"key", labels.value(p.replay.key)},
                              {"idempotent", p.replay.idempotent}}},
      {"effects", std::move(effects)},
      {"effectGroups", std::move(groups)},
      {"computes", std::move(computes)},
      {"attestations", std::move(attestations)},
      {"lifecycle", std::move(*lifecycle)}};
}

Expected<json::Value> planToJson(const CoordinationPlan &p) {
  json::Array effects;
  for (const PlanEffect &e : p.effects)
    effects.push_back(json::Object{{"index", (int64_t)e.index},
                                   {"name", e.name},
                                   {"kind", e.kind},
                                   {"guard", e.canonicalGuard},
                                   {"guardKey", e.guardKey},
                                   {"attestation", e.attestationInput},
                                   {"gateMode", gateModeStr(e.gateMode)},
                                   {"gatePolicy", e.gatePolicy}});
  json::Array groups;
  for (const PlanEffectGroup &g : p.effectGroups) {
    json::Array idx;
    for (size_t i : g.effectIndices)
      idx.push_back((int64_t)i);
    groups.push_back(json::Object{{"guard", g.canonicalGuard},
                                  {"guardKey", g.guardKey},
                                  {"attestation", g.attestationInput},
                                  {"gateMode", gateModeStr(g.gateMode)},
                                  {"gatePolicy", g.gatePolicy},
                                  {"firstIndex", (int64_t)g.firstIndex},
                                  {"mustBalance", g.mustBalance},
                                  {"debits", (int64_t)g.debitCount},
                                  {"credits", (int64_t)g.creditCount},
                                  {"effects", std::move(idx)}});
  }
  json::Array computes;
  for (const PlanCompute &c : p.computes) {
    json::Array deps;
    for (const std::string &d : c.deps)
      deps.push_back(d);
    // The compute EXPRESSION's canonical structural key ( P1): serializing
    // it makes the MLIR<->external-spec 3-way plan diff non-vacuous — two
    // different reconstructed trees now produce different plan bytes.
    computes.push_back(
        json::Object{{"name", c.name},
                     {"category", c.category},
                     {"exprKey", canonicalGuardKey(c.expr.get())},
                     {"deps", std::move(deps)}});
  }
  json::Array policies;
  for (const AttestationPolicy &ap : p.attestations)
    policies.push_back(ap.input);
  json::Array participants;
  for (const PlanParticipant &participant : p.participants)
    participants.push_back(json::Object{{"name", participant.name},
                                        {"role", participant.role},
                                        {"org", participant.org}});
  json::Array allowedOrgPairs;
  for (const PlanOrgPolicy &edge : p.allowedOrgPairs)
    allowedOrgPairs.push_back(json::Object{{"orgA", edge.orgA},
                                           {"orgB", edge.orgB},
                                           {"roleA", edge.roleA},
                                           {"roleB", edge.roleB}});
  json::Array lifecycleTransitions;
  for (const LifecycleTransitionPolicy &t : p.lifecycleTransitions) {
    json::Array transitionEffects;
    for (const std::string &effect : t.effects)
      transitionEffects.push_back(effect);
    json::Array transitionGuards;
    for (const LifecycleTransitionGuardPolicy &guard : t.guards) {
      json::Object guardJson{{"kind", guard.kind}};
      if (!guard.detail.empty())
        guardJson["detail"] = guard.detail;
      transitionGuards.push_back(std::move(guardJson));
    }
    json::Object transitionJson{{"name", t.name},
                                {"from", t.from},
                                {"to", t.to},
                                {"effects", std::move(transitionEffects)},
                                {"guards", std::move(transitionGuards)},
                                {"idempotency", t.idempotency}};
    if (t.evidence)
      transitionJson["evidence"] = json::Object{
          {"style", t.evidence->style}, {"chained", t.evidence->chained}};
    lifecycleTransitions.push_back(std::move(transitionJson));
  }
  json::Array lifecycleStates;
  for (const std::string &state : p.lifecycleStates)
    lifecycleStates.push_back(state);
  // Obligations (): serialized ONLY when present (omit-when-empty), so an
  // obligation-free plan's bytes/hash are byte-identical to before. Effect
  // order is part of the obligation identity, so `effects` is an ordered array.
  // The predicate is serialized by its structural key (the compute `exprKey`
  // pattern) to keep the 3-way plan diff non-vacuous.
  json::Array obligations;
  for (const PlanObligation &o : p.obligations) {
    json::Array effs;
    for (const std::string &en : o.effects)
      effs.push_back(en);
    json::Array statuses;
    for (const std::string &st : o.statuses)
      statuses.push_back(st);
    obligations.push_back(json::Object{{"version", (int64_t)o.version},
                                       {"name", o.name},
                                       {"obligor", o.obligor},
                                       {"beneficiary", o.beneficiary},
                                       {"authority", o.authority},
                                       {"guard", o.canonicalGuard},
                                       {"guardKey", o.guardKey},
                                       {"effects", std::move(effs)},
                                       {"statuses", std::move(statuses)}});
  }
  Expected<json::Value> semantics = canonicalPlanSemanticsImpl(p);
  if (!semantics)
    return semantics.takeError();
  json::Object out{
      {"procedure", p.procedure},
      {"participants", std::move(participants)},
      {"allowedOrgPairs", std::move(allowedOrgPairs)},
      {"authorizationTopology", canonicalAuthorizationTopology(p)},
      {"semantics", std::move(*semantics)},
      {"workflowKey", p.workflowKey},
      {"balanced", p.balanced},
      {"attested", !p.attestations.empty()},
      {"replay", json::Object{{"key", p.replay.key},
                              {"idempotent", p.replay.idempotent}}},
      {"terminal", json::Object{{"success", p.terminal.success},
                                {"aborted", p.terminal.aborted},
                                {"contested", p.terminal.contested}}},
      {"lifecycleInitialState", p.lifecycleInitialState},
      {"lifecycleStates", std::move(lifecycleStates)},
      {"effects", std::move(effects)},
      {"effectGroups", std::move(groups)},
      {"computes", std::move(computes)},
      {"lifecycleTransitions", std::move(lifecycleTransitions)},
      {"attestationPolicies", std::move(policies)}};
  if (!p.obligations.empty())
    out["obligations"] = std::move(obligations);
  return out;
}
} // namespace

Expected<json::Value>
canonicalPlanSemantics(const CoordinationPlan &coordinationPlan) {
  return canonicalPlanSemanticsImpl(coordinationPlan);
}

Expected<std::string>
coordinationPlanToText(const CoordinationPlan &coordinationPlan) {
  Expected<json::Value> plan = planToJson(coordinationPlan);
  if (!plan)
    return plan.takeError();
  std::string text;
  raw_string_ostream os(text);
  os << formatv("{0:2}", *plan) << "\n";
  os.flush();
  return text;
}

// Serialize the complete backend projection graph of a
// coordination plan to JSON. Because the projection is a deterministic function
// of the verified plan (Property P1) and the plan is reconstructed identically
// from the source MLIR and from a round-tripped capability-spec, this text is
// invariant under the waist round-trip — the check
// test/ir/backend/backend_projection_graph.test asserts exactly that and
// compares the node/edge structure against the three bound traces.
Expected<std::string>
backendProjectionToText(const CoordinationPlan &coordinationPlan) {
  using namespace neutrino::projection;
  // Propagate the projector's explicit error contract ( P1-B): an
  // internally-invalid projection surfaces its stable diagnostic and emits no
  // artifact, rather than serializing a bad graph.
  // The projection core (projectBackendGraph) already canonicalizes every leaf
  // value (§2.5) and verifies + orders the graph, so this is pure
  // serialization.
  Expected<BackendProjectionGraph> gOr = projectBackendGraph(coordinationPlan);
  if (!gOr)
    return gOr.takeError();
  BackendProjectionGraph g = std::move(*gOr);

  json::Array nodes, edges;
  auto node = [&](const std::string &id, const char *kind,
                  const std::string &sourceRef,
                  std::vector<std::pair<std::string, json::Value>> fields) {
    json::Object o;
    o["id"] = id;
    o["kind"] = kind;
    for (auto &kv : fields)
      o[kv.first] = std::move(kv.second);
    o["sourceRef"] = sourceRef;
    nodes.push_back(std::move(o));
  };
  auto terminalKindStr = [](TerminalKind k) -> const char * {
    switch (k) {
    case TerminalKind::Success:
      return "success";
    case TerminalKind::Aborted:
      return "aborted";
    case TerminalKind::Contested:
      return "contested";
    default:
      return "none";
    }
  };
  auto executionModeStr = [](ExecutionMode m) -> const char * {
    switch (m) {
    case ExecutionMode::Evidence:
      return "evidence";
    case ExecutionMode::Temporal:
      return "temporal";
    default:
      return "effectful";
    }
  };
  auto lifecycleRoleStr = [](LifecycleRole r) -> const char * {
    switch (r) {
    case LifecycleRole::Initial:
      return "initial";
    case LifecycleRole::AcceptedOrAttested:
      return "acceptedOrAttested";
    default:
      return "success";
    }
  };

  for (const auto &n : g.executionIdentities)
    node(n.id, "ExecutionIdentity", n.sourceRef,
         {{"procedureNamespace", n.procedureNamespace},
          {"instanceKey", n.instanceKey},
          {"replayKey", n.replayKey}});
  for (const auto &n : g.commitStates)
    node(
        n.id, "CommitState", n.sourceRef,
        {{"idempotencyKey", n.idempotencyKey}, {"commitScope", n.commitScope}});
  for (const auto &n : g.lifecycleStates) {
    std::vector<std::pair<std::string, json::Value>> f = {
        {"name", n.name}, {"terminal", n.terminal}};
    if (n.terminal)
      f.push_back({"terminalKind", terminalKindStr(n.terminalKind)});
    node(n.id, "LifecycleState", n.sourceRef, std::move(f));
  }
  for (const auto &n : g.transitions)
    node(n.id, "Transition", n.sourceRef, {{"name", n.name}});
  for (const auto &n : g.projectedLifecycleRoles)
    node(n.id, "ProjectedLifecycleRole", n.sourceRef,
         {{"mode", executionModeStr(n.mode)},
          {"role", lifecycleRoleStr(n.role)},
          {"state", n.state}});
  for (const auto &n : g.quorumPolicies)
    node(n.id, "QuorumPolicy", n.sourceRef,
         {{"threshold", n.threshold},
          {"canonicalization", n.canonicalization},
          {"timeout", n.timeout},
          {"fallback", n.fallback}});
  for (const auto &n : g.guardObligations)
    node(n.id, "GuardObligation", n.sourceRef,
         {{"guardKind", n.guardKind},
          {"conditionKind", n.conditionKind},
          {"applicationMode", n.applicationMode}});
  for (const auto &n : g.evidenceAcceptances)
    node(n.id, "EvidenceAcceptance", n.sourceRef,
         {{"bindingValue", n.bindingValue},
          {"style", n.style},
          {"chained", n.chained},
          {"admissibility", n.admissibility}});
  for (const auto &n : g.primitiveObligations) {
    json::Array ops;
    for (const std::string &o : n.typedOperands)
      ops.push_back(o);
    node(n.id, "PrimitiveObligation", n.sourceRef,
         {{"finalizedKind", n.finalizedKind},
          {"typedOperands", std::move(ops)}});
  }
  for (const auto &n : g.balancedEffectGroups)
    node(n.id, "BalancedEffectGroup", n.sourceRef,
         {{"firstIndex", n.firstIndex},
          {"pairing", n.pairing},
          {"mustBalance", n.mustBalance}});
  for (const auto &n : g.ledgerPostings)
    node(n.id, "LedgerPosting", n.sourceRef,
         {{"effectIndex", n.effectIndex}, {"direction", n.direction}});
  for (const auto &n : g.balanceAssertions)
    node(n.id, "BalanceAssertion", n.sourceRef, {{"scope", n.scope}});
  for (const auto &n : g.compensationObligations)
    node(n.id, "CompensationObligation", n.sourceRef, {{"mode", n.mode}});
  for (const auto &n : g.typedOperands)
    node(n.id, "TypedOperand", n.sourceRef,
         {{"operandKind", n.operandKind}, {"value", n.value}});
  for (const auto &n : g.typedParams)
    node(n.id, "TypedParam", n.sourceRef,
         {{"name", n.name},
          {"bindingValue", n.bindingValue},
          {"ordinal", n.ordinal},
          {"type", n.type}});
  for (const auto &n : g.references) {
    std::vector<std::pair<std::string, json::Value>> f = {{"ref", n.ref},
                                                          {"role", n.role}};
    // S0.1: emit the lossless authorization operand alongside the structural
    // `ref`. Present exactly for observer-set references (the verifier's
    // fail-closed invariant), so a non-observerSet reference stays byte-stable.
    if (!n.bindingValue.empty())
      f.push_back({"bindingValue", n.bindingValue});
    node(n.id, "Reference", n.sourceRef, std::move(f));
  }
  for (const auto &n : g.computeNodes)
    node(n.id, "ComputeNode", n.sourceRef,
         {{"bindingValue", n.bindingValue},
          {"ordinal", n.ordinal},
          {"exprKind", n.exprKind},
          {"dtype", n.dtype},
          {"expression", n.expression}});

  for (const auto &e : g.edges) {
    json::Object o;
    o["from"] = e.from;
    o["name"] = e.name;
    o["to"] = e.to;
    o["sourceRef"] = e.sourceRef;
    edges.push_back(std::move(o));
  }

  json::Object out{{"kind", "neutrino.backend-projection-graph.v1"},
                   {"schemaVersion", g.schemaVersion},
                   {"nodes", std::move(nodes)},
                   {"edges", std::move(edges)}};
  std::string text;
  raw_string_ostream os(text);
  os << formatv("{0:2}", json::Value(std::move(out))) << "\n";
  os.flush();
  return text;
}

// : the coordination-plan target registers NO emit function. It is a
// DRIVER-SERIALIZED target (TargetRegistry.def / TargetSpec::driverSerialized):
// neutrino-gen writes coordination-plan.json + backend-projection.json
// directly, with CHECKED `Expected` propagation of `coordinationPlanToText` +
// `backendProjectionToText`, so a serialization/legality failure fails closed
// with a stable diagnostic and leaves no partial artifact — and there is no
// publicly-callable registered emitter for this target to re-assemble it with
// `cantFail` (the  regression seam) or to abort.

} // namespace neutrino
