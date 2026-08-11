//===- neutrino-emit - emit text artifacts from Neutrino MLIR -------------===//
//
//   neutrino-emit --kind=events|symbols <input.mlir|input.neu> [-o out]
//
// INSPECTION only. `events` is the IR's expected fact ordering; `symbols` is
// the front-end document outline (editor tooling). These are NOT backend
// artifacts — the backends are `neutrino-gen --target=postgres|solidity`. The
// old raw-MLIR `sql` / `contract` projections were retired in .
//
//===----------------------------------------------------------------------===//

#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/CoordinationPlanBuild.h"
#include "Neutrino/Emit.h"
#include "Neutrino/GenDomainSemantics.h"
#include "Neutrino/L2Dialect.h"
#include "Neutrino/L2Imports.h"
#include "Neutrino/L2Reduction.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/SourceLoad.h"
#include "Neutrino/VersionInfo.h"
#include "Neutrino/View.h"

#include "mlir/IR/MLIRContext.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

static cl::opt<std::string>
    inputFile(cl::Positional, cl::desc("<input .mlir|.neu>"), cl::Required);
static cl::opt<std::string>
    kind("kind",
         cl::desc("events | symbols (inspection) | domain-semantics (L2 "
                  "sidecar) | domain-reduction (canonical L2->L1 reduction) | "
                  "domain-imports (versioned import resolution)"),
         cl::Required);
static cl::opt<std::string>
    outputFile("o", cl::desc("output (default: stdout)"), cl::init("-"));
static cl::opt<std::string> reduceAgainst(
    "reduce-against",
    cl::desc("capability-spec.json: verify the L2->L1 reduction binds this "
             "domain's l1_features to the coordination plan "
             "(--kind=domain-semantics)"),
    cl::init(""));
static cl::opt<std::string> registry(
    "registry",
    cl::desc("cross-rail catalog .json: resolve the domain's l2.import records "
             "against this versioned domain registry (--kind=domain-imports)"),
    cl::init(""));
static cl::opt<std::string> registryRoot(
    "registry-root",
    cl::desc("repository root the registry's repo-root-relative l2v2 sidecar "
             "paths resolve against (default: the current directory)"),
    cl::init("."));

// Build a CoordinationPlan from a coordination plan source: a capability-spec
// .json (the leaf planFromSpec) OR a .neu/.mlir source (the DIRECT
// normalizePlan path — parse, select the procedure, view, normalize).
// Exercising BOTH paths is what the reduction parity proof rests on: they yield
// byte-identical coordination plans, so the canonical reduction over either is
// identical.
static llvm::Expected<neutrino::CoordinationPlan>
buildCoordinationPlan(llvm::StringRef path, mlir::MLIRContext &ctx) {
  if (path.endswith(".json")) {
    auto buf = llvm::MemoryBuffer::getFile(path);
    if (!buf)
      return llvm::createStringError(llvm::inconvertibleErrorCode(),
                                     "cannot read coordination plan spec " +
                                         path.str());
    llvm::Expected<llvm::json::Value> j =
        llvm::json::parse((*buf)->getBuffer());
    if (!j)
      return j.takeError();
    if (!j->getAsObject())
      return llvm::createStringError(
          llvm::inconvertibleErrorCode(),
          "coordination plan spec is not a JSON object");
    return neutrino::planFromSpec(*j->getAsObject());
  }
  neutrino::LoadResult lr = neutrino::loadModule(path, ctx);
  if (lr.status != neutrino::LoadStatus::Ok)
    return llvm::createStringError(llvm::inconvertibleErrorCode(),
                                   "cannot load coordination plan source " +
                                       path.str());
  neutrino::ProcedureOp proc = neutrino::defaultProcedure(*lr.module);
  if (!proc)
    return llvm::createStringError(llvm::inconvertibleErrorCode(),
                                   "no procedure in coordination plan source " +
                                       path.str());
  return neutrino::normalizePlan(neutrino::viewOf(proc));
}

int main(int argc, char **argv) {
  InitLLVM z(argc, argv);
  if (neutrino::handleVersionFlag(argc, argv, "neutrino-emit"))
    return 0;
  cl::ParseCommandLineOptions(argc, argv, "neutrino-emit\n");

  // --reduce-against only applies to the L2 domain-semantics / domain-reduction
  // kinds; reject it on the inspection kinds so a caller never gets success
  // without the requested reduction gate running.
  if (!reduceAgainst.empty() && kind != "domain-semantics" &&
      kind != "domain-reduction") {
    errs() << "error: --reduce-against applies only to "
              "--kind=domain-semantics|domain-reduction\n";
    return 2;
  }
  // --registry resolves l2.import records; it applies to domain-imports (the
  // dedicated resolution kind) and to domain-reduction (which GATES on import
  // resolution before reducing an importing domain). Reject it elsewhere.
  if (!registry.empty() && kind != "domain-imports" &&
      kind != "domain-reduction") {
    errs() << "error: --registry applies only to "
              "--kind=domain-imports|domain-reduction\n";
    return 2;
  }

  mlir::MLIRContext ctx;
  ctx.getOrLoadDialect<neutrino::NeutrinoDialect>();
  ctx.getOrLoadDialect<neutrino::l2::L2Dialect>();

  auto writeOut = [&](const std::string &out) -> int {
    if (outputFile == "-") {
      outs() << out;
      return 0;
    }
    std::error_code ec;
    raw_fd_ostream os(outputFile, ec);
    if (ec) {
      errs() << "error: " << ec.message() << "\n";
      return 2;
    }
    os << out;
    return 0;
  };

  // The reduction trust-seam gate (): a domain that declares l2.import
  // records may NOT reduce until those imports resolve against a registry, so a
  // dangling/unknown/ambiguous/cyclic import cannot ride through reduction
  // silently. Returns true to proceed; on failure prints the error and sets rc.
  auto gateImports = [&](StringRef domainId, StringRef version,
                         ArrayRef<neutrino::ResolvedImport> imports,
                         int &rc) -> bool {
    if (imports.empty())
      return true;
    if (registry.empty()) {
      errs() << "error: this domain declares l2.import records; --registry "
                "<cross-rail-catalog.json> is required to resolve them before "
                "reduction\n";
      rc = 2;
      return false;
    }
    auto rbuf = MemoryBuffer::getFile(registry);
    if (!rbuf) {
      errs() << "error: cannot read registry " << registry << "\n";
      rc = 2;
      return false;
    }
    Expected<json::Value> rj = json::parse((*rbuf)->getBuffer());
    if (!rj) {
      errs() << "error: " << toString(rj.takeError()) << "\n";
      rc = 2;
      return false;
    }
    if (!rj->getAsObject()) {
      errs() << "error: registry is not a JSON object\n";
      rc = 2;
      return false;
    }
    Expected<neutrino::DomainImports> resolved = neutrino::resolveDomainImports(
        domainId, version, imports, *rj->getAsObject(), registryRoot);
    if (!resolved) {
      errs() << "error: " << toString(resolved.takeError()) << "\n";
      rc = 1;
      return false;
    }
    return true;
  };

  // A domain-reduction can be re-driven from an emitted v2 domain-semantics
  // sidecar (.json) instead of the l2 MLIR — the RE-INGEST parity path. It must
  // yield the byte-identical reduction as the direct IR, so a separately
  // validated artifact is a provably faithful stand-in for the source. The
  // module loader cannot parse a sidecar, so handle it before the load.
  if (kind == "domain-reduction" && StringRef(inputFile).endswith(".json")) {
    if (reduceAgainst.empty()) {
      errs() << "error: --kind=domain-reduction requires --reduce-against "
                "<capability-spec.json | source.neu>\n";
      return 2;
    }
    auto buf = MemoryBuffer::getFile(inputFile);
    if (!buf) {
      errs() << "error: cannot read v2 sidecar " << inputFile << "\n";
      return 2;
    }
    Expected<json::Value> j = json::parse((*buf)->getBuffer());
    if (!j) {
      errs() << "error: " << toString(j.takeError()) << "\n";
      return 2;
    }
    if (!j->getAsObject()) {
      errs() << "error: v2 sidecar is not a JSON object\n";
      return 2;
    }
    const json::Object &sidecar = *j->getAsObject();
    // Validate the sidecar (shape/verifier/hash) FIRST, so its imports are
    // well-formed before the resolution gate reads them.
    if (llvm::Error e = neutrino::validateDomainSemanticsSidecarV2(sidecar)) {
      errs() << "error: " << toString(std::move(e)) << "\n";
      return 1;
    }
    std::vector<neutrino::ResolvedImport> imports;
    if (const json::Array *imps = sidecar.getArray("imports"))
      for (const json::Value &iv : *imps) {
        const json::Object *io = iv.getAsObject();
        imports.push_back({io->getString("capability")->str(),
                           io->getString("version")->str()});
      }
    int rc = 0;
    if (!gateImports(*sidecar.getString("implements"),
                     *sidecar.getString("version"), imports, rc))
      return rc;
    Expected<neutrino::CoordinationPlan> coordinationPlan =
        buildCoordinationPlan(reduceAgainst, ctx);
    if (!coordinationPlan) {
      errs() << "error: " << toString(coordinationPlan.takeError()) << "\n";
      return 1;
    }
    Expected<neutrino::L2Reduction> red =
        neutrino::reduceSidecarToCoordinationPlan(sidecar, *coordinationPlan);
    if (!red) {
      errs() << "error: " << toString(red.takeError()) << "\n";
      return 1;
    }
    return writeOut(neutrino::emitDomainReduction(*red));
  }

  neutrino::LoadResult loaded = neutrino::loadModule(inputFile, ctx);
  switch (loaded.status) {
  case neutrino::LoadStatus::SourceIoError:
    errs() << "error: " << loaded.detail << "\n";
    return 2;
  case neutrino::LoadStatus::IrVerifyError:
    errs() << "error: input IR failed verification\n";
    return 1;
  case neutrino::LoadStatus::SourceParseError:
  case neutrino::LoadStatus::IrParseError:
    return 2;
  case neutrino::LoadStatus::Ok:
    break;
  }
  mlir::OwningOpRef<mlir::ModuleOp> module = std::move(loaded.module);

  std::string out;
  if (kind == "events")
    out = neutrino::emitEvents(*module);
  else if (kind == "symbols")
    out = neutrino::emitSymbols(*module);
  else if (kind == "domain-semantics" || kind == "domain-reduction") {
    // The L2->L1 reduction onto the coordination plan a source induces ().
    // domain-reduction EMITS the canonical, hashed reduction (the parity
    // artifact); domain-semantics with --reduce-against is a VERIFICATION gate
    // that leaves the sidecar byte-identical (the sidecar stays a sibling;
    // §7 — backends never consume it, so the reduction cannot perturb any
    // capability-spec or backend output).
    if (kind == "domain-reduction" || !reduceAgainst.empty()) {
      if (reduceAgainst.empty()) {
        errs() << "error: --kind=domain-reduction requires --reduce-against "
                  "<capability-spec.json | source.neu>\n";
        return 2;
      }
      neutrino::l2::DomainOp domain;
      int nDomains = 0;
      module->walk([&](neutrino::l2::DomainOp d) {
        if (nDomains++ == 0)
          domain = d;
      });
      if (nDomains == 0) {
        errs() << "error: input contains no l2.domain to reduce\n";
        return 1;
      }
      if (nDomains > 1) {
        errs() << "error: input contains more than one l2.domain (exactly one "
                  "required)\n";
        return 1;
      }
      // Trust-seam gate: an importing domain must resolve its imports first.
      std::vector<neutrino::ResolvedImport> imports;
      for (mlir::Operation &op : domain.getBody().front())
        if (auto imp = mlir::dyn_cast<neutrino::l2::ImportOp>(op))
          imports.push_back(
              {imp.getCapability().str(), imp.getVersion().str()});
      int rc = 0;
      if (!gateImports(domain.getImplements(), domain.getVersion(), imports,
                       rc))
        return rc;
      Expected<neutrino::CoordinationPlan> coordinationPlan =
          buildCoordinationPlan(reduceAgainst, ctx);
      if (!coordinationPlan) {
        errs() << "error: " << toString(coordinationPlan.takeError()) << "\n";
        return 1;
      }
      Expected<neutrino::L2Reduction> red =
          neutrino::reduceL2ToCoordinationPlan(domain, *coordinationPlan);
      if (!red) {
        errs() << "error: " << toString(red.takeError()) << "\n";
        return 1;
      }
      if (kind == "domain-reduction")
        out = neutrino::emitDomainReduction(*red);
    }
    if (kind == "domain-semantics") {
      // The visible L2 sidecar: a deterministic, hashed projection of a
      // verified l2.domain. Byte-identical whether or not --reduce-against ran.
      llvm::Expected<std::string> sidecar =
          neutrino::emitDomainSemanticsSidecar(*module);
      if (!sidecar) {
        errs() << "error: " << llvm::toString(sidecar.takeError()) << "\n";
        return 1;
      }
      out = *sidecar;
    }
  } else if (kind == "domain-imports") {
    // Versioned import resolution (): resolve the domain's l2.import
    // records against the cross-rail catalog registry, fail-closed on a
    // dangling, unknown-version, ambiguous, or cyclic mapping.
    if (registry.empty()) {
      errs() << "error: --kind=domain-imports requires --registry "
                "<cross-rail-catalog.json>\n";
      return 2;
    }
    neutrino::l2::DomainOp domain;
    int nDomains = 0;
    module->walk([&](neutrino::l2::DomainOp d) {
      if (nDomains++ == 0)
        domain = d;
    });
    if (nDomains == 0) {
      errs() << "error: input contains no l2.domain to resolve imports for\n";
      return 1;
    }
    if (nDomains > 1) {
      errs() << "error: input contains more than one l2.domain (exactly one "
                "required)\n";
      return 1;
    }
    auto buf = MemoryBuffer::getFile(registry);
    if (!buf) {
      errs() << "error: cannot read registry " << registry << "\n";
      return 2;
    }
    Expected<json::Value> j = json::parse((*buf)->getBuffer());
    if (!j) {
      errs() << "error: " << toString(j.takeError()) << "\n";
      return 2;
    }
    if (!j->getAsObject()) {
      errs() << "error: registry is not a JSON object\n";
      return 2;
    }
    Expected<neutrino::DomainImports> resolved =
        neutrino::resolveDomainImports(domain, *j->getAsObject(), registryRoot);
    if (!resolved) {
      errs() << "error: " << toString(resolved.takeError()) << "\n";
      return 1;
    }
    out = neutrino::emitDomainImports(*resolved);
  } else if (kind == "sql" || kind == "contract") {
    // Retired in : these walked raw MLIR and were presented as backend
    // outputs while NOT consuming the frozen capability-spec (the `sql` path
    // even emitted a correctness-buggy no-upsert UPDATE). Fail closed with a
    // migration pointer rather than a generic unknown-kind error.
    errs()
        << "error: --kind=" << kind
        << " was retired (): neutrino-emit only produces INSPECTION "
           "projections (events|symbols), not backends. Render backends with "
           "the capability-spec path: neutrino-gen "
           "--target=postgres|solidity.\n";
    return 2;
  } else {
    errs()
        << "error: --kind must be "
           "events|symbols|domain-semantics|domain-reduction|domain-imports\n";
    return 2;
  }

  return writeOut(out);
}
