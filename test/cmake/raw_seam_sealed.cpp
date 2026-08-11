//===- raw_seam_sealed.cpp -  SolStmt-encapsulation boundary probes --===//
//
// This TU stands in for "any translation unit outside the governed legalization
// TU". Each PROBE_* selector isolates ONE structural authoring bypass and MUST
// FAIL TO COMPILE. The `solidity-raw-seam-sealed[.N]` CTests compile this file
// once per probe and pass iff that probe's compile fails with its expected
// diagnostic — so if any single path re-opens, exactly that probe starts
// compiling and the suite fails (the probes are independent, not several
// failures in one compile).
//
//  reached zero and the RawCap/rawLine/rawBlock seam was DELETED, so the
// capability-mint probes are gone. What remains — and must stay sealed — is the
// SolStmt encapsulation that makes forging a raw `Line`/`Block` a compile
// error: the private constructor (no aggregate-init, no ctor call from a
// non-friend) and the const fields (no mutation). The scanner gate
// (check_solidity_syntax_authority.py) enforces the same prohibition textually;
// these probes prove the type system holds it structurally at build time.
//
//===----------------------------------------------------------------------===//

#include "SolidityTargetAdapter.h"

using namespace neutrino::solidity_model;

#if defined(PROBE_AGGREGATE)
// Forge a Line by brace/aggregate construction — the SolStmt constructor is
// private, so a `SolStmt{…}` build cannot bypass the typed factories.
SolStmt probe() {
  return SolStmt{SolStmt::Kind::Line, {std::string("selfdestruct();")}, {}};
}

#elif defined(PROBE_MUTATION)
// Mutate a factory-obtained instance — the fields are const.
SolStmt probe() {
  SolStmt s = SolStmt::blank();
  s.kind = SolStmt::Kind::Block;
  return s;
}

#elif defined(PROBE_CTOR_PROBE_COMPLETION)
// The exact former exploit: complete the old test-only friend name in an
// external TU and bypass localDecl's separator validation by invoking the
// private constructor directly. The production friend declaration is deleted,
// so this formerly privileged name has no access and must not compile.
namespace neutrino {
namespace solidity_model {
struct SolStmtCtorProbe {
  static SolStmt go() {
    return SolStmt(SolStmt::Kind::LocalDecl,
                   {std::string("uint256 x; selfdestruct(); //"),
                    std::string("ignored"), std::string("0")},
                   {});
  }
};
} // namespace solidity_model
} // namespace neutrino
SolStmt probe() {
  return neutrino::solidity_model::SolStmtCtorProbe::go();
}

#else
#error "raw_seam_sealed.cpp must be compiled with a -DPROBE_* selector"
#endif
