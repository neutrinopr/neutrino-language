//===- GenSolidityTest.cpp - Foundry harness rendered from the spec -------===//
//
// The spec-sourced Foundry test harness (), extracted from
// GenSoliditySpec.cpp
// (). Its structural shape is single-sourced from the SAME capability-spec
// that renders the contract, so the two cannot drift; only concrete values come
// from the folded TestRealization (). View.h-free; framing is codetext
// (). Moved verbatim — output byte-identical (the lit Solidity goldens
// prove it).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSoliditySpec.h"

#include "Neutrino/CodeText.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/CoordinationEnvelope.h"
#include "Neutrino/Expr.h"
#include "Neutrino/SolidityEmit.h"
#include "Neutrino/StrCase.h"
#include "Neutrino/ValueModel.h"

#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

using namespace llvm;

namespace neutrino {

using namespace sol_detail;

// Evidence-only Foundry harness (): proves the effectless accept()
// coordination the evidence-only contract renders — records+emits on accepted
// quorum, refuses replay, rejects unaccepted quorum, proceeds once accepted,
// and keeps distinct instance keys isolated. It asserts NOTHING about ledger
// totals (there are none), so it never touches net/debitTotal/creditTotal.
static std::string
generateSolidityEvidenceTest(const json::Object &spec,
                             const TestRealization &tr,
                             const CoordinationPlan &coordinationPlan) {
  std::string proc = spec.getString("procedure").value_or("").str();
  std::string name = pascalCase(proc);

  const json::Array *inputsA = spec.getArray("inputs");
  if (!inputsA)
    throw ExprError("spec.ast", "capability-spec: missing inputs");

  // Key off the SAME normalized coordination-plan the contract renderer reads —
  // the explicit instance key, never re-derived from the first input.
  std::string key = coordinationPlan.workflowKey;
  std::string KEY = upper(key);

  std::vector<std::pair<std::string, std::string>> inputs; // (name, type)
  for (const json::Value &v : *inputsA) {
    const json::Object &in = obj(&v, "input");
    inputs.push_back({in.getString("name").value_or("").str(),
                      in.getString("type").value_or("").str()});
  }

  using namespace codetext;
  std::vector<Node> consts;
  for (auto &p : inputs) {
    const ScenarioInput &val = tr.inputs.at(p.first);
    if (solType(p.second) == "uint256")
      consts.push_back(line("uint256 constant " + upper(p.first) + " = " +
                            std::to_string(val.i) + ";"));
    else
      consts.push_back(line("string constant " + upper(p.first) + " = " +
                            solString(val.s) + ";"));
  }
  consts.push_back(line("string constant " + KEY +
                        "_2 = " + solString(tr.inputs.at(key).s + "-2") + ";"));

  std::string callArgs, altArgs;
  for (size_t i = 0; i < inputs.size(); ++i) {
    std::string u = upper(inputs[i].first);
    std::string sep = (i + 1 < inputs.size() ? ", " : "");
    callArgs += u + sep;
    std::string a = (inputs[i].first == key) ? (u + "_2") : u;
    altArgs += a + sep;
  }

  auto pushJoined = [](std::vector<Node> &dst, std::vector<Node> &v,
                       int suffixNewlines) {
    if (v.empty()) {
      for (int i = 0; i < suffixNewlines; ++i)
        dst.push_back(blank());
      return;
    }
    for (Node &n : v)
      dst.push_back(std::move(n));
    for (int i = 0; i < suffixNewlines - 1; ++i)
      dst.push_back(blank());
  };

  auto accStatus = [&](const std::string &s) {
    return "require(uint256(c.statusOf(" + s + ")) == uint256(" + name +
           ".Status.Accepted), ";
  };

  std::vector<Node> tb;
  tb.push_back(
      line("Vm constant vm = Vm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);"));
  tb.push_back(line(name + " c;"));
  tb.push_back(line("MockQuorumGuard guard;"));
  tb.push_back(blank());
  pushJoined(tb, consts, 2);
  tb.push_back(line("event " + name + "Accepted(string " + key + ");"));
  tb.push_back(blank());
  tb.push_back(block("function setUp() public {", "}",
                     {line("guard = new MockQuorumGuard();"),
                      line("c = new " + name + "(address(guard));")}));
  tb.push_back(blank());
  tb.push_back(block("function _key() internal pure returns (bytes32) {", "}",
                     {line("return keccak256(bytes(" + KEY + "));")}));
  tb.push_back(blank());

  {
    std::vector<Node> b = {
        line("bytes32 _k = _key();"),
        line("guard.setAccepted(keccak256(bytes(" + KEY + ")), true);"),
        line("vm.expectEmit(true, true, true, true);"),
        line("emit " + name + "Accepted(" + KEY + ");"),
        line("c.accept(" + callArgs + ");"),
        line(accStatus("_k") + solString("accepted") + ");")};
    tb.push_back(block("function test_accept_records_evidence_and_emits() "
                       "public {",
                       "}", std::move(b)));
    tb.push_back(blank());
  }

  // Replay: a second accept on the SAME instance key is refused; the recorded
  // status is unchanged (no double-acceptance).
  tb.push_back(
      block("function test_replay_is_refused() public {", "}",
            {line("bytes32 _k = _key();"),
             line("guard.setAccepted(keccak256(bytes(" + KEY + ")), true);"),
             line("c.accept(" + callArgs + ");"),
             line("vm.expectRevert(bytes(\"replay\"));"),
             line("c.accept(" + callArgs + ");"),
             line(accStatus("_k") + solString("still accepted") + ");")}));
  tb.push_back(blank());

  // The gate regression: without the guard accepting the instance key, accept()
  // is REFUSED — there is no local setter to bypass the quorum.
  tb.push_back(block("function test_unaccepted_quorum_rejected() public {", "}",
                     {line("vm.expectRevert(bytes(\"quorum not accepted\"));"),
                      line("c.accept(" + callArgs + ");")}));
  tb.push_back(blank());

  // And once the guard DOES accept, accept() proceeds — the gate is the guard's
  // verdict, not an unconditional block.
  tb.push_back(
      block("function test_accepted_quorum_proceeds() public {", "}",
            {line("bytes32 _k = _key();"),
             line("guard.setAccepted(keccak256(bytes(" + KEY + ")), true);"),
             line("c.accept(" + callArgs + ");"),
             line(accStatus("_k") + solString("gated status") + ");")}));
  tb.push_back(blank());

  tb.push_back(
      block("function test_instances_are_isolated_per_key() public {", "}",
            {line("guard.setAccepted(keccak256(bytes(" + KEY + ")), true);"),
             line("c.accept(" + callArgs + ");"),
             line("guard.setAccepted(keccak256(bytes(" + KEY + "_2)), true);"),
             line("c.accept(" + altArgs + ");"),
             line("// each instance key keeps its own status; no sharing"),
             line(accStatus("keccak256(bytes(" + KEY + "))") +
                  solString("k1 status") + ");"),
             line(accStatus("keccak256(bytes(" + KEY + "_2))") +
                  solString("k2 status") + ");")}));

  Document doc;
  doc.add(line("// SPDX-License-Identifier: MIT"));
  doc.add(line("pragma solidity ^0.8.20;"));
  doc.add(blank());
  doc.add(line("import \"../src/" + name + ".sol\";"));
  doc.add(blank());
  doc.add(
      block("interface Vm {", "}",
            {line("function expectRevert(bytes calldata) external;"),
             line("function expectEmit(bool, bool, bool, bool) external;")}));
  doc.add(blank());
  doc.add(
      block("contract MockQuorumGuard {", "}",
            {line("mapping(bytes32 => bool) public accepted;"),
             block("function setAccepted(bytes32 claimId, bool v) external {",
                   "}", {line("accepted[claimId] = v;")}),
             block("function isAccepted(bytes32 claimId) external view returns "
                   "(bool) {",
                   "}", {line("return accepted[claimId];")})}));
  doc.add(blank());
  doc.add(line("/// Generated by the Neutrino Translator from scenario \"" +
               tr.scenario + "\"."));
  doc.add(block("contract " + name + "Test {", "}", std::move(tb)));
  return doc.print("    ");
}

// Temporal per-policy Foundry harness ( activation): the SOUND behavioral
// proof of the per-(key,group) commit-ledger contract. It drives N
// independently controllable mock guards (one per policy) that expose
// acceptedExecutionClaim, RECOMPUTES the exact  execution claim in-harness
// via the emitted CoordinationEnvelope (so a mock returns precisely what execute()
// recomputes), and proves: no-progress before acceptance, incremental
// early/late per-group commits, each group committing exactly once, terminal
// only after every required group commits, replay after terminal, a changed
// payload for the same key failing the claim binding, and cross-key isolation.
static std::string
generateTemporalTest(const json::Object &, const TestRealization &tr,
                     const CoordinationPlan &coordinationPlan) {
  using namespace codetext;
  std::string name = pascalCase(coordinationPlan.procedure);
  std::string key = coordinationPlan.workflowKey;
  std::string KEY = upper(key);
  std::string identity = coordinationIdentityHash(coordinationPlan);
  std::string RECON = "uint256(" + name + ".Status.Reconciled)";

  std::vector<std::string> perPolicies;
  for (const AttestationPolicy &ap : coordinationPlan.attestations)
    perPolicies.push_back(ap.input);

  // Declared inputs sorted by name — the claim order the contract + reference
  // use.
  std::vector<PlanInput> sortedInputs = coordinationPlan.inputs;
  std::stable_sort(
      sortedInputs.begin(), sortedInputs.end(),
      [](const auto &a, const auto &b) { return a.name < b.name; });

  // A non-key input to perturb for the changed-payload test.
  std::string altName;
  for (const PlanInput &pin : coordinationPlan.inputs)
    if (pin.name != key) {
      altName = pin.name;
      break;
    }

  // The TemporalSuppress groups (ordinal + bound policy) — accepted
  // incrementally.
  std::vector<std::pair<size_t, std::string>> tsGroups;
  for (size_t gi = 0; gi < coordinationPlan.effectGroups.size(); ++gi)
    if (coordinationPlan.effectGroups[gi].gateMode ==
        PlanGateMode::TemporalSuppress)
      tsGroups.push_back({gi, coordinationPlan.effectGroups[gi].gatePolicy});

  auto guardVar = [](const std::string &p) { return "guard_" + p; };
  auto grp = [](size_t gi) {
    return "committedGroup(_k, " + std::to_string(gi) + ")";
  };

  // Call-arg list in declaration order, optionally swapping one input's value.
  auto argList = [&](const std::string &swapName, const std::string &swapVal) {
    std::string a;
    for (size_t i = 0; i < coordinationPlan.inputs.size(); ++i) {
      const std::string &n = coordinationPlan.inputs[i].name;
      a += (n == swapName ? swapVal : upper(n));
      a += (i + 1 < coordinationPlan.inputs.size() ? ", " : "");
    }
    return a;
  };
  std::string callArgs = argList("", "");            // base payload
  std::string altKeyArgs = argList(key, KEY + "_2"); // different key
  std::string altPayloadArgs = // same key, changed payload
      altName.empty() ? callArgs : argList(altName, upper(altName) + "_ALT");

  // input constants (values from the realized scenario) + the perturbed ALT.
  std::vector<Node> consts;
  for (const PlanInput &pin : coordinationPlan.inputs) {
    const ScenarioInput &val = tr.inputs.at(pin.name);
    bool num = solType(pin.type) == "uint256";
    consts.push_back(line(
        (num ? "uint256 constant " : "string constant ") + upper(pin.name) +
        " = " + (num ? std::to_string(val.i) : solString(val.s)) + ";"));
    if (pin.name == altName)
      consts.push_back(line(
          (num ? "uint256 constant " : "string constant ") + upper(pin.name) +
          "_ALT = " +
          (num ? std::to_string(val.i + 1) : solString(val.s + "X")) + ";"));
  }
  consts.push_back(line("string constant " + KEY +
                        "_2 = " + solString(tr.inputs.at(key).s + "-2") + ";"));

  // _claim(): rebuild the EXACT execution claim the contract recomputes, so a
  // mock guard can be primed with it. Sorted (name, category, value) over the
  // inputs.
  std::vector<Node> claimBody;
  claimBody.push_back(line("string[] memory _n = new string[](" +
                           std::to_string(sortedInputs.size()) + ");"));
  claimBody.push_back(line("string[] memory _c = new string[](" +
                           std::to_string(sortedInputs.size()) + ");"));
  claimBody.push_back(line("string[] memory _v = new string[](" +
                           std::to_string(sortedInputs.size()) + ");"));
  for (size_t i = 0; i < sortedInputs.size(); ++i) {
    ValueCategory cat = classifyValueType(sortedInputs[i].type);
    std::string idx = std::to_string(i);
    // The workflow-key input takes the parameter `_kv`, so the harness can
    // build the claim for a DIFFERENT key (cross-key independence) as well as
    // the base.
    std::string v = sortedInputs[i].name == key
                        ? "_kv"
                        : (solType(sortedInputs[i].type) == "uint256"
                               ? "CoordinationEnvelope.u2s(" +
                                     upper(sortedInputs[i].name) + ")"
                               : upper(sortedInputs[i].name));
    claimBody.push_back(
        line("_n[" + idx + "] = " + solString(sortedInputs[i].name) + ";"));
    claimBody.push_back(
        line("_c[" + idx + "] = " + solString(categoryName(cat).str()) + ";"));
    claimBody.push_back(line("_v[" + idx + "] = " + v + ";"));
  }
  claimBody.push_back(line("return CoordinationEnvelope.claim(" +
                           solString(identity) + ", _kv, _n, _c, _v);"));

  // --- assemble the test contract body ---
  std::vector<Node> tb;
  tb.push_back(
      line("Vm constant vm = Vm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);"));
  tb.push_back(line(name + " c;"));
  for (const std::string &p : perPolicies)
    tb.push_back(line("MockQuorumGuard " + guardVar(p) + ";"));
  tb.push_back(blank());
  for (Node &n : consts)
    tb.push_back(std::move(n));
  tb.push_back(blank());

  {
    std::vector<Node> su;
    std::string ctorArgs;
    for (size_t i = 0; i < perPolicies.size(); ++i) {
      su.push_back(
          line(guardVar(perPolicies[i]) + " = new MockQuorumGuard();"));
      ctorArgs += "address(" + guardVar(perPolicies[i]) + ")" +
                  (i + 1 < perPolicies.size() ? ", " : "");
    }
    su.push_back(line("c = new " + name + "(" + ctorArgs + ");"));
    tb.push_back(block("function setUp() public {", "}", std::move(su)));
  }
  tb.push_back(blank());
  tb.push_back(block("function _key() internal pure returns (bytes32) {", "}",
                     {line("return keccak256(bytes(" + KEY + "));")}));
  tb.push_back(blank());
  tb.push_back(block(
      "function _claim(string memory _kv) internal pure returns (bytes32) {",
      "}", std::move(claimBody)));
  tb.push_back(blank());

  // (1) No-progress before acceptance + incremental early/late commits +
  // terminal only after every group commits.
  {
    std::vector<Node> b = {
        line("bytes32 _k = _key();"),
        line("bytes32 _cl = _claim(" + KEY + ");"),
        line("// no policy accepted yet: a call commits nothing, leaves the "
             "key's"),
        line("// claim unset, and does not reconcile (no premature terminal)."),
        line("c.execute(" + callArgs + ");"),
        line("require(c.keyClaim(_k) == bytes32(0), \"no-progress leaves "
             "keyClaim "
             "unset\");"),
        line("require(uint256(c.statusOf(_k)) != " + RECON +
             ", \"no premature terminal\");")};
    for (size_t j = 0; j < tsGroups.size(); ++j) {
      size_t gi = tsGroups[j].first;
      const std::string &pol = tsGroups[j].second;
      bool last = j + 1 == tsGroups.size();
      b.push_back(line("// accept policy '" + pol +
                       "' for THIS execution claim -> its group commits."));
      b.push_back(line(guardVar(pol) + ".setAcceptedClaim(_k, _cl);"));
      b.push_back(line("c.execute(" + callArgs + ");"));
      b.push_back(line("require(c." + grp(gi) + ", \"group " +
                       std::to_string(gi) +
                       " committed once its policy accepted\");"));
      b.push_back(
          line("require(uint256(c.statusOf(_k)) " +
               std::string(last ? "== " : "!= ") + RECON + ", " +
               solString(last ? "terminal after every required group"
                              : "not terminal until all groups commit") +
               ");"));
    }
    b.push_back(line("require(c.keyClaim(_k) == _cl, \"keyClaim pinned to the "
                     "recomputed execution claim\");"));
    tb.push_back(
        block("function test_incremental_commit_then_terminal() public {", "}",
              std::move(b)));
    tb.push_back(blank());
  }

  // (2) A group commits EXACTLY ONCE — re-executing while another group is
  // still pending does not re-post. (Needs >= 2 groups so the key is not yet
  // terminal.)
  if (tsGroups.size() >= 2) {
    size_t g0 = tsGroups[0].first;
    const std::string &p0 = tsGroups[0].second;
    tb.push_back(
        block("function test_group_commits_exactly_once() public {", "}",
              {line("bytes32 _k = _key();"),
               line("bytes32 _cl = _claim(" + KEY + ");"),
               line(guardVar(p0) + ".setAcceptedClaim(_k, _cl);"),
               line("c.execute(" + callArgs + ");"),
               line("require(c." + grp(g0) + ", \"group committed\");"),
               line("uint256 _d = c.debitTotal(_k);"),
               line("require(_d > 0, \"group posted its debit legs\");"),
               line("// re-execute: the group is already committed (and the "
                    "key not yet"),
               line("// terminal), so nothing re-posts."),
               line("c.execute(" + callArgs + ");"),
               line("require(c.debitTotal(_k) == _d, \"group commits exactly "
                    "once\");")}));
    tb.push_back(blank());
  }

  // (3) Replay after terminal is refused.
  {
    std::vector<Node> b = {line("bytes32 _k = _key();"),
                           line("bytes32 _cl = _claim(" + KEY + ");")};
    for (const auto &tg : tsGroups)
      b.push_back(line(guardVar(tg.second) + ".setAcceptedClaim(_k, _cl);"));
    b.push_back(line("c.execute(" + callArgs + ");"));
    b.push_back(line("require(uint256(c.statusOf(_k)) == " + RECON +
                     ", \"reconciled\");"));
    b.push_back(line("vm.expectRevert(bytes(\"replay\"));"));
    b.push_back(line("c.execute(" + callArgs + ");"));
    tb.push_back(block("function test_replay_after_terminal_refused() public {",
                       "}", std::move(b)));
    tb.push_back(blank());
  }

  // (4a) The GUARD binding rejects a payload the quorum did NOT accept: on a
  // fresh, unbound key, a guard acceptance for payload A does not authorize a
  // DIFFERENT payload B — B's group never commits and the key stays unbound.
  // This is the guard-claim binding itself, independent of key immutability
  // (4b).
  if (!altName.empty() && !tsGroups.empty()) {
    size_t g0 = tsGroups[0].first;
    const std::string &p0 = tsGroups[0].second;
    tb.push_back(block(
        "function test_guard_acceptance_of_A_does_not_authorize_B() public {",
        "}",
        {line("bytes32 _k = _key();"),
         line("// the quorum accepted payload A's execution claim ..."),
         line(guardVar(p0) + ".setAcceptedClaim(_k, _claim(" + KEY + "));"),
         line("// ... but a DIFFERENT payload B is submitted on the (unbound) "
              "key."),
         line("c.execute(" + altPayloadArgs + ");"),
         line("require(!c." + grp(g0) +
              ", \"acceptance of A must not authorize a different payload "
              "B\");"),
         line(
             "require(c.keyClaim(_k) == bytes32(0), \"B did not commit, so the "
             "key stays unbound\");")}));
    tb.push_back(blank());

    // (4b) Key immutability: once a group has committed (the key is BOUND to
    // A), a later call with a different payload reverts (claim mismatch).
    tb.push_back(block(
        "function test_changed_payload_after_commit_reverts() public {", "}",
        {line("bytes32 _k = _key();"),
         line(guardVar(p0) + ".setAcceptedClaim(_k, _claim(" + KEY + "));"),
         line("c.execute(" + callArgs + ");"),
         line("require(c.keyClaim(_k) == _claim(" + KEY +
              "), \"claim bound on first "
              "commit\");"),
         line("vm.expectRevert(bytes(\"claim mismatch\"));"),
         line("c.execute(" + altPayloadArgs + ");")}));
    tb.push_back(blank());
  }

  // (5) Cross-key isolation: after key1 terminates, a DISTINCT key EXECUTES
  // independently to its OWN terminal (keyed on its own claim), and key1 is
  // unchanged — not merely a read of key2's untouched default state.
  {
    std::vector<Node> b = {
        line("bytes32 _k = _key();"),
        line("bytes32 _k2 = keccak256(bytes(" + KEY + "_2));"),
        line("// key1 reaches terminal.")};
    for (const auto &tg : tsGroups)
      b.push_back(line(guardVar(tg.second) + ".setAcceptedClaim(_k, _claim(" +
                       KEY + "));"));
    b.push_back(line("c.execute(" + callArgs + ");"));
    b.push_back(line("require(uint256(c.statusOf(_k)) == " + RECON +
                     ", \"k1 reconciled\");"));
    b.push_back(line("require(uint256(c.statusOf(_k2)) != " + RECON +
                     ", \"k2 open before its own execution\");"));
    b.push_back(line("// key2 (keyed on " + KEY +
                     "_2, its own claim) executes independently to terminal."));
    for (const auto &tg : tsGroups)
      b.push_back(line(guardVar(tg.second) + ".setAcceptedClaim(_k2, _claim(" +
                       KEY + "_2));"));
    b.push_back(line("c.execute(" + altKeyArgs + ");"));
    b.push_back(line("require(uint256(c.statusOf(_k2)) == " + RECON +
                     ", \"k2 reconciles independently after k1\");"));
    b.push_back(line("require(c.keyClaim(_k2) == _claim(" + KEY +
                     "_2), \"k2 bound to its own claim\");"));
    b.push_back(line("require(uint256(c.statusOf(_k)) == " + RECON +
                     ", \"k1 unchanged\");"));
    tb.push_back(block("function test_cross_key_isolation() public {", "}",
                       std::move(b)));
  }

  Document doc;
  doc.add(line("// SPDX-License-Identifier: MIT"));
  doc.add(line("pragma solidity ^0.8.20;"));
  doc.add(blank());
  doc.add(line("import \"../src/" + name + ".sol\";"));
  doc.add(line("import \"../src/CoordinationEnvelope.sol\";"));
  doc.add(blank());
  doc.add(block("interface Vm {", "}",
                {line("function expectRevert(bytes calldata) external;")}));
  doc.add(blank());
  // A minimal per-policy mock: the coordination reads acceptedExecutionClaim,
  // so the mock stores and returns a per-key claim primed by the harness.
  doc.add(block(
      "contract MockQuorumGuard {", "}",
      {line("mapping(bytes32 => bytes32) public claimOf;"),
       block("function setAcceptedClaim(bytes32 claimId, bytes32 claim) "
             "external {",
             "}", {line("claimOf[claimId] = claim;")}),
       block("function acceptedExecutionClaim(bytes32 claimId) external view "
             "returns (bytes32) {",
             "}", {line("return claimOf[claimId];")}),
       block("function isAccepted(bytes32 claimId) external view returns "
             "(bool) {",
             "}", {line("return claimOf[claimId] != bytes32(0);")})}));
  doc.add(blank());
  doc.add(line("/// Generated by the Neutrino Translator from scenario \"" +
               tr.scenario + "\"."));
  doc.add(block("contract " + name + "Test {", "}", std::move(tb)));
  return doc.print("    ");
}

std::string
generateSolidityTestFromSpec(const json::Object &spec,
                             const TestRealization &tr,
                             const CoordinationPlan &coordinationPlan) {
  if (coordinationPlan.evidenceOnly)
    return generateSolidityEvidenceTest(spec, tr, coordinationPlan);
  //  activation: a temporal per-policy coordination gets the behavioral
  // commit-ledger harness, not the single-shot one.
  for (const PlanEffect &pe : coordinationPlan.effects)
    if (pe.gateMode == PlanGateMode::TemporalSuppress)
      return generateTemporalTest(spec, tr, coordinationPlan);

  std::string proc = spec.getString("procedure").value_or("").str();
  std::string name = pascalCase(proc);

  const json::Array *inputsA = spec.getArray("inputs");
  const json::Array *computesA = spec.getArray("computes");
  const json::Array *effectsA = spec.getArray("effects");
  if (!inputsA || !computesA || !effectsA)
    throw ExprError("spec.ast",
                    "capability-spec: missing inputs/computes/effects");
  if (effectsA->empty())
    throw ExprError("spec.ast", "procedure has no ledger entries");

  // The workflow key comes off the SAME normalized coordinationPlan instance
  // () the contract renderer reads, so the harness cannot key on a
  // different input than the contract it exercises.
  std::string key = coordinationPlan.workflowKey;
  std::string KEY = upper(key);

  // Oracle S2c (): the coordination is gated by the quorum guard, so the
  // harness cannot self-attest a key — it drives a MockQuorumGuard's acceptance
  // and proves execute() is refused for a NON-accepted claim (the regression
  // the review asked for: no legacy `attest()` path to reach execute() without
  // quorum). `acc(keyExpr)` is the "make this workflow key accepted" step —
  // guard.setAccepted for a gated spec, the legacy c.attest for an unattested
  // one (kept byte-identical). The guard's own crypto (M-of-N/replay/low-s/
  // cross-fork) is proven by its reviewed Foundry suite; here we prove the
  // COORDINATION honors the guard's verdict.
  bool gated = !attestationPoliciesFromSpec(spec).empty();
  auto acc = [&](const std::string &keyExpr) -> std::string {
    return gated
               ? ("guard.setAccepted(keccak256(bytes(" + keyExpr + ")), true);")
               : ("c.attest(" + keyExpr + ");");
  };

  // The scenario's event-chain consistency is validated once in realize(); the
  // renderer consumes the folded value cases (M5 WP2, ) while the SHAPE
  // comes from the spec.
  std::set<std::string> computedSet;
  for (auto &kv : tr.computed)
    computedSet.insert(kv.first);

  // A debit/credit operand from the spec {kind: ref|literal, value}: testUint
  // keeps an int literal, maps a ref to its EXPECT_/upper test constant;
  // testStr quotes a string literal.
  auto testUint = [&](const json::Object &op) -> std::string {
    bool lit = op.getString("kind").value_or("") == "literal";
    std::string v = op.getString("value").value_or("").str();
    if (lit) {
      if (!isInt(v))
        throw ExprError("spec.ast",
                        "numeric operand expected, got string literal " + v);
      return v;
    }
    return computedSet.count(v) ? ("EXPECT_" + upper(v)) : upper(v);
  };
  auto testStr = [&](const json::Object &op) -> std::string {
    bool lit = op.getString("kind").value_or("") == "literal";
    std::string v = op.getString("value").value_or("").str();
    return lit ? solString(v) : upper(v);
  };

  std::vector<std::pair<std::string, std::string>>
      inputs; // (name, type) from the spec
  for (const json::Value &v : *inputsA) {
    const json::Object &in = obj(&v, "input");
    inputs.push_back({in.getString("name").value_or("").str(),
                      in.getString("type").value_or("").str()});
  }

  // Structural framing is described with the codetext block/line model (,
  // ): the leaf lines below carry NO indentation and the contract/function
  // braces are block delimiters; the printer owns indentation + newlines. Byte-
  // identical to the hand-assembled output (four-space unit, matching depths).
  using namespace codetext;
  // constants (shape from the spec; concrete values from the TestRealization)
  std::vector<Node> consts;
  for (auto &p : inputs) {
    const ScenarioInput &val = tr.inputs.at(p.first);
    if (solType(p.second) == "uint256")
      consts.push_back(line("uint256 constant " + upper(p.first) + " = " +
                            std::to_string(val.i) + ";"));
    else
      consts.push_back(line("string constant " + upper(p.first) + " = " +
                            solString(val.s) + ";"));
  }
  consts.push_back(line("string constant " + KEY +
                        "_2 = " + solString(tr.inputs.at(key).s + "-2") + ";"));

  std::vector<Node> subsidyConsts;
  for (auto &kv : tr.computed)
    subsidyConsts.push_back(line("uint256 constant EXPECT_" + upper(kv.first) +
                                 " = " + std::to_string(kv.second) + ";"));

  std::string callArgs, altArgs;
  for (size_t i = 0; i < inputs.size(); ++i) {
    std::string u = upper(inputs[i].first);
    callArgs += u + (i + 1 < inputs.size() ? ", " : "");
    std::string a = (inputs[i].first == key) ? (u + "_2") : u;
    altArgs += a + (i + 1 < inputs.size() ? ", " : "");
  }

  llvm::Optional<StringRef> trigOpt = spec.getString("trigger");
  std::string trig =
      trigOpt ? pascalCase(*trigOpt) : pascalCase("procedure_invoked");
  std::vector<Node> evDecls;
  evDecls.push_back(line("event " + trig + "(string " + key + ");"));
  for (const json::Value &v : *computesA)
    evDecls.push_back(
        line("event " +
             pascalCase(obj(&v, "compute").getString("name").value_or("")) +
             "Computed(uint256 value);"));
  for (const json::Value &v : *effectsA) {
    const json::Object &e = obj(&v, "effect");
    std::string verb =
        e.getString("kind").value_or("") == "debit" ? "Debited" : "Credited";
    // Mirror the contract's optional memo param () so the test's
    // re-declared event matches the contract signature it checks with
    // vm.expectEmit.
    std::string memoParam =
        e.getString("memo").value_or("").empty() ? "" : ", string memo";
    evDecls.push_back(line(
        "event " + pascalCase(e.getString("name").value_or("")) + verb +
        "(string party, uint256 amount, string currency" + memoParam + ");"));
  }
  evDecls.push_back(line("event " + name + "Reconciled(string " + key + ");"));

  std::vector<Node> emits;
  emits.push_back(line("vm.expectEmit(true, true, true, true);"));
  emits.push_back(line("emit " + trig + "(" + KEY + ");"));
  for (const json::Value &v : *computesA) {
    std::string cname = obj(&v, "compute").getString("name").value_or("").str();
    emits.push_back(line("vm.expectEmit(true, true, true, true);"));
    emits.push_back(line("emit " + pascalCase(cname) + "Computed(EXPECT_" +
                         upper(cname) + ");"));
  }
  for (const json::Value &v : *effectsA) {
    const json::Object &e = obj(&v, "effect");
    std::string verb =
        e.getString("kind").value_or("") == "debit" ? "Debited" : "Credited";
    // Expect the memo too (): vm.expectEmit checks the data field, so an
    // omitted/renamed memo makes the expected event mismatch and the test
    // fails.
    std::string memoArg = e.getString("memo").value_or("").empty()
                              ? ""
                              : ", " + solString(e.getString("memo")->str());
    emits.push_back(line("vm.expectEmit(true, true, true, true);"));
    emits.push_back(
        line("emit " + pascalCase(e.getString("name").value_or("")) + verb +
             "(" + testStr(obj(e.get("party"), "party")) + ", " +
             testUint(obj(e.get("amount"), "amount")) + ", " +
             testStr(obj(e.get("currency"), "currency")) + memoArg + ");"));
  }
  emits.push_back(line("vm.expectEmit(true, true, true, true);"));
  emits.push_back(line("emit " + name + "Reconciled(" + KEY + ");"));

  std::vector<Node> ledgerAsserts;
  for (auto &kv : tr.ledger)
    ledgerAsserts.push_back(line("require(c.net(_k, " + solString(kv.first) +
                                 ") == int256(" + std::to_string(kv.second) +
                                 "), " + solString("net " + kv.first) + ");"));

  // Expected debit total = sum of every debit's amount (not just the first): a
  // procedure may move value through multiple debit legs.
  std::string debitTotalExpr;
  for (const json::Value &v : *effectsA) {
    const json::Object &e = obj(&v, "effect");
    if (e.getString("kind").value_or("") == "debit")
      debitTotalExpr += (debitTotalExpr.empty() ? "" : " + ") +
                        testUint(obj(e.get("amount"), "amount"));
  }
  if (debitTotalExpr.empty())
    debitTotalExpr = "0";

  // Reproduce `join(v) + <suffixNewlines '\n'>` as codetext nodes: a non-empty
  // vector's last line absorbs one of the suffix newlines, so it adds
  // (suffixNewlines - 1) trailing blank lines; an empty vector (join == "")
  // emits `suffixNewlines` blank lines. Keeps the byte-exact blank-line
  // spacing.
  auto pushJoined = [](std::vector<Node> &dst, std::vector<Node> &v,
                       int suffixNewlines) {
    if (v.empty()) {
      for (int i = 0; i < suffixNewlines; ++i)
        dst.push_back(blank());
      return;
    }
    for (Node &n : v)
      dst.push_back(std::move(n));
    for (int i = 0; i < suffixNewlines - 1; ++i)
      dst.push_back(blank());
  };

  // The test contract body (children of `contract NameTest { }`).
  std::vector<Node> tb;
  tb.push_back(
      line("Vm constant vm = Vm(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);"));
  tb.push_back(line(name + " c;"));
  if (gated)
    tb.push_back(line("MockQuorumGuard guard;"));
  tb.push_back(blank());
  pushJoined(tb, consts, 1);
  pushJoined(tb, subsidyConsts, 2);
  pushJoined(tb, evDecls, 2);
  if (gated)
    tb.push_back(block("function setUp() public {", "}",
                       {line("guard = new MockQuorumGuard();"),
                        line("c = new " + name + "(address(guard));")}));
  else
    tb.push_back(block("function setUp() public {", "}",
                       {line("c = new " + name + "();")}));
  tb.push_back(blank());
  tb.push_back(block("function _key() internal pure returns (bytes32) {", "}",
                     {line("return keccak256(bytes(" + KEY + "));")}));
  tb.push_back(blank());

  {
    std::vector<Node> b = {line("bytes32 _k = _key();"), line(acc(KEY))};
    pushJoined(b, emits, 1);
    b.push_back(line("c.execute(" + callArgs + ");"));
    b.push_back(line("require(uint256(c.statusOf(_k)) == uint256(" + name +
                     ".Status.Reconciled), \"status\");"));
    b.push_back(
        line("require(c.debitTotal(_k) == c.creditTotal(_k), \"balanced\");"));
    b.push_back(line("require(c.debitTotal(_k) == " + debitTotalExpr +
                     ", \"debit total\");"));
    pushJoined(b, ledgerAsserts, 1);
    tb.push_back(block(
        "function test_happy_path_reaches_reconciled_with_events() public {",
        "}", std::move(b)));
    tb.push_back(blank());
  }

  tb.push_back(block("function test_replay_is_safe_no_double_debit() public {",
                     "}",
                     {line("bytes32 _k = _key();"), line(acc(KEY)),
                      line("c.execute(" + callArgs + ");"),
                      line("vm.expectRevert(bytes(\"replay\"));"),
                      line("c.execute(" + callArgs + ");"),
                      line("require(c.debitTotal(_k) == " + debitTotalExpr +
                           ", \"no double debit\");")}));
  tb.push_back(blank());

  if (gated) {
    // The gate regression: without the guard accepting the workflow key,
    // execute() is REFUSED — there is no local `attest()` setter to bypass the
    // quorum, so unattested evidence can never post a leg.
    tb.push_back(
        block("function test_unaccepted_quorum_rejected() public {", "}",
              {line("vm.expectRevert(bytes(\"quorum not accepted\"));"),
               line("c.execute(" + callArgs + ");")}));
    tb.push_back(blank());
    // And once the guard DOES accept, execute() proceeds — proving the gate is
    // the guard's verdict, not an unconditional block.
    tb.push_back(
        block("function test_accepted_quorum_proceeds() public {", "}",
              {line("bytes32 _k = _key();"), line(acc(KEY)),
               line("c.execute(" + callArgs + ");"),
               line("require(uint256(c.statusOf(_k)) == uint256(" + name +
                    ".Status.Reconciled), \"gated status\");")}));
    tb.push_back(blank());
  } else {
    tb.push_back(
        block("function test_missing_attestation_rejected() public {", "}",
              {line("vm.expectRevert(bytes(\"missing attestation\"));"),
               line("c.execute(" + callArgs + ");")}));
    tb.push_back(blank());
    tb.push_back(block(
        "function test_invalid_transition_ordering_rejected() public {", "}",
        {line("c.attest(" + KEY + ");"), line("c.execute(" + callArgs + ");"),
         line("vm.expectRevert(bytes(\"bad transition\"));"),
         line("c.attest(" + KEY + ");")}));
    tb.push_back(blank());
  }

  tb.push_back(block("function test_balanced_invariant_holds() public {", "}",
                     {line("bytes32 _k = _key();"), line(acc(KEY)),
                      line("c.execute(" + callArgs + ");"),
                      line("require(c.debitTotal(_k) == c.creditTotal(_k), "
                           "\"debit==credit\");")}));
  tb.push_back(blank());

  tb.push_back(block(
      "function test_workflows_are_isolated_per_key() public {", "}",
      {line(acc(KEY)), line("c.execute(" + callArgs + ");"),
       line(acc(KEY + "_2")), line("c.execute(" + altArgs + ");"),
       line("// each workflow key keeps its own totals; no sharing/double "
            "counting"),
       line("require(c.debitTotal(keccak256(bytes(" + KEY +
            "))) == " + debitTotalExpr + ", \"k1 total\");"),
       line("require(c.debitTotal(keccak256(bytes(" + KEY +
            "_2))) == " + debitTotalExpr + ", \"k2 total\");")}));

  Document doc;
  doc.add(line("// SPDX-License-Identifier: MIT"));
  doc.add(line("pragma solidity ^0.8.20;"));
  doc.add(blank());
  doc.add(line("import \"../src/" + name + ".sol\";"));
  doc.add(blank());
  doc.add(
      block("interface Vm {", "}",
            {line("function expectRevert(bytes calldata) external;"),
             line("function expectEmit(bool, bool, bool, bool) external;")}));
  doc.add(blank());
  if (gated) {
    // A trivial stand-in for the quorum guard: it exposes only the acceptance
    // verdict the coordination reads, so the harness controls whether a claim
    // counts as accepted WITHOUT re-deriving M-of-N signatures (that crypto is
    // proven by ThresholdQuorumAcceptance's own reviewed Foundry suite). This
    // isolates ONE property: the coordination proceeds iff the guard accepted
    // the workflow key — and reverts otherwise.
    doc.add(block(
        "contract MockQuorumGuard {", "}",
        {line("mapping(bytes32 => bool) public accepted;"),
         block("function setAccepted(bytes32 claimId, bool v) external {", "}",
               {line("accepted[claimId] = v;")}),
         block("function isAccepted(bytes32 claimId) external view returns "
               "(bool) {",
               "}", {line("return accepted[claimId];")})}));
    doc.add(blank());
  }
  doc.add(line("/// Generated by the Neutrino Translator from scenario \"" +
               tr.scenario + "\"."));
  doc.add(block("contract " + name + "Test {", "}", std::move(tb)));
  return doc.print("    ");
}

} // namespace neutrino
