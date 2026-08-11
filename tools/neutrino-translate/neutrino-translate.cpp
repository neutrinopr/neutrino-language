//===- neutrino-translate - .neu -> Neutrino MLIR (generic form) ------===//

#include "Neutrino/DiagnosticTaxonomy.h"
#include "Neutrino/Frontend.h"
#include "Neutrino/LanguageMetadata.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/SemanticRequirements.h"
#include "Neutrino/VersionInfo.h"

#include "mlir/IR/MLIRContext.h"
#include "mlir/IR/OperationSupport.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

static cl::opt<std::string> inputFile(cl::Positional, cl::desc("<input .neu>"),
                                      cl::Required);
static cl::opt<std::string>
    outputFile("o", cl::desc("output file (default: stdout)"), cl::init("-"));

int main(int argc, char **argv) {
  InitLLVM y(argc, argv);
  if (neutrino::handleVersionFlag(argc, argv, "neutrino-translate"))
    return 0;
  // `--language-metadata` dumps the compiler-owned grammar/language metadata
  // (keywords, value types, operators) as deterministic JSON for the Python
  // tooling to consume (M5 D10). Like
  // --version-json it is a pure query: no input file required, handled before
  // cl parsing.
  if (neutrino::handleLanguageMetadataFlag(argc, argv))
    return 0;
  // `--diagnostic-taxonomy` dumps the shared failure taxonomy (M5 WP1c, ):
  // the stable dotted diagnostic codes, their category/owner, status, and
  // root-cause precedence, as deterministic JSON. Pure query, no input
  // required, handled before cl parsing (like --language-metadata).
  if (neutrino::handleDiagnosticTaxonomyFlag(argc, argv))
    return 0;
  // `--semantic-feature-vocabulary` dumps the closed  semantic-requirement
  // vocabulary (knownSemanticFeatures + the pinned kSemanticProfileVersion) as
  // deterministic JSON — the ONE authoritative artifact the profile validator,
  // bundle generator, and released verifier consume. Pure query, no input,
  // handled before cl parsing (like --diagnostic-taxonomy).
  if (neutrino::handleSemanticVocabularyFlag(argc, argv))
    return 0;
  // `--capability-registry` dumps the closed capability registry (each feature
  // projected with its dimension/value/category, pinned by
  // kSemanticProfileVersion) as deterministic JSON — the ONE authoritative
  // capability contract executable domain reductions anchor against at the
  // intake seam. Pure query, no input, handled before cl parsing (like
  // --semantic-feature-vocabulary).
  if (neutrino::handleCapabilityRegistryFlag(argc, argv))
    return 0;
  cl::ParseCommandLineOptions(argc, argv, "neutrino-translate: .neu -> MLIR\n");

  // `.neu` is the only accepted DSL source extension (STDIN "-" excepted). A
  // legacy `.finproc` — or any other — filename is rejected here rather than
  // silently parsed as DSL, matching isDslSourcePath() routing in the other
  // tools. See docs/process/COMPATIBILITY.md and self-test [34].
  if (inputFile != "-" && !neutrino::isDslSourcePath(inputFile)) {
    errs() << "error: " << inputFile
           << ": not a .neu source file (.neu is the only accepted DSL source "
              "extension)\n";
    return 2;
  }

  auto fileOrErr = MemoryBuffer::getFileOrSTDIN(inputFile);
  if (std::error_code ec = fileOrErr.getError()) {
    errs() << "error: cannot open " << inputFile << ": " << ec.message()
           << "\n";
    return 2;
  }

  mlir::MLIRContext ctx;
  ctx.getOrLoadDialect<neutrino::NeutrinoDialect>();

  auto module =
      neutrino::parseNeutrinoSource((*fileOrErr)->getBuffer(), inputFile, ctx);
  if (!module)
    return 2;

  mlir::OpPrintingFlags flags;
  flags.printGenericOpForm();

  if (outputFile == "-") {
    module->print(outs(), flags);
    outs() << "\n";
  } else {
    std::error_code ec;
    raw_fd_ostream os(outputFile, ec);
    if (ec) {
      errs() << "error: cannot write " << outputFile << ": " << ec.message()
             << "\n";
      return 2;
    }
    module->print(os, flags);
    os << "\n";
  }
  return 0;
}
