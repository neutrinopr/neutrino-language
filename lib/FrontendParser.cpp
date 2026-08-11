//===- FrontendParser.cpp - .neu parser orchestration -------------------===//
//
//===----------------------------------------------------------------------===//

#include "FrontendParser.h"

#include "Neutrino/Expr.h"
#include "Neutrino/ExprAttr.h"
#include "Neutrino/LanguageVocabulary.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/ParseUtil.h"
#include "Neutrino/ValueModel.h"
#include "Neutrino/Version.h"

#include "mlir/IR/Verifier.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <cctype>
#include <map>
#include <utility>

using namespace mlir;
using namespace neutrino;
using namespace neutrino::frontend;

Parser::Parser(std::vector<Line> lines, llvm::StringRef filename,
               MLIRContext &ctx)
    : lines(std::move(lines)), filename(filename), ctx(ctx), builder(&ctx) {}

OwningOpRef<ModuleOp> Parser::parse() {
  auto module = ModuleOp::create(loc());
  builder.setInsertionPointToEnd(module.getBody());
  while (pos < lines.size()) {
    llvm::StringRef top = llvm::StringRef(cur().text);
    if (!lineStartsWithKeyword(top, VocabId::procedure) &&
        !lineStartsWithKeyword(top, VocabId::agreement)) {
      return err(cur().no, "expected 'procedure' or 'agreement'");
    }
    if (failed(parseProcedure()))
      return nullptr;
  }
  if (failed(verify(module.getOperation()))) {
    llvm::errs() << "error: built module failed verification\n";
    return nullptr;
  }
  return module;
}

Location Parser::loc() { return UnknownLoc::get(&ctx); }

Location Parser::locAt(int line) {
  return FileLineColLoc::get(builder.getStringAttr(filename), (unsigned)line,
                             1);
}

Location Parser::locSpan(int startLine, int endLine) {
  return builder.getFusedLoc({locAt(startLine), locAt(endLine)});
}

const Line &Parser::cur() { return lines[pos]; }

OwningOpRef<ModuleOp> Parser::err(int line, const llvm::Twine &msg) {
  llvm::errs() << filename << ":" << line << ": error: " << msg << "\n";
  return nullptr;
}

LogicalResult Parser::fail(int line, const llvm::Twine &msg) {
  llvm::errs() << filename << ":" << line << ": error: " << msg << "\n";
  return failure();
}

StringAttr Parser::str(llvm::StringRef s) { return builder.getStringAttr(s); }

Type Parser::valueType() { return ValueType::get(&ctx); }

ValueCategory Parser::catOf(Value v) {
  Operation *d = v.getDefiningOp();
  if (auto in = llvm::dyn_cast_or_null<InputOp>(d))
    return classifyValueType(in.getTy());
  if (auto c = llvm::dyn_cast_or_null<ComputeOp>(d))
    return categoryFromName(c.getAst().getDtype());
  return ValueCategory::Extension;
}

LogicalResult Parser::buildExprAttr(llvm::StringRef text, llvm::StringRef what,
                                    int line,
                                    const llvm::StringMap<Value> &defined,
                                    bool guard, ExprAttr &out) {
  std::map<std::string, ValueCategory> env;
  llvm::StringMap<int64_t> slotOf;
  int64_t slot = 0;
  for (const std::string &dep : computeDeps(text)) {
    auto it = defined.find(dep);
    if (it != defined.end())
      env[dep] = catOf(it->second);
    slotOf[dep] = slot++;
  }

  ExprPtr node;
  try {
    node = guard ? parseGuard(text) : parseExpr(text);
  } catch (const ExprError &e) {
    emitError(locAt(line)) << "[" << e.code << "] " << what << ": " << e.what();
    return failure();
  }

  try {
    if (guard)
      typeGuard(*node, env);
    else
      typeExpr(*node, env);
  } catch (const ExprError &) {
  }

  out = toExprAttr(*node, &ctx, slotOf);
  return success();
}

// value token -> (isRef, text). Pure classification lives in ParseUtil; this
// wrapper attaches the parser's `filename:line` diagnostic on failure.
LogicalResult Parser::parseValue(llvm::StringRef tok, int line, bool &isRef,
                                 std::string &out) {
  tok = tok.trim();
  if (parseValueToken(tok, isRef, out))
    return success();
  return fail(
      line, "attribute value must be a \"literal\" or %reference, got: " + tok);
}

// Collect the double-quoted substrings on a line (deterministic,
// left-to-right). Pure scanning lives in ParseUtil; this wrapper attaches the
// diagnostic.
LogicalResult Parser::quotedStrings(llvm::StringRef t, int line,
                                    llvm::SmallVectorImpl<std::string> &out) {
  if (collectQuotedStrings(t, out))
    return success();
  return fail(line, "unterminated string literal");
}

LogicalResult Parser::parseProcedure() {
  explicitParticipants.clear(); // names are scoped to this procedure
  const Line &head = cur();
  llvm::StringRef h = llvm::StringRef(head.text);
  llvm::SmallVector<llvm::StringRef> parts;
  if (!splitBlockHeader(h, parts))
    return fail(head.no, "procedure header must end with '{'");

  // Two header forms:
  //   procedure NAME { ... }
  //   agreement NAME between A and B { ... }   (sugar; desugars below)
  std::string procName;
  llvm::SmallVector<std::string> agreementParties;
  if (!parts.empty() && tokenIsKeyword(parts[0], VocabId::procedure)) {
    if (parts.size() != 2)
      return fail(head.no, "malformed procedure header");
    procName = parts[1].str();
  } else if (!parts.empty() && tokenIsKeyword(parts[0], VocabId::agreement)) {
    if (parts.size() != 6 || !tokenIsKeyword(parts[2], VocabId::between) ||
        !tokenIsKeyword(parts[4], VocabId::and_))
      return fail(
          head.no,
          "agreement header must be 'agreement NAME between A and B {'");
    procName = parts[1].str();
    agreementParties.push_back(parts[3].str());
    agreementParties.push_back(parts[5].str());
  } else {
    return fail(head.no, "malformed procedure header");
  }
  ++pos;

  // Build the ProcedureOp with a single-block region. Start at the header line;
  // the closing '}' line extends it to a full span below.
  int procStart = head.no;
  auto proc =
      builder.create<ProcedureOp>(locAt(procStart), str(procName), StringAttr(),
                                  StringAttr(), StringAttr());
  Block *block = builder.createBlock(&proc.getBody());

  // Save/restore insertion point around the body.
  OpBuilder::InsertionGuard guard(builder);
  builder.setInsertionPointToStart(block);

  // `agreement ... between A and B` desugars to two declared participants
  // (default role = the party name lowercased). A later `participant A { ... }`
  // block augments this declaration (e.g. adds an org / overrides the role)
  // rather than duplicating it — see parseParticipant.
  for (const std::string &party : agreementParties) {
    std::string role = party;
    std::transform(role.begin(), role.end(), role.begin(),
                   [](unsigned char c) { return std::tolower(c); });
    builder.create<ParticipantOp>(locAt(procStart), str(party), str(role),
                                  ArrayAttr(), StringAttr(), StringAttr(),
                                  ArrayAttr(), StringAttr());
  }

  llvm::StringMap<Value> defined;

  while (true) {
    if (pos >= lines.size())
      return fail(head.no, "procedure '" + procName + "' not closed with '}'");
    const Line &ln = cur();
    llvm::StringRef t = llvm::StringRef(ln.text);
    llvm::StringRef rest;
    if (t == "}") {
      proc->setLoc(locSpan(procStart, ln.no)); // header .. closing '}'
      ++pos;
      break;
    } else if (matchKeywordPrefix(t, VocabId::trigger, rest)) {
      proc.setTriggerAttr(str(rest.trim()));
      ++pos;
    } else if (matchKeywordPrefix(t, VocabId::version, rest)) {
      // Capability versions accept either a fully double-quoted SemVer token
      // or a bare SemVer token. A half-quoted token is rejected so malformed
      // source cannot be silently normalized.
      llvm::StringRef raw = rest.trim();
      llvm::StringRef v;
      if (!unquoteVersionToken(raw, v))
        return fail(ln.no,
                    "version has an unbalanced quote: write a quoted "
                    "\"MAJOR.MINOR.PATCH\" or a bare MAJOR.MINOR.PATCH, got: " +
                        raw.str());
      if (!isValidSemVer(v))
        return fail(ln.no, "version must be a semantic version "
                           "MAJOR.MINOR.PATCH, got: \"" +
                               v.str() + "\"");
      proc.setVersionAttr(str(v));
      ++pos;
    } else if (matchKeywordPrefix(t, VocabId::instance_key, rest)) {
      llvm::StringRef key = rest.trim();
      if (key.empty())
        return fail(ln.no, "instance_key requires an input name");
      if (proc.getInstanceKeyAttr())
        return fail(ln.no, "duplicate instance_key declaration");
      proc.setInstanceKeyAttr(str(key));
      ++pos;
    } else if (matchKeywordPrefix(t, VocabId::input, rest)) {
      if (failed(parseInput(rest, ln.no, defined)))
        return failure();
      ++pos;
    } else if (matchKeywordPrefix(t, VocabId::compute, rest)) {
      if (failed(parseCompute(rest, ln.no, defined)))
        return failure();
      ++pos;
    } else if (lineStartsWithKeyword(t, VocabId::participant)) {
      if (failed(parseParticipant()))
        return failure();
    } else if (lineStartsWithKeyword(t, VocabId::allow)) {
      if (failed(
              parseAllow())) // consumes its own line(s), incl. optional block
        return failure();
    } else if (lineStartsWithKeyword(t, VocabId::attest)) {
      if (failed(parseAttest(defined))) // consumes its own block
        return failure();
    } else if (lineStartsWithKeyword(t, VocabId::debit) ||
               lineStartsWithKeyword(t, VocabId::credit)) {
      if (failed(parseEntry(defined)))
        return failure();
    } else if (matchKeywordPrefix(t, VocabId::assert_, rest)) {
      llvm::StringRef which = rest.trim();
      if (!tokenIsKeyword(which, VocabId::balanced))
        return fail(ln.no,
                    "only 'assert balanced' is supported, got: " + which);
      builder.create<AssertBalancedOp>(locAt(ln.no));
      ++pos;
    } else {
      return fail(ln.no, "unexpected statement: " + t);
    }
  }

  // Auto-allow: an agreement between A and B whose participants declare
  // (differing) orgs implies those orgs may coordinate — emit the org-pair
  // policy so `agreement` is a one-liner that still satisfies the topology
  // gate.
  //
  // But explicit `allow` is authoritative: the inference fires only when the
  // body declares NO org-pair policy at all. The moment the author writes any
  // `allow`, they own the full policy and we infer nothing — so a wrong or
  // incomplete explicit `allow` (e.g. naming the wrong counterparty) correctly
  // fails the topology gate instead of being silently broadened by the inferred
  // pair.
  if (!agreementParties.empty()) {
    auto allows = block->getOps<AllowOrgsOp>();
    bool anyExplicitPolicy = allows.begin() != allows.end();
    if (!anyExplicitPolicy) {
      auto orgOf = [&](llvm::StringRef name) -> std::string {
        for (auto p : block->getOps<ParticipantOp>())
          if (p.getSymName() == name)
            return p.getOrgAttr() ? p.getOrgAttr().getValue().str()
                                  : std::string();
        return std::string();
      };
      std::string orgA = orgOf(agreementParties[0]);
      std::string orgB = orgOf(agreementParties[1]);
      if (!orgA.empty() && !orgB.empty() && orgA != orgB) {
        // Inferred permission carries no role constraints (empty roleA/roleB).
        builder.setInsertionPointToEnd(block);
        builder.create<AllowOrgsOp>(locAt(procStart), str(orgA), str(orgB),
                                    StringAttr(), StringAttr());
      }
    }
  }
  return success();
}
