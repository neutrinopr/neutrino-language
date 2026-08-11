//===- ParseUtil.cpp - pure DSL token/expression helpers -----------------===//
//
// The front-end's pure token/expression scanning, separated from the
// parser/builder (T9 R1 parser decomposition). These functions are byte-for-byte
// the logic previously inlined in Frontend.cpp's Parser; they do not emit
// diagnostics or touch MLIR/parser state, so behavior is identical and the
// parser keeps owning `filename:line` error emission.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/ParseUtil.h"

#include "llvm/ADT/STLExtras.h"

#include <cctype>

std::vector<std::string> neutrino::computeDeps(llvm::StringRef expr) {
  std::vector<std::string> out;
  size_t i = 0;
  auto isIdentStart = [](char c) { return isalpha((unsigned char)c) || c == '_'; };
  auto isIdent = [](char c) { return isalnum((unsigned char)c) || c == '_'; };
  while (i < expr.size()) {
    if (isIdentStart(expr[i])) {
      size_t j = i;
      while (j < expr.size() && isIdent(expr[j]))
        ++j;
      std::string name = expr.substr(i, j - i).str();
      size_t k = j;
      while (k < expr.size() && isspace((unsigned char)expr[k]))
        ++k;
      bool isCall = (k < expr.size() && expr[k] == '(');
      if (!isCall && !llvm::is_contained(out, name))
        out.push_back(name);
      i = j;
    } else {
      ++i;
    }
  }
  return out;
}

bool neutrino::parseValueToken(llvm::StringRef tok, bool &isRef, std::string &out) {
  tok = tok.trim();
  if (tok.size() >= 2 && tok.front() == '"' && tok.back() == '"') {
    isRef = false;
    out = tok.drop_front().drop_back().str();
    return true;
  }
  if (tok.startswith("%") && tok.size() > 1) {
    isRef = true;
    out = tok.drop_front().str();
    return true;
  }
  return false;
}

bool neutrino::collectQuotedStrings(llvm::StringRef t,
                                    llvm::SmallVectorImpl<std::string> &out) {
  size_t i = 0;
  while (i < t.size()) {
    if (t[i] == '"') {
      size_t j = t.find('"', i + 1);
      if (j == llvm::StringRef::npos)
        return false;
      out.push_back(t.substr(i + 1, j - i - 1).str());
      i = j + 1;
    } else {
      ++i;
    }
  }
  return true;
}

bool neutrino::splitBlockHeader(llvm::StringRef header,
                                llvm::SmallVectorImpl<llvm::StringRef> &words) {
  if (!header.endswith("{"))
    return false;
  header.drop_back().trim().split(words, ' ', -1, false);
  return true;
}

bool neutrino::takeQuotedWord(llvm::StringRef &s, std::string &out) {
  s = s.ltrim();
  if (s.empty() || s.front() != '"')
    return false;
  size_t end = s.find('"', 1);
  if (end == llvm::StringRef::npos)
    return false;
  out = s.substr(1, end - 1).str();
  s = s.drop_front(end + 1);
  return true;
}

bool neutrino::consumeKeyword(llvm::StringRef &s, llvm::StringRef kw) {
  s = s.ltrim();
  if (!s.consume_front(kw))
    return false;
  return s.empty() || s.front() == ' ' || s.front() == '\t' || s.front() == '"';
}

bool neutrino::unquoteVersionToken(llvm::StringRef raw, llvm::StringRef &v) {
  if (raw.size() >= 2 && raw.front() == '"' && raw.back() == '"') {
    v = raw.drop_front().drop_back(); // fully quoted
    return true;
  }
  if (!raw.empty() && (raw.front() == '"' || raw.back() == '"'))
    return false; // unbalanced (one stray quote)
  v = raw;        // bare
  return true;
}
