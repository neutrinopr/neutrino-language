//===- SolidityCallableCoverage.inc - enum<->.td coverage asserts --------===//
//
// The compile-time coverage contract () over the GENERATED CallableKind /
// CallableModifier enums. Both enums are generated from the SAME `.td` X-macro
// (SolidityTargetEnums.inc) that drives the spelling tables, so the member set
// IS the position-indexed `.td` list. These assertions make that structural:
//
//  * POSITION probe — a second enum built from the same X-macro with pure
//    auto-increment (each member = its declaration position). Comparing the real
//    enum's ordinal to its position catches an ALIAS (a member reusing an
//    earlier ordinal) or a REORDER — the drift the terminal sentinel alone
//    cannot see (a max-ordinal+1 sentinel does not count enumerators). Because
//    the X-macro enumerates whatever members the generated source carries, a
//    hand-added alias line is itself asserted.
//  * COUNT — the `Count` sentinel == the generated spelling-table length, so an
//    appended member with no spelling is caught too.
//
// Requires (include order): SolidityTargetAdapter.h (the enums) then
// SolidityPrinterHandlers.inc (the generated_printer spelling counts). The
// callable-enum-alias compile-NEGATIVE probe injects an alias into a copy of the
// generated X-macro and proves the POSITION assert below fails to compile.
//
//===----------------------------------------------------------------------===//

namespace enum_coverage {
// Position probes: each member = its DECLARATION POSITION (auto-increment), from
// the same generated X-macro as the real enums.
enum class CallableKindPos {
#define NEU_SOL_ENUM_CallableKind(Sym, Ordinal, Spelling) Sym,
#include "SolidityTargetEnums.inc"
#undef NEU_SOL_ENUM_CallableKind
};
enum class CallableModifierPos {
#define NEU_SOL_ENUM_CallableModifier(Sym, Ordinal, Spelling) Sym,
#include "SolidityTargetEnums.inc"
#undef NEU_SOL_ENUM_CallableModifier
};
} // namespace enum_coverage

// Per-member: the `.td`-declared ordinal must equal the declaration position. An
// alias (ordinal != position) or reorder fails to compile — for EVERY member the
// generated source carries, including a hand-injected one.
#define NEU_SOL_ENUM_CallableKind(Sym, Ordinal, Spelling)                      \
  static_assert(static_cast<int>(CallableKind::Sym) ==                         \
                    static_cast<int>(enum_coverage::CallableKindPos::Sym),     \
                "CallableKind::" #Sym                                          \
                " ordinal drifted from its declaration position "             \
                "(an alias or reorder)");
#include "SolidityTargetEnums.inc"
#undef NEU_SOL_ENUM_CallableKind

#define NEU_SOL_ENUM_CallableModifier(Sym, Ordinal, Spelling)                  \
  static_assert(                                                               \
      static_cast<int>(CallableModifier::Sym) ==                              \
          static_cast<int>(enum_coverage::CallableModifierPos::Sym),           \
      "CallableModifier::" #Sym                                                \
      " ordinal drifted from its declaration position (an alias or reorder)");
#include "SolidityTargetEnums.inc"
#undef NEU_SOL_ENUM_CallableModifier

// COUNT: the terminal sentinel == the generated spelling-table length. An
// appended member with no matching `.td` spelling makes `Count` grow past the
// table and fails here.
static_assert(static_cast<int>(CallableKind::Count) ==
                  generated_printer::kCallableKindSpellingCount,
              "CallableKind member count vs .td spelling table length mismatch");
static_assert(static_cast<int>(CallableModifier::Count) ==
                  generated_printer::kCallableModifierSpellingCount,
              "CallableModifier member count vs .td spelling table length "
              "mismatch");
