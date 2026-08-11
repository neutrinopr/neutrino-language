#ifndef NEUTRINO_LEXER_H
#define NEUTRINO_LEXER_H

#include "llvm/ADT/StringRef.h"

#include <string>
#include <vector>

namespace neutrino {

// One non-blank logical source line: its 1-based line number and the
// comment-stripped, trimmed text.
struct Line {
  int no;
  std::string text;
};

// Split source into non-blank logical lines: strip `//` and `#` comments (markers
// inside a double-quoted string literal are preserved, so "https://x" / "ACME "
// survive), trim whitespace, and drop blank lines. This is the front-end's lexing
// step, separated from the parser/builder (T9 R1 parser decomposition).
std::vector<Line> logicalLines(llvm::StringRef text);

} // namespace neutrino

#endif // NEUTRINO_LEXER_H
