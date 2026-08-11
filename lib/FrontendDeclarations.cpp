//===- FrontendDeclarations.cpp - .neu declarations parser --------------===//
//
//===----------------------------------------------------------------------===//

#include "FrontendParser.h"

#include "Neutrino/LanguageVocabulary.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/ParseUtil.h"

#include <string>
#include <vector>

using namespace mlir;
using namespace neutrino;
using namespace neutrino::frontend;

LogicalResult Parser::parseInput(llvm::StringRef rest, int line,
                                 llvm::StringMap<Value> &defined) {
  // `rest` is the text after the leading "input " keyword (matched by caller).
  auto colon = rest.find(':');
  if (colon == llvm::StringRef::npos)
    return fail(line, "input must be 'input NAME : TYPE'");
  std::string name = rest.take_front(colon).trim().str();
  std::string ty = rest.drop_front(colon + 1).trim().str();
  if (name.empty() || ty.empty())
    return fail(line, "input must be 'input NAME : TYPE'");
  if (defined.count(name))
    return fail(line, "name '" + name + "' declared more than once");
  auto op =
      builder.create<InputOp>(locAt(line), valueType(), str(name), str(ty));
  defined[name] = op.getRes();
  return success();
}

LogicalResult Parser::parseCompute(llvm::StringRef rest, int line,
                                   llvm::StringMap<Value> &defined) {
  // `rest` is the text after the leading "compute " keyword (matched by caller).
  auto eq = rest.find('=');
  if (eq == llvm::StringRef::npos)
    return fail(line, "compute must be 'compute NAME = EXPR'");
  std::string name = rest.take_front(eq).trim().str();
  std::string expr = rest.drop_front(eq + 1).trim().str();
  if (name.empty() || expr.empty())
    return fail(line, "compute must be 'compute NAME = EXPR'");
  if (defined.count(name))
    return fail(line, "name '" + name + "' declared more than once");

  std::vector<Value> deps;
  for (const std::string &dep : computeDeps(expr)) {
    auto it = defined.find(dep);
    if (it == defined.end())
      return fail(line,
                  "compute '" + name + "' references '" + dep +
                      "', which is not a declared input or computed value");
    deps.push_back(it->second);
  }
  ExprAttr ast;
  if (failed(buildExprAttr(expr, "compute '" + name + "'", line, defined,
                           /*guard=*/false, ast)))
    return failure();
  auto op = builder.create<ComputeOp>(
      locAt(line), valueType(), ValueRange(deps), str(name), str(expr), ast);
  defined[name] = op.getRes();
  return success();
}

// participant NAME { role = "..."; capabilities = ["...", ...] }
LogicalResult Parser::parseParticipant() {
  const Line &head = cur();
  llvm::StringRef h = llvm::StringRef(head.text);
  llvm::SmallVector<llvm::StringRef> parts;
  if (!splitBlockHeader(h, parts))
    return fail(head.no, "participant header must end with '{'");
  if (parts.size() != 2 || !tokenIsKeyword(parts[0], VocabId::participant))
    return fail(head.no, "malformed participant header");
  std::string name = parts[1].str();
  ++pos;

  std::string role, org;
  bool haveRole = false;
  llvm::SmallVector<std::string> caps;
  std::string binding, bindMinAssurance;
  llvm::SmallVector<std::string> bindRuntimes;
  int partEnd; // set to the closing-brace line on the '}' break before any read
  while (true) {
    if (pos >= lines.size())
      return fail(head.no, "participant '" + name + "' not closed with '}'");
    const Line &ln = cur();
    llvm::StringRef t = llvm::StringRef(ln.text);
    if (t == "}") {
      partEnd = ln.no;
      ++pos;
      break;
    }
    auto eq = t.find('=');
    if (eq == llvm::StringRef::npos)
      return fail(ln.no, "expected 'key = value', got: " + t.str());
    std::string key = t.take_front(eq).trim().str();
    llvm::StringRef rhs = t.drop_front(eq + 1).trim();
    if (tokenIsKeyword(key, VocabId::role)) {
      bool isRef = false;
      std::string val;
      if (failed(parseValue(rhs, ln.no, isRef, val)))
        return failure();
      if (isRef)
        return fail(ln.no, "participant 'role' must be a string literal");
      role = val;
      haveRole = true;
    } else if (tokenIsKeyword(key, VocabId::capabilities)) {
      if (!rhs.startswith("[") || !rhs.endswith("]"))
        return fail(ln.no,
                    "participant 'capabilities' must be a [\"...\", ...] list");
      llvm::StringRef inner = rhs.drop_front().drop_back().trim();
      if (!inner.empty()) {
        llvm::SmallVector<llvm::StringRef> items;
        inner.split(items, ',', -1, false);
        for (llvm::StringRef item : items) {
          bool isRef = false;
          std::string val;
          if (failed(parseValue(item.trim(), ln.no, isRef, val)))
            return failure();
          if (isRef)
            return fail(ln.no, "capability entries must be string literals");
          caps.push_back(val);
        }
      }
    } else if (tokenIsKeyword(key, VocabId::org)) {
      bool isRef = false;
      std::string val;
      if (failed(parseValue(rhs, ln.no, isRef, val)))
        return failure();
      if (isRef)
        return fail(ln.no, "participant 'org' must be a string literal");
      org = val;
    } else if (tokenIsKeyword(key, VocabId::binding)) {
      bool isRef = false;
      std::string val;
      if (failed(parseValue(rhs, ln.no, isRef, val)))
        return failure();
      if (isRef || (val != "to_be_bound" && val != "fixed"))
        return fail(ln.no, "participant 'binding' must be \"to_be_bound\" or "
                           "\"fixed\", got: " +
                               rhs.str());
      binding = (val == "to_be_bound") ? val : ""; // "fixed" == no policy
    } else if (tokenIsKeyword(key, VocabId::bind_runtimes)) {
      if (!rhs.startswith("[") || !rhs.endswith("]"))
        return fail(
            ln.no, "participant 'bind_runtimes' must be a [\"...\", ...] list");
      llvm::StringRef inner = rhs.drop_front().drop_back().trim();
      if (!inner.empty()) {
        llvm::SmallVector<llvm::StringRef> items;
        inner.split(items, ',', -1, false);
        for (llvm::StringRef item : items) {
          bool isRef = false;
          std::string val;
          if (failed(parseValue(item.trim(), ln.no, isRef, val)))
            return failure();
          if (isRef)
            return fail(ln.no, "bind_runtimes entries must be string literals");
          if (llvm::StringRef(val).trim().empty())
            return fail(
                ln.no,
                "bind_runtimes entries must be non-empty runtime "
                "families (it is the allow-list a binding is checked against)");
          bindRuntimes.push_back(val);
        }
      }
    } else if (tokenIsKeyword(key, VocabId::bind_min_assurance)) {
      bool isRef = false;
      std::string val;
      if (failed(parseValue(rhs, ln.no, isRef, val)))
        return failure();
      if (isRef || !(val == "A1" || val == "A2" || val == "A3" || val == "A4"))
        return fail(ln.no, "participant 'bind_min_assurance' must be one of "
                           "\"A1\"/\"A2\"/\"A3\"/\"A4\", got: " +
                               rhs.str());
      bindMinAssurance = val;
    } else {
      return fail(ln.no,
                  "unknown participant field '" + key +
                      "' (expected 'role', 'capabilities', 'org', "
                      "'binding', 'bind_runtimes', or 'bind_min_assurance')");
    }
    ++pos;
  }
  llvm::SmallVector<llvm::StringRef> capRefs(caps.begin(), caps.end());
  ArrayAttr capsAttr =
      caps.empty() ? ArrayAttr() : builder.getStrArrayAttr(capRefs);
  StringAttr orgAttr = org.empty() ? StringAttr() : str(org);

  // Late-binding policy: the bind_* fields only apply to a to_be_bound
  // participant, and a flexible participant must declare its allowed runtimes
  // (conservative default — no open-ended binding surface).
  bool flexible = (binding == "to_be_bound");
  if (!flexible && (!bindRuntimes.empty() || !bindMinAssurance.empty()))
    return fail(head.no, "participant '" + name +
                             "' sets bind_* policy without "
                             "binding = \"to_be_bound\"");
  if (flexible && bindRuntimes.empty())
    return fail(head.no,
                "participant '" + name +
                    "' is binding = \"to_be_bound\" but "
                    "declares no bind_runtimes (allowed runtime families)");
  if (flexible && org.empty())
    return fail(
        head.no,
        "participant '" + name +
            "' is binding = \"to_be_bound\" but "
            "declares no org — the authorized binder would be unspecified; "
            "a late-bound slot must name the org permitted to bind it");
  llvm::SmallVector<llvm::StringRef> rtRefs(bindRuntimes.begin(),
                                            bindRuntimes.end());
  StringAttr bindingAttr = binding.empty() ? StringAttr() : str(binding);
  ArrayAttr bindRtAttr =
      bindRuntimes.empty() ? ArrayAttr() : builder.getStrArrayAttr(rtRefs);
  StringAttr bindMaAttr =
      bindMinAssurance.empty() ? StringAttr() : str(bindMinAssurance);

  // If a participant with this name was already declared, augment it rather
  // than duplicating — but ONLY when the prior declaration was a
  // pre-declaration from an `agreement ... between` header (set only the fields
  // given here; role is then optional). Two explicit `participant` blocks for
  // the same name are a duplicate (the second would silently overwrite the
  // first), so reject them.
  Block *block = builder.getInsertionBlock();
  for (auto existing : block->getOps<ParticipantOp>()) {
    if (existing.getSymName() == name) {
      if (explicitParticipants.contains(name))
        return fail(head.no,
                    "participant '" + name + "' declared more than once");
      if (haveRole)
        existing.setRoleAttr(str(role));
      if (capsAttr)
        existing.setCapabilitiesAttr(capsAttr);
      if (orgAttr)
        existing.setOrgAttr(orgAttr);
      if (bindingAttr)
        existing.setBindingAttr(bindingAttr);
      if (bindRtAttr)
        existing.setBindRuntimesAttr(bindRtAttr);
      if (bindMaAttr)
        existing.setBindMinAssuranceAttr(bindMaAttr);
      // The explicit block is the authoritative declaration site — point the
      // outline at its full span (the prior loc was the agreement header).
      existing->setLoc(locSpan(head.no, partEnd));
      explicitParticipants.insert(name);
      return success();
    }
  }

  if (!haveRole)
    return fail(head.no,
                "participant '" + name + "' missing required field: role");
  explicitParticipants.insert(name);
  builder.create<ParticipantOp>(locSpan(head.no, partEnd), str(name), str(role),
                                capsAttr, orgAttr, bindingAttr, bindRtAttr,
                                bindMaAttr);
  return success();
}
