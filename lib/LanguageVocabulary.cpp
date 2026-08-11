//===- LanguageVocabulary.cpp - shared .neu keyword vocabulary ----------===//
//
// Expands LanguageVocabulary.def into the runtime table and implements the
// approved recognition helpers the frontend uses ().
//
//===----------------------------------------------------------------------===//

#include "Neutrino/LanguageVocabulary.h"

#include <cstddef>
#include <string>

namespace neutrino {
namespace {

VocabCategory categoryFromTag(const char *tag) {
  // .def rows use STATEMENT / FIELD / CONNECTOR; first letter discriminates.
  if (tag[0] == 'S')
    return VocabCategory::Statement;
  if (tag[0] == 'F')
    return VocabCategory::Field;
  return VocabCategory::Connector;
}

const VocabEntry kVocab[] = {
#define NEUTRINO_VOCAB(Category, EnumId, Spelling)                             \
  {VocabId::EnumId, categoryFromTag(#Category), llvm::StringRef(Spelling)},
#include "Neutrino/LanguageVocabulary.def"
#undef NEUTRINO_VOCAB
};

constexpr size_t kVocabCount = sizeof(kVocab) / sizeof(kVocab[0]);

const VocabEntry &entryOf(VocabId id) {
  const size_t i = static_cast<size_t>(id);
  // VocabId enumerators are dense and in .def order, matching kVocab.
  return kVocab[i < kVocabCount ? i : 0];
}

} // namespace

llvm::ArrayRef<VocabEntry> languageVocabulary() {
  return llvm::ArrayRef<VocabEntry>(kVocab, kVocabCount);
}

llvm::StringRef vocabSpelling(VocabId id) { return entryOf(id).spelling; }

VocabCategory vocabCategory(VocabId id) { return entryOf(id).category; }

bool lineStartsWithKeyword(llvm::StringRef line, VocabId id) {
  llvm::StringRef unused;
  return matchKeywordPrefix(line, id, unused);
}

bool matchKeywordPrefix(llvm::StringRef line, VocabId id,
                        llvm::StringRef &rest) {
  llvm::StringRef kw = vocabSpelling(id);
  if (!line.consume_front(kw) || line.empty() || line.front() != ' ')
    return false;
  rest = line.drop_front(); // skip the separating space
  return true;
}

bool tokenIsKeyword(llvm::StringRef token, VocabId id) {
  return token == vocabSpelling(id);
}

bool consumeVocabKeyword(llvm::StringRef &s, VocabId id) {
  // Whole-word consume: same contract as ParseUtil::consumeKeyword, inlined so
  // the dialect library does not depend on the frontend ParseUtil object.
  llvm::StringRef kw = vocabSpelling(id);
  s = s.ltrim();
  if (!s.consume_front(kw))
    return false;
  return s.empty() || s.front() == ' ' || s.front() == '\t' || s.front() == '"';
}

bool lineContainsKeywordWord(llvm::StringRef line, VocabId id) {
  // Match " kw " (spaces both sides) so a connector like `as` is found only as
  // a whole word, matching the prior `b.find(" as ")` recognition.
  std::string needle;
  needle.reserve(vocabSpelling(id).size() + 2);
  needle.push_back(' ');
  needle.append(vocabSpelling(id).data(), vocabSpelling(id).size());
  needle.push_back(' ');
  return line.find(needle) != llvm::StringRef::npos;
}

} // namespace neutrino
