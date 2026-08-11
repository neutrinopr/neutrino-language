//===- FrontendEntries.cpp - .neu effect entry parser -------------------===//
//
//===----------------------------------------------------------------------===//

#include "FrontendParser.h"

#include "Neutrino/LanguageVocabulary.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/ParseUtil.h"

#include <string>
#include <utility>
#include <vector>

using namespace mlir;
using namespace neutrino;
using namespace neutrino::frontend;

LogicalResult Parser::parseEntry(llvm::StringMap<Value> &defined) {
  const Line &head = cur();
  llvm::StringRef h = llvm::StringRef(head.text);
  llvm::SmallVector<llvm::StringRef> parts;
  if (!splitBlockHeader(h, parts))
    return fail(head.no, "debit/credit header must end with '{'");
  if (parts.size() != 2 || (!tokenIsKeyword(parts[0], VocabId::debit) &&
                            !tokenIsKeyword(parts[0], VocabId::credit)))
    return fail(head.no, "malformed entry header");
  std::string kind = parts[0].str();
  std::string name = parts[1].str();
  int entryEnd; // set to the closing-brace line on the '}' break before any
                // read
  ++pos;

  llvm::StringMap<std::pair<bool, std::string>> attrs; // key -> (isRef, text)
  std::string guardText;
  while (true) {
    if (pos >= lines.size())
      return fail(head.no, "entry '" + name + "' not closed with '}'");
    const Line &ln = cur();
    llvm::StringRef t = llvm::StringRef(ln.text);
    if (t == "}") {
      entryEnd = ln.no;
      ++pos;
      break;
    }
    auto eq = t.find('=');
    if (eq == llvm::StringRef::npos)
      return fail(ln.no, "expected 'key = value', got: " + t);
    std::string key = t.take_front(eq).trim().str();
    // `when` carries a whole comparison predicate as its value (spaces +
    // comparison operators), like `compute`, so it bypasses the single-value
    // parser. The predicate is stored verbatim and parsed/typed by viewOf.
    if (tokenIsKeyword(key, VocabId::when)) {
      if (!guardText.empty())
        return fail(ln.no,
                    "duplicate attribute 'when' in entry '" + name + "'");
      guardText = t.drop_front(eq + 1).trim().str();
      if (guardText.empty())
        return fail(ln.no, "entry '" + name + "' 'when' guard is empty");
      ++pos;
      continue;
    }
    bool isRef = false;
    std::string val;
    if (failed(parseValue(t.drop_front(eq + 1), ln.no, isRef, val)))
      return failure();
    if (attrs.count(key))
      return fail(ln.no,
                  "duplicate attribute '" + key + "' in entry '" + name + "'");
    attrs[key] = {isRef, val};
    ++pos;
  }
  // A guard's referenced names must be declared inputs / computed values (the
  // scan is lexical, matching how compute deps are validated; viewOf does the
  // structural parseGuard + typeGuard).
  std::vector<Value> guardDeps;
  for (const std::string &dep : computeDeps(guardText))
    if (!defined.count(dep)) {
      return fail(head.no, "entry '" + name + "' guard references '" + dep +
                               "', which is not a declared input or computed value");
    } else {
      guardDeps.push_back(defined[dep]);
    }

  // Required fields — each spelling is obtained via vocabSpelling(VocabId::…)
  // so the vocabulary gate sees helper-mediated recognition (not a bare enum
  // mention).
  for (llvm::StringRef fname :
       {vocabSpelling(VocabId::party), vocabSpelling(VocabId::amount),
        vocabSpelling(VocabId::currency), vocabSpelling(VocabId::idempotency_key),
        vocabSpelling(VocabId::ledger), vocabSpelling(VocabId::owner)})
    if (!attrs.count(fname))
      return fail(head.no,
                  "entry '" + name + "' missing required field: " + fname.str());

  // Operand fields -> SSA values (ref lookup or const materialisation).
  auto operandFor = [&](llvm::StringRef fname, Value &out) -> LogicalResult {
    auto [isRef, text] = attrs[fname];
    if (isRef) {
      auto it = defined.find(text);
      if (it == defined.end())
        return fail(head.no, "entry '" + name + "' field '" + fname.str() +
                                 "' references %" + text +
                                 ", which is not a declared value");
      out = it->second;
    } else {
      auto c = builder.create<ConstOp>(locAt(head.no), valueType(), str(text));
      out = c.getRes();
    }
    return success();
  };
  Value party, amount, currency, idem;
  if (failed(operandFor(vocabSpelling(VocabId::party), party)) ||
      failed(operandFor(vocabSpelling(VocabId::amount), amount)) ||
      failed(operandFor(vocabSpelling(VocabId::currency), currency)) ||
      failed(operandFor(vocabSpelling(VocabId::idempotency_key), idem)))
    return failure();

  // Attribute fields must be literals.
  for (llvm::StringRef fname :
       {vocabSpelling(VocabId::ledger), vocabSpelling(VocabId::owner)}) {
    if (attrs[fname].first)
      return fail(head.no, "entry '" + name + "' field '" + fname.str() +
                               "' must be a string literal, not a %reference");
  }
  StringAttr ledger = str(attrs[vocabSpelling(VocabId::ledger)].second);
  StringAttr owner = str(attrs[vocabSpelling(VocabId::owner)].second);

  // Optional participant binding (option C): which declared participant owns/
  // authorizes this leg. A string literal naming a participant; cross-checked
  // against declarations by the Capability Security Pass.
  // Bounded exception: `participant` is a STATEMENT vocabulary entry that is
  // also reused as an optional entry-field name; recognition still goes through
  // vocabSpelling so the spelling cannot drift from the shared table.
  StringAttr participant = StringAttr();
  if (attrs.count(vocabSpelling(VocabId::participant))) {
    if (attrs[vocabSpelling(VocabId::participant)].first)
      return fail(head.no,
                  "entry '" + name +
                      "' field 'participant' must be a string literal");
    participant = str(attrs[vocabSpelling(VocabId::participant)].second);
  }

  // Optional effect metadata carried with the movement. A string literal
  // (not a %reference), surfaced in each backend's emitted event/row.
  StringAttr memo = StringAttr();
  if (attrs.count(vocabSpelling(VocabId::memo))) {
    if (attrs[vocabSpelling(VocabId::memo)].first)
      return fail(head.no,
                  "entry '" + name + "' field 'memo' must be a string literal");
    memo = str(attrs[vocabSpelling(VocabId::memo)].second);
  }

  StringAttr guard = guardText.empty() ? StringAttr() : str(guardText);
  ExprAttr guardAst;
  if (!guardText.empty() &&
      failed(buildExprAttr(guardText, "entry '" + name + "' guard", head.no,
                           defined, /*guard=*/true, guardAst)))
    return failure();
  Location eloc = locSpan(head.no, entryEnd);
  if (tokenIsKeyword(kind, VocabId::debit))
    builder.create<DebitOp>(eloc, party, amount, currency, idem,
                            ValueRange(guardDeps), str(name), ledger, owner,
                            participant, guard, guardAst, memo);
  else
    builder.create<CreditOp>(eloc, party, amount, currency, idem,
                             ValueRange(guardDeps), str(name), ledger, owner,
                             participant, guard, guardAst, memo);
  return success();
}
