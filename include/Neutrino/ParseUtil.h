#ifndef NEUTRINO_PARSEUTIL_H
#define NEUTRINO_PARSEUTIL_H

#include "llvm/ADT/SmallVector.h"
#include "llvm/ADT/StringRef.h"

#include <string>
#include <vector>

namespace neutrino {

// Pure token/expression helpers for the front-end, separated from the
// parser/builder (T9 R1 parser decomposition). None of these touch MLIR or
// parser state; they classify/scan raw DSL text and leave diagnostics to the
// caller, so the parser keeps owning `filename:line` error emission.

// First-appearance-ordered, de-duplicated identifier references in an opaque
// compute expression, excluding function calls (an identifier immediately
// followed by '('). Used to wire a `compute` op's SSA operands.
std::vector<std::string> computeDeps(llvm::StringRef expr);

// Classify a single attribute value token as either a "quoted literal" or a
// %reference. Trims the token, then on success sets (isRef, out) and returns
// true; returns false if the token is neither (the caller emits the diagnostic).
bool parseValueToken(llvm::StringRef tok, bool &isRef, std::string &out);

// Collect the double-quoted substrings of `t`, left-to-right (deterministic).
// Returns false if a quote is left unterminated (the caller emits the
// diagnostic); `out` may hold the complete pairs seen before that point.
bool collectQuotedStrings(llvm::StringRef t,
                          llvm::SmallVectorImpl<std::string> &out);

// Tokenize a block-opening header line "KEYWORD ARG... {": strip the trailing
// '{' and space-split the remainder (empty tokens dropped) into `words`. Returns
// false if the line does not end with '{' (the caller emits the diagnostic). The
// returned StringRefs alias `header`'s buffer, so it must outlive `words`.
bool splitBlockHeader(llvm::StringRef header,
                      llvm::SmallVectorImpl<llvm::StringRef> &words);

// `allow`-policy grammar scanners that consume from the front of `s` in place,
// so a typoed connective (e.g. `allow "a" banana "b"`) fails the grammar instead
// of parsing into a policy. takeQuotedWord: if `s` (after ltrim) starts with a
// "double-quoted" word, set `out` to its contents, advance `s` past the closing
// quote, and return true.
bool takeQuotedWord(llvm::StringRef &s, std::string &out);
// consumeKeyword: if `s` (after ltrim) begins with the whole word `kw` (followed
// by whitespace, EOL, or a quote), advance `s` past it and return true.
bool consumeKeyword(llvm::StringRef &s, llvm::StringRef kw);

// Unwrap an optionally-double-quoted `version` token: a fully `"quoted"` value
// yields its contents and a bare value passes through. Returns false on an
// unbalanced quote (exactly one stray quote at an end), which the caller reports;
// SemVer validity is a separate check (isValidSemVer). On success `v` aliases
// `raw`'s buffer.
bool unquoteVersionToken(llvm::StringRef raw, llvm::StringRef &v);

} // namespace neutrino

#endif // NEUTRINO_PARSEUTIL_H
