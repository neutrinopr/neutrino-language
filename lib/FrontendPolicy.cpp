//===- FrontendPolicy.cpp - .neu policy parser --------------------------===//
//
//===----------------------------------------------------------------------===//

#include "FrontendParser.h"

#include "Neutrino/Attestation.h"
#include "Neutrino/LanguageVocabulary.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/ParseUtil.h"
#include "Neutrino/ValueModel.h"

#include <string>

using namespace mlir;
using namespace neutrino;
using namespace neutrino::frontend;

// allow "OrgA" with "OrgB"                — permit two orgs to coordinate; or
// allow "OrgA" with "OrgB" {              — additionally constrain the role
// each
//     "OrgA" as "roleA"                     org's actors may take (optional,
//     one "OrgB" as "roleB"                     line per side; org must be in
//     the pair).
// }
// parseAllow consumes its own lines (header + optional block).
LogicalResult Parser::parseAllow() {
  const Line &ln = cur();
  llvm::StringRef t = llvm::StringRef(ln.text);
  bool hasBlock = t.rtrim().endswith("{");
  // Enforce the full grammar `allow "A" with "B"` (optionally `{`), not just
  // "two quoted strings" — otherwise a typoed connective like
  // `allow "a" banana "b"` would parse into an authoritative policy. The
  // whole-word keyword and quoted-word scanners are pure (ParseUtil /
  // LanguageVocabulary).
  llvm::StringRef rest = t.rtrim();
  if (hasBlock)
    rest = rest.drop_back().rtrim(); // strip the trailing '{'
  std::string orgA, orgB;
  const char *grammar = "'allow' policy must be: allow \"A\" with \"B\"";
  if (!consumeVocabKeyword(rest, VocabId::allow) || !takeQuotedWord(rest, orgA) ||
      !consumeVocabKeyword(rest, VocabId::with) || !takeQuotedWord(rest, orgB))
    return fail(ln.no, grammar);
  if (!rest.ltrim().empty())
    return fail(ln.no, std::string(grammar) + " (unexpected trailing text '" +
                           rest.ltrim().str() + "')");
  ++pos;

  int allowStart = ln.no, allowEnd = ln.no;
  std::string roleA, roleB;
  if (hasBlock) {
    while (true) {
      if (pos >= lines.size())
        return fail(ln.no, "'allow' block not closed with '}'");
      const Line &bl = cur();
      llvm::StringRef b = llvm::StringRef(bl.text);
      if (b == "}") {
        allowEnd = bl.no;
        ++pos;
        break;
      }
      llvm::SmallVector<std::string> q;
      if (failed(quotedStrings(b, bl.no, q)))
        return failure();
      if (q.size() != 2 || !lineContainsKeywordWord(b, VocabId::as))
        return fail(bl.no,
                    "allow constraint must be 'ORG as ROLE', got: " + b.str());
      if (q[0] == orgA)
        roleA = q[1];
      else if (q[0] == orgB)
        roleB = q[1];
      else
        return fail(bl.no, "allow constraint org '" + q[0] +
                               "' is not one of the pair \"" + orgA + "\"/\"" +
                               orgB + "\"");
      ++pos;
    }
  }

  StringAttr ra = roleA.empty() ? StringAttr() : str(roleA);
  StringAttr rb = roleB.empty() ? StringAttr() : str(roleB);
  Location aloc = hasBlock ? locSpan(allowStart, allowEnd) : locAt(allowStart);
  builder.create<AllowOrgsOp>(aloc, str(orgA), str(orgB), ra, rb);
  return success();
}

// parseAttest consumes an `attest <evidence_input> { ... }` block. It reads the
// key=value body, then fails closed via the shared contract validator so the
// frontend and the IR-level AttestOp verifier reject the same shapes. The
// referenced input must be a declared `evidence` input (a cross-op check only
// the frontend, which holds the input table, can make).
LogicalResult Parser::parseAttest(llvm::StringMap<Value> &defined) {
  const Line &head = cur();
  llvm::StringRef h = llvm::StringRef(head.text);
  llvm::SmallVector<llvm::StringRef> parts;
  if (!splitBlockHeader(h, parts))
    return fail(head.no, "attest header must end with '{'");
  if (parts.size() != 2 || !tokenIsKeyword(parts[0], VocabId::attest))
    return fail(head.no, "attest header must be 'attest <evidence_input> {'");
  std::string input = parts[1].str();
  ++pos;

  // The policy carried by this input; the input's category is validated
  // below.
  AttestationPolicy p;
  p.input = input;
  bool haveQuorum = false;
  while (true) {
    if (pos >= lines.size())
      return fail(head.no, "attest '" + input + "' not closed with '}'");
    const Line &ln = cur();
    llvm::StringRef t = llvm::StringRef(ln.text);
    if (t == "}") {
      ++pos;
      break;
    }
    auto eq = t.find('=');
    if (eq == llvm::StringRef::npos)
      return fail(ln.no, "expected 'key = value', got: " + t.str());
    std::string key = t.take_front(eq).trim().str();
    llvm::StringRef rhs = t.drop_front(eq + 1).trim();

    // `quorum` is a bare positive integer (the M threshold); everything else
    // is a string literal.
    if (tokenIsKeyword(key, VocabId::quorum)) {
      long long q = 0;
      if (rhs.getAsInteger(10, q))
        return fail(ln.no,
                    "attest 'quorum' must be an integer, got: " + rhs.str());
      p.quorum = (int)q;
      haveQuorum = true;
      ++pos;
      continue;
    }
    bool isRef = false;
    std::string val;
    if (failed(parseValue(rhs, ln.no, isRef, val)))
      return failure();
    if (isRef)
      return fail(ln.no, "attest '" + key + "' must be a string literal");
    if (tokenIsKeyword(key, VocabId::observer_set))
      p.observerSet = val;
    else if (tokenIsKeyword(key, VocabId::observer_role))
      p.observerRole = val;
    else if (tokenIsKeyword(key, VocabId::assurance))
      p.assurance = val;
    else if (tokenIsKeyword(key, VocabId::independence))
      p.independence = val;
    else if (tokenIsKeyword(key, VocabId::canonicalization))
      p.canonicalization = val;
    else if (tokenIsKeyword(key, VocabId::tolerance))
      p.tolerance = val;
    else if (tokenIsKeyword(key, VocabId::timeout))
      p.timeout = val;
    else if (tokenIsKeyword(key, VocabId::fallback))
      p.fallback = val;
    else
      return fail(ln.no, "unknown attest field: " + key);
    ++pos;
  }

  // Cross-op: the policy must attach to a declared `evidence` input (not a
  // compute, not a non-evidence input, not an undeclared name).
  auto it = defined.find(input);
  if (it == defined.end())
    return fail(head.no, "attest references undeclared input '" + input + "'");
  auto in = it->second.getDefiningOp<InputOp>();
  if (!in || classifyValueType(in.getTy()) != ValueCategory::Evidence)
    return fail(head.no, "attest '" + input +
                             "' must reference an input of type 'evidence'");

  // Fail closed on the four rejected shapes, using the shared contract
  // validator so the message matches the IR-level verifier. `quorum` absent
  // defaults to 0, which the validator rejects as a non-positive threshold.
  (void)haveQuorum;
  if (std::string err = validateAttestationPolicy(p); !err.empty())
    return fail(head.no, err);

  builder.create<AttestOp>(
      locAt(head.no), str(p.input), (int64_t)p.quorum, str(p.observerSet),
      str(p.canonicalization), str(p.fallback),
      p.observerRole.empty() ? StringAttr() : str(p.observerRole),
      p.tolerance.empty() ? StringAttr() : str(p.tolerance),
      p.timeout.empty() ? StringAttr() : str(p.timeout),
      p.assurance.empty() ? StringAttr() : str(p.assurance),
      p.independence.empty() ? StringAttr() : str(p.independence));
  return success();
}
