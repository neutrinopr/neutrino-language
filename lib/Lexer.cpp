//===- Lexer.cpp - .neu lexing (logical lines) ------------------===//
//
// The front-end's lexing step, separated from the parser/builder (T9 R1 parser
// decomposition): turn raw source into the non-blank, comment-stripped, trimmed
// logical lines the line-oriented parser consumes. Behavior is byte-identical
// to the previous in-Frontend implementation.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/Lexer.h"

#include "llvm/ADT/SmallVector.h"

namespace {

// Strip // and # comments and return the prefix before the first comment marker.
// Markers inside a double-quoted string literal are NOT comments, so a value like
// "https://api.example" or "ACME " survives intact.
std::string stripComment(llvm::StringRef line) {
  bool inStr = false;
  for (size_t i = 0; i < line.size(); ++i) {
    char c = line[i];
    if (c == '"') {
      inStr = !inStr;
    } else if (!inStr && (c == '#' || (c == '/' && i + 1 < line.size() && line[i + 1] == '/'))) {
      return line.substr(0, i).str();
    }
  }
  return line.str();
}

} // namespace

std::vector<neutrino::Line> neutrino::logicalLines(llvm::StringRef text) {
  std::vector<Line> out;
  int n = 0;
  llvm::SmallVector<llvm::StringRef> raw;
  text.split(raw, '\n');
  for (llvm::StringRef ln : raw) {
    ++n;
    std::string s = stripComment(ln);
    llvm::StringRef trimmed = llvm::StringRef(s).trim();
    if (!trimmed.empty())
      out.push_back({n, trimmed.str()});
  }
  return out;
}
