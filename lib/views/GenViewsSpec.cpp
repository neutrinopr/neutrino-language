//===- GenViewsSpec.cpp - per-participant views rendered from the spec
//-----===//
//
// M5 : the migrated `views` renderer. It renders every per-participant
// narrowed view from the canonical capability spec (the frozen external
// contract, ) instead of ProcedureView — so this translation unit includes
// NO View.h and holds no ProcedureView. Output is byte-identical to the
// ProcedureView path it replaces (proved by the fixture gate); the whole
// `views` renderer now consumes only the spec, closing the WP5/WP6 migration
// arc (postgres /, solidity /, now views).
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenViewsSpec.h"

#include "llvm/Support/JSON.h"

#include <algorithm>
#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

using namespace llvm;

namespace neutrino {

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

std::string arr(const std::vector<std::string> &v) {
  std::string o = "[";
  for (size_t i = 0; i < v.size(); ++i) {
    if (i)
      o += ", ";
    o += q(v[i]);
  }
  return o + "]";
}

// A 1-based DSL source location object, matching GenViews (the lexer is
// line-oriented, so column is always 1). "" when the construct carries no
// location, so the field is omitted.
std::string sourceObj(int line) {
  return line > 0 ? "{ \"line\": " + std::to_string(line) + ", \"column\": 1 }"
                  : std::string();
}

const json::Object &obj(const json::Value *v, const char *what) {
  const json::Object *o = v ? v->getAsObject() : nullptr;
  if (!o)
    throw std::runtime_error(std::string("views-from-spec: missing/invalid ") +
                             what);
  return *o;
}
const json::Array &arrOf(const json::Object &o, const char *key) {
  const json::Array *a = o.getArray(key);
  if (!a)
    throw std::runtime_error(std::string("views-from-spec: missing array ") +
                             key);
  return *a;
}

// A spec operand {kind: ref|literal, value}: a `ref` names an input/compute.
// Returns the referenced name, or "" for a literal.
std::string refName(const json::Object &e, const char *field) {
  const json::Object &op = obj(e.get(field), field);
  if (op.getString("kind").value_or("") == "ref")
    return op.getString("value").value_or("").str();
  return "";
}

// Collect every variable name referenced anywhere in a serialized expr AST
// (var / bin / call / cmp). Used to pull a guard's ( `when.ast`) input
// dependencies into a participant's requiredInputs — a consumer must have the
// values the guard compares to know whether its obligation fires ( review).
void collectAstVars(const json::Value *v, std::vector<std::string> &out) {
  const json::Object *o = v ? v->getAsObject() : nullptr;
  if (!o)
    return;
  if (o->getString("kind").value_or("") == "var") {
    out.push_back(o->getString("name").value_or("").str());
    return;
  }
  collectAstVars(o->get("lhs"), out);
  collectAstVars(o->get("rhs"), out);
  if (const json::Array *args = o->getArray("args"))
    for (const json::Value &a : *args)
      collectAstVars(&a, out);
}

// reachableInputs, from the spec: resolve `seeds` to the underlying declared
// inputs, following compute dependencies transitively (a leg may reference a
// compute whose value derives from inputs). Mirrors Analysis.cpp exactly.
std::set<std::string>
reachableInputs(const std::set<std::string> &inputNames,
                const std::map<std::string, std::vector<std::string>> &computes,
                const std::vector<std::string> &seeds) {
  std::set<std::string> neededInputs, seen;
  std::vector<std::string> work(seeds.begin(), seeds.end());
  while (!work.empty()) {
    std::string n = work.back();
    work.pop_back();
    if (!seen.insert(n).second)
      continue;
    if (inputNames.count(n)) {
      neededInputs.insert(n);
    } else {
      auto it = computes.find(n);
      if (it != computes.end())
        for (const std::string &d : it->second)
          work.push_back(d);
    }
  }
  return neededInputs;
}

} // namespace

std::vector<std::pair<std::string, std::string>>
generateParticipantViewsFromSpec(const json::Object &spec) {
  std::string name = spec.getString("procedure").value_or("").str();
  std::string version = spec.getString("specVersion").value_or("").str();
  std::string capHash = obj(spec.get("identity"), "identity")
                            .getString("capabilityHash")
                            .value_or("")
                            .str();
  int schemaVersion = (int)spec.getInteger("schemaVersion").value_or(1);
  std::string cap = "coordinate." + name;

  // visibleOperations = the canonical lifecycle machine's operation names, in
  // first-occurrence order (LifecycleModel::operationNames): the deduped
  // transition names carried in the spec's lifecycle ().
  std::vector<std::string> visibleOps;
  for (const json::Value &t :
       arrOf(obj(spec.get("lifecycle"), "lifecycle"), "transitions")) {
    std::string tn = obj(&t, "transition").getString("name").value_or("").str();
    if (std::find(visibleOps.begin(), visibleOps.end(), tn) == visibleOps.end())
      visibleOps.push_back(tn);
  }

  // sourceMap: specPath -> 1-based source line (0 when absent).
  std::map<std::string, int> lineOf;
  if (const json::Array *sm = spec.getArray("sourceMap"))
    for (const json::Value &e : *sm) {
      const json::Object &o = obj(&e, "sourceMap entry");
      std::string pp = o.getString("specPath").value_or("").str();
      if (const json::Object *src = o.getObject("source"))
        lineOf[pp] = (int)src->getInteger("line").value_or(0);
    }
  auto sourceFor = [&](const std::string &specPath) -> int {
    auto it = lineOf.find(specPath);
    return it != lineOf.end() ? it->second : 0;
  };

  // Declared inputs (name/type in order) + the compute dependency graph, for
  // reachableInputs.
  const json::Array &inputsA = arrOf(spec, "inputs");
  std::set<std::string> inputNames;
  for (const json::Value &v : inputsA)
    inputNames.insert(obj(&v, "input").getString("name").value_or("").str());
  std::map<std::string, std::vector<std::string>> computes;
  for (const json::Value &v : arrOf(spec, "computes")) {
    const json::Object &c = obj(&v, "compute");
    std::vector<std::string> deps;
    if (const json::Array *d = c.getArray("deps"))
      for (const json::Value &dv : *d)
        deps.push_back(dv.getAsString().value_or("").str());
    computes[c.getString("name").value_or("").str()] = std::move(deps);
  }

  const json::Array &effectsA = arrOf(spec, "effects");
  const json::Array *topoPairs = nullptr;
  if (const json::Object *topo = spec.getObject("topology"))
    topoPairs = topo->getArray("allowedOrgPairs");

  std::vector<std::pair<std::string, std::string>> out;
  for (const json::Value &pv : arrOf(spec, "participants")) {
    const json::Object &p = obj(&pv, "participant");
    std::string pname = p.getString("name").value_or("").str();
    std::string prole = p.getString("role").value_or("").str();
    std::string porg = p.getString("org").value_or("").str();
    bool flexible = p.getString("binding").value_or("") == "to_be_bound";

    // Legs this participant authorizes (evidence obligations) + the inputs they
    // reference (via reachableInputs). Track leg index for specPath/source.
    std::vector<size_t> legIdx;
    std::vector<std::string> usedRefs;
    auto note = [&](const std::string &r) {
      if (!r.empty() &&
          std::find(usedRefs.begin(), usedRefs.end(), r) == usedRefs.end())
        usedRefs.push_back(r);
    };
    for (size_t i = 0; i < effectsA.size(); ++i) {
      const json::Object &e = obj(&effectsA[i], "effect");
      if (e.getString("participant").value_or("") != pname)
        continue;
      legIdx.push_back(i);
      note(refName(e, "party"));
      note(refName(e, "amount"));
      note(refName(e, "currency"));
      note(refName(e, "idempotencyKey"));
      // A guarded leg () also depends on the values its `when` predicate
      // compares — include them so the participant's requiredInputs let a
      // consumer evaluate whether the obligation fires ( review).
      if (const json::Value *whenV = e.get("when")) {
        std::vector<std::string> gvars;
        collectAstVars(obj(whenV, "when").get("ast"), gvars);
        for (const std::string &gv : gvars)
          note(gv);
      }
    }
    std::set<std::string> neededInputs =
        reachableInputs(inputNames, computes, usedRefs);

    std::string o = "{\n";
    o += "  \"kind\": \"neutrino.participant-view\",\n";
    o += "  \"schemaVersion\": \"0.2.0\",\n";
    o += "  \"procedure\": " + q(name) + ",\n";
    o += "  \"dslVersion\": " + q(version) + ",\n";
    o += "  \"capability\": { \"capabilityHash\": " + q(capHash) +
         ", \"specVersion\": " + q(version) + " },\n";
    o += "  \"participant\": { \"name\": " + q(pname) +
         ", \"role\": " + q(prole);
    if (!porg.empty())
      o += ", \"org\": " + q(porg);
    o += ", \"slotId\": " + q(cap + "#" + pname) + " },\n";
    o += "  \"visibleOperations\": " + arr(visibleOps) + ",\n";

    o += "  \"requiredInputs\": [";
    bool first = true;
    for (size_t i = 0; i < inputsA.size(); ++i) {
      const json::Object &in = obj(&inputsA[i], "input");
      std::string iname = in.getString("name").value_or("").str();
      if (!neededInputs.count(iname))
        continue;
      o += (first ? "\n" : ",\n");
      o += "    { \"name\": " + q(iname) +
           ", \"type\": " + q(in.getString("type").value_or("").str()) +
           ", \"specPath\": " + q("inputs[" + std::to_string(i) + "]");
      std::string src =
          sourceObj(sourceFor("inputs[" + std::to_string(i) + "]"));
      if (!src.empty())
        o += ", \"source\": " + src;
      o += " }";
      first = false;
    }
    o += first ? "],\n" : "\n  ],\n";

    o += "  \"permittedCounterparties\": [";
    first = true;
    if (!porg.empty() && topoPairs)
      for (const json::Value &plv : *topoPairs) {
        const json::Object &pol = obj(&plv, "allowedOrgPair");
        std::string orgA = pol.getString("orgA").value_or("").str();
        std::string orgB = pol.getString("orgB").value_or("").str();
        std::string other, otherRole;
        if (orgA == porg) {
          other = orgB;
          otherRole = pol.getString("roleB").value_or("").str();
        } else if (orgB == porg) {
          other = orgA;
          otherRole = pol.getString("roleA").value_or("").str();
        } else {
          continue;
        }
        o += (first ? "\n" : ",\n");
        o += "    { \"org\": " + q(other);
        if (!otherRole.empty())
          o += ", \"role\": " + q(otherRole);
        o += " }";
        first = false;
      }
    o += first ? "],\n" : "\n  ],\n";

    if (flexible) {
      std::vector<std::string> runtimes;
      if (const json::Array *rt = p.getArray("bindRuntimes"))
        for (const json::Value &r : *rt)
          runtimes.push_back(r.getAsString().value_or("").str());
      std::string minA = p.getString("bindMinAssurance").value_or("").str();
      o += "  \"binding\": { \"mode\": \"to_be_bound\", \"runtimes\": " +
           arr(runtimes);
      if (!minA.empty())
        o += ", \"minAssurance\": " + q(minA);
      if (!porg.empty())
        o += ", \"authorizedBinder\": " + q(porg);
      o += " },\n";
    }

    o += "  \"evidenceObligations\": [";
    first = true;
    for (size_t idx : legIdx) {
      const json::Object &e = obj(&effectsA[idx], "effect");
      o += (first ? "\n" : ",\n");
      o += "    { \"leg\": " + q(e.getString("name").value_or("").str()) +
           ", \"kind\": " + q(e.getString("kind").value_or("").str()) +
           ", \"ledger\": " + q(e.getString("ledger").value_or("").str()) +
           ", \"specPath\": " + q("effects[" + std::to_string(idx) + "]");
      std::string src =
          sourceObj(sourceFor("effects[" + std::to_string(idx) + "]"));
      if (!src.empty())
        o += ", \"source\": " + src;
      o += " }";
      first = false;
    }
    o += first ? "],\n" : "\n  ],\n";

    o += "  \"provenance\": { \"derivedFrom\": \"capability-spec.json\", "
         "\"specContract\": "
         "{ \"kind\": \"neutrino.capability-spec\", \"schemaVersion\": " +
         std::to_string(schemaVersion) + " } }\n";
    o += "}\n";
    out.push_back({pname, std::move(o)});
  }
  return out;
}

} // namespace neutrino
