//===- GenSlotSpec.cpp - render the slot/ subtree from the capability-spec
//-===//
//
// Target-neutral slot lifecycle projection from the frozen capability-spec
// contract. Backend packages may decorate the resulting typed artifacts without
// becoming dependencies of this retained-core renderer.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenSlotSpec.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/Lifecycle.h"

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"
#include "llvm/Support/ErrorHandling.h"
#include "llvm/Support/JSON.h"

#include <algorithm>
#include <map>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

using namespace llvm;

namespace {

std::string q(StringRef s) { return "\"" + neutrino::jsonEscape(s) + "\""; }

std::string arr(const std::vector<std::string> &v) {
  std::string o = "[";
  for (size_t i = 0; i < v.size(); ++i) {
    if (i)
      o += ", ";
    o += q(v[i]);
  }
  return o + "]";
}

// Distinct, in first-appearance order.
std::vector<std::string> distinct(const std::vector<std::string> &v) {
  std::vector<std::string> out;
  for (const auto &s : v)
    if (std::find(out.begin(), out.end(), s) == out.end())
      out.push_back(s);
  return out;
}

// ---- capability-spec JSON accessors (fail-closed on a malformed spec) -------

const json::Object &obj(const json::Value *v, const char *what) {
  const json::Object *o = v ? v->getAsObject() : nullptr;
  if (!o)
    throw std::runtime_error(
        std::string("capability-spec: expected object for '") + what + "'");
  return *o;
}

const json::Array *arrPtr(const json::Object &o, const char *key) {
  return o.getArray(key);
}

std::string str(const json::Object &o, const char *k) {
  return o.getString(k).value_or("").str();
}

// A spec operand `{ "kind": "ref"|"literal", "value": ... }` -> the slot's
// `{ "input": ... }` / `{ "literal": ... }` shape (mirrors ProcedureView Ref).
std::string refJson(const json::Object &e, const char *field) {
  const json::Object &r = obj(e.get(field), field);
  std::string value = str(r, "value");
  return str(r, "kind") == "literal"
             ? std::string("{ \"literal\": ") + q(value) + " }"
             : std::string("{ \"input\": ") + q(value) + " }";
}

const char *kEnvelopeSchema = R"({
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "neutrino.slot.envelope",
  "title": "Neutrino Slot Operation Envelope",
  "description": "Canonical envelope for one slot operation. Business-coordination operations only (not arbitrary RPC).",
  "type": "object",
  "additionalProperties": false,
  "required": ["sessionId", "operationId", "operation", "capability", "capabilityVersion", "participant", "counterparty", "payload", "payloadHash", "previousTranscriptHash", "signature"],
  "allOf": [
    {"if": {"properties": {"operation": {"enum": ["COMMIT", "REJECT", "COMPENSATE"]}}},
     "then": {"required": ["correlationId"]}}
  ],
  "properties": {
    "sessionId": {"type": "string"},
    "operationId": {"type": "string"},
    "operation": {"type": "string", "enum": @OPS@},
    "correlationId": {"type": "string"},
    "capability": {"type": "string"},
    "capabilityVersion": {"type": "string"},
    "participant": {"type": "string"},
    "counterparty": {"type": "string"},
    "payload": {"type": "object"},
    "payloadHash": {"type": "string"},
    "previousTranscriptHash": {"type": "string"},
    "signature": {"type": "string"},
    "diagnostics": {"type": "array", "items": {"type": "object", "required": ["severity", "code", "message"], "properties": {"severity": {"type": "string"}, "code": {"type": "string"}, "message": {"type": "string"}}}},
    "anchorRef": {"type": "object", "properties": {"chain": {"type": "string"}, "address": {"type": "string"}, "commitmentHash": {"type": "string"}}}
  }
}
)";

// The envelope's `operation` enum is PROJECTED from the machine's operation
// vocabulary (), not hardcoded — so an oracle-gated machine's quorum ops
// (S3, : AWAIT_QUORUM/REACH_QUORUM/TIMEOUT + the fallback) appear in the
// wire contract too, and check_slot_from_spec's "envelope enum == spec
// vocabulary" invariant holds for every machine shape. For the fixed
// OPEN..CLOSE machine this substitutes the identical 7-op enum, so committed
// slot goldens are byte-unchanged.
std::string envelopeSchema(const std::vector<std::string> &ops) {
  std::string s = kEnvelopeSchema;
  const std::string marker = "@OPS@";
  const size_t at = s.find(marker);
  s.replace(at, marker.size(), arr(ops));
  return s;
}

bool isFlexible(const json::Object &p) {
  return str(p, "binding") == "to_be_bound";
}

std::vector<std::string> strArray(const json::Object &o, const char *key) {
  std::vector<std::string> out;
  if (const json::Array *a = o.getArray(key))
    for (const json::Value &v : *a)
      out.push_back(v.getAsString().value_or("").str());
  return out;
}

bool specIsBalanced(const json::Object &spec) {
  if (const json::Array *inv = spec.getArray("invariants"))
    for (const json::Value &iv : *inv)
      if (const json::Object *io = iv.getAsObject())
        if (io->getString("kind").value_or("") == "balanced")
          return true;
  return false;
}

std::string capabilityJson(const json::Object &spec, const std::string &cap) {
  const std::string name = str(spec, "procedure");
  const std::string version = str(spec, "specVersion");
  std::vector<std::string> owners, ledgers, computes, evidence, partyInputs,
      parties;
  const json::Array *effects = arrPtr(spec, "effects");
  if (effects)
    for (const json::Value &ev : *effects) {
      const json::Object &e = obj(&ev, "effect");
      owners.push_back(str(e, "owner"));
      ledgers.push_back(str(e, "ledger"));
      // The workflow parties are the `party` operands of the legs (the party
      // input refs), NOT the ledger owners.
      parties.push_back(str(obj(e.get("party"), "party"), "value"));
    }
  const json::Array *computesA = arrPtr(spec, "computes");
  if (computesA)
    for (const json::Value &cv : *computesA)
      computes.push_back(str(obj(&cv, "compute"), "name"));
  const json::Array *inputsA = arrPtr(spec, "inputs");
  if (inputsA)
    for (const json::Value &iv : *inputsA) {
      const json::Object &in = obj(&iv, "input");
      std::string ty = str(in, "type");
      if (ty == "evidence")
        evidence.push_back(str(in, "name"));
      if (ty == "party")
        partyInputs.push_back(str(in, "name"));
    }

  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.slot-capability\",\n";
  o += "  \"capability\": " + q(cap) + ",\n";
  o += "  \"capabilityVersion\": " + q(version) + ",\n";
  o += "  \"procedure\": " + q(name) + ",\n";
  if (spec.get("trigger"))
    o += "  \"trigger\": " + q(str(spec, "trigger")) + ",\n";
  o += "  \"parties\": " + arr(distinct(parties)) + ",\n";

  const json::Array *participants = arrPtr(spec, "participants");
  if (participants && !participants->empty()) {
    std::vector<std::string> orgs;
    o += "  \"declaredParticipants\": [\n";
    for (size_t i = 0; i < participants->size(); ++i) {
      const json::Object &p = obj(&(*participants)[i], "participant");
      std::string org = str(p, "org");
      std::string entry = "    { \"name\": " + q(str(p, "name")) +
                          ", \"role\": " + q(str(p, "role"));
      if (!org.empty()) {
        entry += ", \"org\": " + q(org);
        orgs.push_back(org);
      }
      entry += ", \"capabilities\": " + arr(strArray(p, "capabilities"));
      if (isFlexible(p)) {
        entry += ", \"binding\": { \"mode\": \"to_be_bound\", \"runtimes\": " +
                 arr(strArray(p, "bindRuntimes"));
        std::string minA = str(p, "bindMinAssurance");
        if (!minA.empty())
          entry += ", \"minAssurance\": " + q(minA);
        if (!org.empty())
          entry += ", \"authorizedBinder\": " + q(org);
        entry += " }";
      }
      entry += " }";
      o += entry + (i + 1 < participants->size() ? ",\n" : "\n");
    }
    o += "  ],\n";
    orgs = distinct(orgs);
    if (!orgs.empty())
      o += "  \"topology\": { \"organizations\": " + arr(orgs) +
           ", \"crossOrganization\": " + (orgs.size() > 1 ? "true" : "false") +
           " },\n";
  }
  o += "  \"ledgerOwners\": " + arr(distinct(owners)) + ",\n";
  // The operation vocabulary is PROJECTED from the canonical lifecycle machine
  // ().
  o += "  \"operations\": " +
       arr(neutrino::lifecycleModelFromSpec(spec).operationNames()) + ",\n";
  o += "  \"computed\": " + arr(computes) + ",\n";
  o += "  \"ledgers\": " + arr(distinct(ledgers)) + ",\n";
  o += "  \"evidenceInputs\": " + arr(evidence) + ",\n";
  o += "  \"partyTypedInputs\": " + arr(partyInputs) + ",\n";
  o += "  \"typedInputs\": [\n";
  if (inputsA)
    for (size_t i = 0; i < inputsA->size(); ++i) {
      const json::Object &in = obj(&(*inputsA)[i], "input");
      o += "    { \"name\": " + q(str(in, "name")) +
           ", \"type\": " + q(str(in, "type")) + " }";
      o += (i + 1 < inputsA->size() ? ",\n" : "\n");
    }
  o += "  ],\n";
  o += "  \"entries\": [\n";
  if (effects)
    for (size_t i = 0; i < effects->size(); ++i) {
      const json::Object &e = obj(&(*effects)[i], "effect");
      o += "    {\n";
      o += "      \"name\": " + q(str(e, "name")) + ",\n";
      o += "      \"kind\": " + q(str(e, "kind")) + ",\n";
      o += "      \"ledger\": " + q(str(e, "ledger")) + ",\n";
      o += "      \"owner\": " + q(str(e, "owner")) + ",\n";
      if (!str(e, "participant").empty())
        o += "      \"participant\": " + q(str(e, "participant")) + ",\n";
      o += "      \"party\": " + refJson(e, "party") + ",\n";
      o += "      \"amount\": " + refJson(e, "amount") + ",\n";
      o += "      \"currency\": " + refJson(e, "currency") + ",\n";
      o += "      \"idempotencyKey\": " + refJson(e, "idempotencyKey") + "\n";
      o += "    }";
      o += (i + 1 < effects->size() ? ",\n" : "\n");
    }
  o += "  ]\n";
  o += "}\n";
  return o;
}

std::string op(const char *name, const char *prior, const std::string &maps,
               bool last) {
  std::string priorJson = prior ? q(prior) : std::string("null");
  std::string o = "    { \"operation\": " + q(name) +
                  ", \"requiresPrior\": " + priorJson +
                  ", \"maps\": " + q(maps) + " }";
  return o + (last ? "\n" : ",\n");
}

std::string operationsJson(const json::Object &spec, const std::string &cap) {
  const std::string name = str(spec, "procedure");
  std::vector<std::string> computes, entries;
  if (const json::Array *c = arrPtr(spec, "computes"))
    for (const json::Value &cv : *c)
      computes.push_back(str(obj(&cv, "compute"), "name"));
  if (const json::Array *ef = arrPtr(spec, "effects"))
    for (const json::Value &ev : *ef) {
      const json::Object &e = obj(&ev, "effect");
      entries.push_back(str(e, "kind") + " " + str(e, "name"));
    }
  std::string compList, entryList;
  for (size_t i = 0; i < computes.size(); ++i)
    compList += (i ? ", " : "") + computes[i];
  for (size_t i = 0; i < entries.size(); ++i)
    entryList += (i ? ", " : "") + entries[i];

  std::map<std::string, std::string> maps = {
      {"OPEN", "initialize workflow key (status NEW)"},
      {"NEGOTIATE", "capability / attestation agreement"},
      {"PROPOSE", "compute [" + compList + "]; stage [" + entryList + "]"},
      {"COMMIT", "assert_balanced + post the staged legs (replay-protected)"},
      {"REJECT", "decline; no postings; recorded in transcript"},
      {"COMPENSATE", "reverse the committed legs"},
      {"CLOSE", "reconciliation + final coordination status"},
      // Oracle-consensus quorum gate (S3, ): projected when the machine is
      // oracle-gated. The staged legs post only after REACH_QUORUM -> COMMIT,
      // so a leg never fires on < M (fail-closed by construction).
      {"AWAIT_QUORUM", "open the M-of-N attestation window (status "
                       "QUORUM_PENDING)"},
      {"REACH_QUORUM",
       "quorum reached: >= M valid signatures over the canonical "
       "claim (status QUORUM_MET)"},
      {"TIMEOUT", "deadline reached before quorum (status QUORUM_TIMEOUT)"},
      {"ABORT", "quorum-timeout fallback: abort — the staged legs never post"},
      {"ESCALATE", "quorum-timeout fallback: escalate — hand off; the staged "
                   "legs never post"},
  };

  const neutrino::LifecycleModel m = neutrino::lifecycleModelFromSpec(spec);
  std::vector<std::string> ops = m.operationNames();
  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.slot-operations\",\n";
  o += "  \"capability\": " + q(cap) + ",\n";
  o += "  \"operations\": [\n";
  for (size_t i = 0; i < ops.size(); ++i) {
    auto it = maps.find(ops[i]);
    if (it == maps.end())
      throw std::runtime_error("slot ('" + name +
                               "') has no rendering for lifecycle operation '" +
                               ops[i] + "'");
    std::string prior = m.requiresPrior(ops[i]);
    o += op(ops[i].c_str(), prior.empty() ? nullptr : prior.c_str(), it->second,
            i + 1 == ops.size());
  }
  o += "  ]\n}\n";
  return o;
}

std::string compensationJson(const json::Object &spec, const std::string &cap) {
  const std::string name = str(spec, "procedure");
  const neutrino::LifecycleModel m = neutrino::lifecycleModelFromSpec(spec);
  std::vector<std::string> post = m.operationsWithEffect("post");
  std::vector<std::string> comp = m.operationsWithEffect("compensate");
  if (post.size() != 1 || comp.size() != 1)
    throw std::runtime_error(
        "slot ('" + name +
        "') compensation requires exactly one 'post' and one 'compensate' "
        "operation in the lifecycle machine (got " +
        std::to_string(post.size()) + " post, " + std::to_string(comp.size()) +
        " compensate)");
  std::string commitOp = post.front();
  std::vector<std::string> nonComp;
  for (const std::string &n : m.operationNames())
    if (std::find(post.begin(), post.end(), n) == post.end() &&
        std::find(comp.begin(), comp.end(), n) == comp.end())
      nonComp.push_back(n);

  const json::Array *effects = arrPtr(spec, "effects");
  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.slot-compensation\",\n";
  o += "  \"capability\": " + q(cap) + ",\n";
  o += "  \"compensable\": {\n";
  o += "    " + q(commitOp) + ": {\n";
  o += "      \"how\": \"post the inverse of each committed leg\",\n";
  o += "      \"reverses\": [\n";
  if (effects)
    for (size_t i = 0; i < effects->size(); ++i) {
      const json::Object &e = obj(&(*effects)[i], "effect");
      o += "        { \"entry\": " + q(str(e, "name")) +
           ", \"ledger\": " + q(str(e, "ledger")) +
           ", \"inverseOf\": " + q(str(e, "kind")) + " }";
      o += (i + 1 < effects->size() ? ",\n" : "\n");
    }
  o += "      ],\n";
  o += "      \"idempotency\": " + q(name + ":<idempotency_key>:compensation") +
       "\n";
  o += "    }\n";
  o += "  },\n";
  o += "  \"nonCompensable\": " + arr(nonComp) + ",\n";
  o += "  \"invariantAfterCompensation\": " +
       q(specIsBalanced(spec) ? "balanced" : "none") + "\n";
  o += "}\n";
  return o;
}

std::string transcriptJson(const json::Object &spec, const std::string &cap) {
  std::vector<std::string> evidence;
  if (const json::Array *inputsA = arrPtr(spec, "inputs"))
    for (const json::Value &iv : *inputsA) {
      const json::Object &in = obj(&iv, "input");
      if (str(in, "type") == "evidence")
        evidence.push_back(str(in, "name"));
    }
  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.slot-transcript-policy\",\n";
  o += "  \"capability\": " + q(cap) + ",\n";
  o += "  \"hashChain\": {\n";
  o += "    \"perEnvelope\": \"payloadHash = sha256(canonical(payload))\",\n";
  o += "    \"chain\": \"previousTranscriptHash links each envelope to the "
       "prior one\",\n";
  o += "    \"includesRejected\": true,\n";
  o += "    \"includesDiagnostics\": true\n";
  o += "  },\n";
  o += "  \"anchoring\": {\n";
  o += "    \"default\": \"per session close\",\n";
  o += "    \"valueMovingCommit\": \"optional per-commit anchor\",\n";
  o += "    \"anchorRef\": { \"chain\": \"evm\", \"records\": \"commitmentHash "
       "of committed legs\", \"via\": \"blockchain slot as "
       "coordinator-of-record\" }\n";
  o += "  },\n";
  o += "  \"evidence\": " + arr(evidence) + "\n";
  o += "}\n";
  return o;
}

// Orgs in first-appearance order over declared participants; "" is a valid
// bucket (a participant with no declared org), rendered with a null id.
std::vector<std::string> orderedOrgsWithEmpty(const json::Array &participants) {
  std::vector<std::string> out;
  for (const json::Value &pv : participants) {
    std::string org = str(obj(&pv, "participant"), "org");
    if (std::find(out.begin(), out.end(), org) == out.end())
      out.push_back(org);
  }
  return out;
}

std::string bindingTopologyJson(const json::Object &spec,
                                const std::string &cap) {
  const std::string name = str(spec, "procedure");
  const std::string version = str(spec, "specVersion");
  const json::Array &participants = *arrPtr(spec, "participants");
  std::vector<std::string> orgOrder = orderedOrgsWithEmpty(participants);
  size_t namedOrgs = 0;
  for (const auto &org : orgOrder)
    if (!org.empty())
      ++namedOrgs;

  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.slot-binding-topology\",\n";
  o += "  \"schemaVersion\": 1,\n";
  o += "  \"capability\": " + q(cap) + ",\n";
  o += "  \"capabilityVersion\": " + q(version) + ",\n";
  o += "  \"procedure\": " + q(name) + ",\n";
  o += "  \"organizations\": [\n";
  for (size_t oi = 0; oi < orgOrder.size(); ++oi) {
    const std::string &org = orgOrder[oi];
    o += "    {\n";
    o += "      \"organizationId\": " +
         (org.empty() ? std::string("null") : q(org)) + ",\n";
    o += "      \"participants\": [\n";
    // participants declared in `org`, in declaration order.
    std::vector<const json::Object *> ps;
    for (const json::Value &pv : participants) {
      const json::Object &p = obj(&pv, "participant");
      if (str(p, "org") == org)
        ps.push_back(&p);
    }
    for (size_t pi = 0; pi < ps.size(); ++pi) {
      const json::Object &p = *ps[pi];
      std::string pname = str(p, "name");
      std::string slotId = cap + "#" + pname;
      bool flex = isFlexible(p);
      std::string mode = flex ? "to_be_bound" : "fixed";
      std::string bindMin = str(p, "bindMinAssurance");
      std::string minA =
          (flex && !bindMin.empty()) ? bindMin : std::string("A1");
      o += "        {\n";
      o += "          \"participantId\": " + q(pname) + ",\n";
      o += "          \"role\": " + q(str(p, "role")) + ",\n";
      o += "          \"slots\": [\n";
      o += "            {\n";
      o += "              \"slotId\": " + q(slotId) + ",\n";
      o += "              \"lateBindingMode\": " + q(mode) + ",\n";
      o += "              \"allowedRuntimes\": " +
           (flex ? arr(strArray(p, "bindRuntimes")) : std::string("[]")) +
           ",\n";
      o += "              \"minAssurance\": " + q(minA) + ",\n";
      o += "              \"evidenceProfile\": null";
      std::string org2 = str(p, "org");
      if (flex && !org2.empty())
        o += ",\n              \"authorizedBinder\": " + q(org2) + "\n";
      else
        o += "\n";
      o += "            }\n";
      o += "          ]\n";
      o += "        }";
      o += (pi + 1 < ps.size() ? ",\n" : "\n");
    }
    o += "      ]\n";
    o += "    }";
    o += (oi + 1 < orgOrder.size() ? ",\n" : "\n");
  }
  o += "  ],\n";
  o += "  \"crossOrganization\": " +
       std::string(namedOrgs > 1 ? "true" : "false") + "\n";
  o += "}\n";
  return o;
}

// capability.lock — the negotiation identity over the wire-contract files. The
// hash is over each file's CONTENT (== its on-disk bytes), so it is identical
// to the prior sha256OfFile-based lock without needing the files on disk yet.
std::string
capabilityLockJson(const std::string &cap, const std::string &version,
                   std::vector<std::pair<std::string, std::string>> wireFiles) {
  std::sort(wireFiles.begin(), wireFiles.end(),
            [](const auto &a, const auto &b) { return a.first < b.first; });
  std::string preimage;
  std::vector<std::pair<std::string, std::string>> hashes;
  for (const auto &f : wireFiles) {
    std::string h = neutrino::sha256Hex(f.second);
    hashes.push_back({f.first, h});
    preimage += f.first + ":" + h + "\n";
  }
  std::string o = "{\n";
  o += "  \"kind\": \"neutrino.capability-lock\",\n";
  o += "  \"capability\": " + q(cap) + ",\n";
  o += "  \"capabilityVersion\": " + q(version) + ",\n";
  o += "  \"method\": \"lowercase-hex sha256 of concat(sorted(basename + ':' + "
       "sha256(file) + newline)) over the wire-contract files "
       "(capability/operations/compensation/transcript; envelope.schema.json "
       "excluded); decode hex to 32 bytes for EnvelopeHeader.schema_hash\",\n";
  o += "  \"capabilityHash\": " + q(neutrino::sha256Hex(preimage)) + ",\n";
  o += "  \"files\": {\n";
  for (size_t i = 0; i < hashes.size(); ++i) {
    o += "    " + q(hashes[i].first) + ": " + q(hashes[i].second);
    o += (i + 1 < hashes.size() ? ",\n" : "\n");
  }
  o += "  }\n";
  o += "}\n";
  return o;
}

} // namespace

neutrino::SlotArtifacts
neutrino::generateSlotFromSpec(const json::Object &spec) {
  const std::string name = str(spec, "procedure");
  const std::string cap = "coordinate." + name;

  SlotArtifacts files = {
      {"capability.json", capabilityJson(spec, cap)},
      {"operations.json", operationsJson(spec, cap)},
      {"compensation.json", compensationJson(spec, cap)},
      {"transcript.json", transcriptJson(spec, cap)},
      {"envelope.schema.json",
       envelopeSchema(neutrino::lifecycleModelFromSpec(spec).operationNames())},
  };
  // binding-topology.json: emitted only when participants are declared (the
  // entry removes any stale copy when they are not).
  const json::Array *participants = arrPtr(spec, "participants");
  if (participants && !participants->empty())
    files.push_back({"binding-topology.json", bindingTopologyJson(spec, cap)});

  refreshSlotCapabilityLock(files);
  return files;
}

void neutrino::refreshSlotCapabilityLock(SlotArtifacts &artifacts) {
  auto capability = std::find_if(artifacts.begin(), artifacts.end(),
                                 [](const SlotArtifact &artifact) {
                                   return artifact.name == "capability.json";
                                 });
  if (capability == artifacts.end())
    report_fatal_error("slot artifact set has no capability.json");

  Expected<json::Value> parsed = json::parse(capability->content);
  if (!parsed)
    report_fatal_error("slot capability is not valid JSON");
  const json::Object *object = parsed->getAsObject();
  if (!object)
    report_fatal_error("slot capability is not a JSON object");
  const std::string cap = object->getString("capability").value_or("").str();
  const std::string version =
      object->getString("capabilityVersion").value_or("").str();
  if (cap.empty() || version.empty())
    report_fatal_error("slot capability identity is incomplete");

  // capability.lock covers only the wire-contract artifacts. The envelope
  // schema, advisory binding topology, and lock itself are excluded.
  std::vector<std::pair<std::string, std::string>> wire;
  for (const SlotArtifact &artifact : artifacts)
    if (artifact.name == "capability.json" ||
        artifact.name == "operations.json" ||
        artifact.name == "compensation.json" ||
        artifact.name == "transcript.json")
      wire.push_back({artifact.name, artifact.content});

  std::string lock = capabilityLockJson(cap, version, std::move(wire));
  auto existing = std::find_if(artifacts.begin(), artifacts.end(),
                               [](const SlotArtifact &artifact) {
                                 return artifact.name == "capability.lock";
                               });
  if (existing == artifacts.end())
    artifacts.push_back({"capability.lock", std::move(lock)});
  else
    existing->content = std::move(lock);
}
