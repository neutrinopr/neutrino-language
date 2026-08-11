//===- neutrino-gen - generate backend artifacts from IR + scenario -------===//
//
//   neutrino-gen --target=solidity --scenario=s.json <input.mlir|.neu> -o dir
//
//===----------------------------------------------------------------------===//

#include "Neutrino/AgreementEnvelope.h"
#include "Neutrino/ArtifactPublication.h"
#include "Neutrino/BackendDispatchReceipt.h"
#include "Neutrino/BackendInvoker.h"
#include "Neutrino/BackendProjection.h"
#include "Neutrino/CoordinationPlan.h"
#include "Neutrino/CoordinationPlanBuild.h"
#include "Neutrino/Diagnostics.h"
#include "Neutrino/GenCapabilityModelSpec.h"
#include "Neutrino/GenCoordinationPlan.h"
#include "Neutrino/GenCoordinationTrace.h"
#include "Neutrino/GenSemanticRequirements.h"
#include "Neutrino/GenSpec.h"
#include "Neutrino/Manifest.h"
#include "Neutrino/NeutrinoDialect.h"
#include "Neutrino/PlanLegality.h"
#include "Neutrino/Scenario.h"
#include "Neutrino/SourceLoad.h"
#include "Neutrino/SpecLegality.h"
#include "Neutrino/StrCase.h"
#include "Neutrino/TargetCatalog.h"
#include "Neutrino/Targets.h"
#include "Neutrino/Validate.h"
#include "Neutrino/VersionInfo.h"
#include "Neutrino/View.h"
#ifndef NEUTRINO_CORE_ONLY
#include "Neutrino/GenOracleObserverSpec.h"
#include "Neutrino/GenPostgresSpec.h"
#endif

#include "mlir/IR/MLIRContext.h"
#include "llvm/Support/CommandLine.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/raw_ostream.h"

#include <filesystem>
#include <vector>

using namespace llvm;

static cl::opt<std::string>
    inputFile(cl::Positional, cl::desc("<input .mlir|.neu>"), cl::Required);
static cl::opt<std::string>
    target("target", cl::desc("generation target (see --list-targets)"),
           cl::Required);
static cl::opt<std::string> scenarioFile(
    "scenario",
    cl::desc("scenario JSON (required except --target=capability-spec)"),
    cl::init(""));
static cl::opt<std::string> outDir("o", cl::desc("output directory"),
                                   cl::init("build/gen"));
static cl::opt<bool> allowInsecure(
    "allow-insecure",
    cl::desc(
        "override the security gate for an internal bundled renderer; never "
        "authorizes external-package dispatch"),
    cl::init(false));
static cl::opt<std::string>
    profileFile("profile",
                cl::desc("target-profile JSON; when given, the spec-legality "
                         "gate (WP4/) runs "
                         "before a gated render and fails closed on an "
                         "unsupported required feature"),
                cl::init(""));
static cl::opt<bool>
    fromSpec("from-spec",
             cl::desc("treat the positional input as a canonical "
                      "capability-spec.json and render the spec-derived "
                      "artifact from it directly (no source/scenario); "
                      "verified external packages and selected built-ins only"),
             cl::init(false));
static cl::opt<std::string>
    bindingFile("binding",
                cl::desc("observation-binding JSON (required for "
                         "--target=oracle-observer, S4/): resolves each "
                         "attestation observer-set to a concrete source + N "
                         "observer members"),
                cl::init(""));
static cl::list<std::string> backendPackageDirectories(
    "backend-package-dir",
    cl::desc("verified external backend package directory (repeatable)"),
    cl::ZeroOrMore);
static cl::opt<std::string> expectedCoreIdentity("expected-core-identity",
                                                 cl::Hidden, cl::init(""));
static cl::opt<std::string> expectedCatalogIdentity("expected-catalog-identity",
                                                    cl::Hidden, cl::init(""));
// TEST-ONLY governed fault seam (hidden): forces the backend projection step of
// --target=coordination-plan to fail, so a test can witness that the projection
// is validated BEFORE any artifact is written — a projection failure leaves no
// partial coordination-plan.json / backend-projection.json behind ().
static cl::opt<bool> projectionFaultSelftest("projection-fault-selftest",
                                             cl::Hidden, cl::init(false));

// Hidden self-test seam (): forces the coordination-plan SERIALIZATION to
// fail, so a test can witness that the coordination-plan target serializes via
// CHECKED `Expected` propagation (never `cantFail`) on BOTH the from-source and
// --from-spec paths. The failure is injected INTO the `Expected` the serializer
// returns (see `coordinationPlanTextChecked`), so the ordinary `if (!E)
// takeError()` path produces the clean diagnostic — a `cantFail` unwrap would
// instead abort on the injected error.
static cl::opt<bool>
    coordinationPlanFaultSelftest("coordination-plan-fault-selftest",
                                  cl::Hidden, cl::init(false));

// : serialize the coordination-plan text with checked `Expected`
// propagation, SHARED by the from-source and --from-spec paths so they cannot
// drift. The hidden fault seam folds the failure into the returned `Expected`
// itself — it does NOT short-circuit before the serializer — so the caller's
// ordinary `if (!planTextE) return fail(...takeError())` is exercised on both
// paths. Replacing that checked unwrap with `cantFail(...)` would abort here on
// the injected error instead of failing closed with EXIT_IR, which
// plan_target_error_seam.test detects (it asserts the exact exit code + no
// partial artifact).
static Expected<std::string> coordinationPlanTextChecked(
    const neutrino::CoordinationPlan &coordinationPlan) {
  if (coordinationPlanFaultSelftest)
    return createStringError(
        inconvertibleErrorCode(),
        "diag:test:forced-coordination-plan-serialization-failure");
  return neutrino::coordinationPlanToText(coordinationPlan);
}

// Stable exit codes (documented in README).
enum ExitCode {
  EXIT_OK = 0,
  EXIT_USAGE = 2,    // bad arguments / IO / parse error
  EXIT_SCENARIO = 3, // scenario invalid for the procedure
  EXIT_IR = 4,       // IR failed verification
  EXIT_SECURITY =
      5, // Capability Security Pass found hard violations (target=security)
  EXIT_LEGALITY = 6, // spec illegal for the target profile (gate before render)
};

static bool conflictsWithCoreBundleMetadata(StringRef path) {
  constexpr StringLiteral reserved[] = {
      "manifest.json", "diagnostics.json",
      neutrino::backend_dispatch_receipt::kFileName};
  for (StringRef name : reserved)
    if (path == name || path.startswith((name + "/").str()))
      return true;
  return false;
}

int main(int argc, char **argv) {
  InitLLVM w(argc, argv);
  if (neutrino::handleVersionFlag(argc, argv, "neutrino-gen"))
    return 0;
  Expected<std::vector<std::string>> packageDirectories =
      neutrino::resolveBackendPackageDirectories(argc, argv);
  if (!packageDirectories) {
    errs() << "error: " << toString(packageDirectories.takeError()) << "\n";
    return EXIT_USAGE;
  }
  Expected<neutrino::TargetCatalog> catalogE =
      neutrino::loadTargetCatalog(*packageDirectories);
  if (!catalogE) {
    errs() << "error: cannot load target catalog: "
           << toString(catalogE.takeError()) << "\n";
    return EXIT_USAGE;
  }
  neutrino::TargetCatalog catalog = std::move(*catalogE);

  // Introspection consumes the same catalog as target selection. Handled before
  // ParseCommandLineOptions (like --version) so otherwise-required arguments
  // are not needed.
  for (int i = 1; i < argc; ++i) {
    if (std::string(argv[i]) == "--list-targets") {
      for (const neutrino::CatalogTarget &t : catalog.targets())
        outs() << t.name << "\n";
      return EXIT_OK;
    }
    // Emits the independently materialized closure consumed by capability
    // claim verification. This is produced directly from the already verified
    // typed catalog, not copied from a capability output directory.
    if (std::string(argv[i]) == "--verified-target-profile-catalog") {
      Expected<std::string> bytes = neutrino::capabilityModelCatalogBytes(
          catalog.identity(), catalog.profiles());
      if (!bytes) {
        errs() << "error: " << toString(bytes.takeError()) << "\n";
        return EXIT_USAGE;
      }
      outs() << *bytes;
      return EXIT_OK;
    }
    // --dump-semantic-profile=<target> prints the catalog target's
    // authoritative semanticProfile block.
    std::string arg(argv[i]);
    const std::string dumpFlag = "--dump-semantic-profile=";
    if (arg.rfind(dumpFlag, 0) == 0) {
      StringRef requested = StringRef(arg).drop_front(dumpFlag.size());
      const neutrino::CatalogTarget *entry = catalog.find(requested);
      if (!entry) {
        errs() << "error: unknown target '" << requested
               << "'; available targets are " << catalog.usageList() << "\n";
        return EXIT_USAGE;
      }
      if (entry->externalPackage) {
        Expected<json::Value> summary =
            json::parse(entry->canonicalProfileSummary);
        const json::Object *object = summary ? summary->getAsObject() : nullptr;
        const json::Object *semantic =
            object ? object->getObject("semanticProfile") : nullptr;
        if (!semantic) {
          errs() << "error: external target '" << requested
                 << "' has an invalid verified profile summary\n";
          return EXIT_USAGE;
        }
        outs() << formatv("{0:2}", json::Value(json::Object(*semantic)))
               << "\n";
        return EXIT_OK;
      }
      neutrino::SemanticProfile sp =
          neutrino::builtinSemanticProfile(requested);
      outs() << formatv("{0:2}", neutrino::semanticProfileToJson(sp)) << "\n";
      return EXIT_OK;
    }
    // --target-profiles prints every catalog target with a realization profile.
    if (arg == "--target-profiles") {
      json::Array arr;
      for (const neutrino::CatalogTarget &entry : catalog.targets()) {
        if (!entry.hasTargetProfile)
          continue;
        if (entry.externalPackage) {
          arr.push_back(
              json::Object{{"target", entry.name},
                           {"id", entry.targetProfileIdentity},
                           {"version", entry.semanticProfileVersion}});
          continue;
        }
        neutrino::SemanticProfile p =
            neutrino::builtinSemanticProfile(entry.name);
        arr.push_back(json::Object{
            {"target", entry.name}, {"id", p.id}, {"version", p.version}});
      }
      outs() << formatv("{0:2}", json::Value(std::move(arr))) << "\n";
      return EXIT_OK;
    }
  }
  cl::ParseCommandLineOptions(argc, argv,
                              "neutrino-gen: backend artifact generator\n");

  if (expectedCoreIdentity.empty() != expectedCatalogIdentity.empty()) {
    errs() << "error: E_CHILD_IDENTITY: expected core and catalog identities "
              "must be supplied together\n";
    return EXIT_USAGE;
  }
  if (!expectedCoreIdentity.empty()) {
    const std::string actualCoreIdentity =
        neutrino::backend_invocation::coreIdentity();
    const std::string actualCatalogIdentity = catalog.identity();
    if (expectedCoreIdentity != actualCoreIdentity) {
      errs() << "error: E_CHILD_CORE_IDENTITY: expected "
             << expectedCoreIdentity << ", discovered " << actualCoreIdentity
             << "\n";
      return EXIT_USAGE;
    }
    if (expectedCatalogIdentity != actualCatalogIdentity) {
      errs() << "error: E_CHILD_CATALOG_IDENTITY: expected "
             << expectedCatalogIdentity << ", discovered "
             << actualCatalogIdentity << "\n";
      return EXIT_USAGE;
    }
  }

  std::string commandLine;
  for (int i = 0; i < argc; ++i)
    commandLine += (i ? " " : "") + std::string(argv[i]);

  // diagnostics.json is written into the output dir on every path (success or
  // failure), so an agent/CI can read structured results without scraping
  // stderr.
  std::string outStr = outDir;
  std::filesystem::create_directories(outStr);
  std::string diagPath =
      (std::filesystem::path(outStr) / "diagnostics.json").string();
  std::vector<neutrino::Diagnostic> diags;

  // Every run writes BOTH manifest.json and diagnostics.json (success or
  // failure), so an agent always gets the same bundle shape.
  auto writeBundle = [&](bool ok, const std::vector<std::string> &artifacts) {
    neutrino::writeManifest(outStr, target, inputFile, scenarioFile, artifacts,
                            commandLine, ok);
    // Root-cause first (): the primary failure leads, cascades follow.
    neutrino::orderByRootCause(diags);
    neutrino::writeDiagnostics(diagPath, ok, diags);
  };

  auto fail = [&](const std::string &code, const std::string &msg,
                  int exitCode) -> int {
    errs() << "error: " << msg << "\n";
    diags.push_back({"error", code, msg});
    writeBundle(/*ok=*/false, {});
    return exitCode;
  };

  auto codeFrom = [](const std::string &msg,
                     const char *fallback) -> std::string {
    size_t l = msg.find('[');
    size_t r = msg.find(']', l);
    if (l != std::string::npos && r != std::string::npos && r > l + 1)
      return msg.substr(l + 1, r - l - 1);
    return fallback;
  };

  const neutrino::CatalogTarget *targetEntry = catalog.find(target);
  const neutrino::TargetSpec *targetSpec =
      targetEntry ? targetEntry->builtin : nullptr;
  if (!targetEntry) {
#ifndef NEUTRINO_CORE_ONLY
    // oracle-observer (S4/) is not a view-routable registry target: it
    // renders from the FROZEN capability-spec's attestation policy + an
    // observation binding, so it is valid ONLY as `--from-spec --binding`
    // (handled below).
    if (target == "oracle-observer") {
      if (!fromSpec)
        return fail(
            "usage.target",
            "--target=oracle-observer requires --from-spec "
            "<capability-spec.json> --binding <observation-binding.json>",
            EXIT_USAGE);
      // fall through: the --from-spec block renders it and returns.
    } else {
#endif
      std::string targetUsage = catalog.usageList();
#ifndef NEUTRINO_CORE_ONLY
      targetUsage += " | oracle-observer (--from-spec only)";
#endif
      return fail("usage.target", "--target must be " + targetUsage,
                  EXIT_USAGE);
#ifndef NEUTRINO_CORE_ONLY
    }
#endif
  }

  if (targetEntry && targetEntry->externalPackage && !profileFile.empty())
    return fail("legality.profile_override",
                "external target '" + target +
                    "' is bound to its verified package profile; --profile "
                    "cannot override it",
                EXIT_LEGALITY);

  // Spec-legality gate (wired at the renderer entry):
  // before a gated render, match the spec's targetRequirements against the
  // target profile and FAIL CLOSED on an unsupported required feature — so a
  // deployable artifact is never emitted for a capability the target profile
  // cannot legally realize. In-process (the C++ twin of
  // check_spec_legality.py); skipped when no --profile is supplied. Returns -1
  // to continue, or an exit code (bundle already written) to return from main.
  auto gateLegality = [&](const llvm::json::Object &specObj) -> int {
    if (profileFile.empty())
      return -1;
    ErrorOr<std::unique_ptr<MemoryBuffer>> profBuf =
        MemoryBuffer::getFile(profileFile);
    if (!profBuf)
      return fail("legality.io",
                  "cannot read target profile " + profileFile + ": " +
                      profBuf.getError().message(),
                  EXIT_USAGE);
    Expected<json::Value> profVal = json::parse((*profBuf)->getBuffer());
    if (!profVal)
      return fail("legality.io",
                  "target profile " + profileFile +
                      " is not valid JSON: " + toString(profVal.takeError()),
                  EXIT_USAGE);
    const json::Object *profObj = profVal->getAsObject();
    if (!profObj)
      return fail("legality.bad_input", "target profile must be a JSON object",
                  EXIT_LEGALITY);
    std::vector<neutrino::Diagnostic> legal =
        neutrino::checkSpecLegality(specObj, *profObj, target);
    if (!neutrino::specIsLegal(legal)) {
      for (const neutrino::Diagnostic &d : legal)
        errs() << (d.severity == "error" ? "error: " : "warning: ") << d.message
               << "\n";
      diags.insert(diags.end(), legal.begin(), legal.end());
      writeBundle(/*ok=*/false, {});
      return EXIT_LEGALITY;
    }
    diags.insert(diags.end(), legal.begin(),
                 legal.end()); // advisories: legal, still recorded
    return -1;
  };

  // Semantic realization-legality gate (): match a VERIFIED
  // CoordinationPlan's normalized semantic requirements + metrics against the
  // target's SemanticProfile BEFORE evaluator/lowering dispatch. One
  // requirement derivation, one matcher, multiple profile sources: the
  // reference evaluator (coordination-trace) matches the BUILT-IN reference
  // profile; an external lowering matches its descriptor-bound profile and a
  // retained in-process lowering matches its built-in default unless --profile
  // supplies an override. Every coordination-plan-realizing target gates before
  // render; no-profile render is not unbounded.
  // Returns -1 to continue, or an exit code (bundle written) to return from
  // main.
  auto realizesCoordinationPlan = [&]() {
    if (targetEntry && targetEntry->externalPackage)
      return true;
    if (target == "coordination-trace")
      return true;
#ifndef NEUTRINO_CORE_ONLY
    return target == "postgres";
#else
    return false;
#endif
  };
  auto gatePlanLegality =
      [&](const neutrino::CoordinationPlan &coordinationPlan) -> int {
    if (!realizesCoordinationPlan())
      return -1;
    // MANDATORY: the gate ALWAYS runs for a coordination-plan-realizing target.
    // A rigid lowering matches its BUILT-IN default profile unless an explicit
    // --profile overrides it (custom/tamper); a no-profile render never means
    // "unbounded". The evaluator (coordination-trace) always uses its intrinsic
    // profile.
    neutrino::SemanticProfile sprofile;
    if (target == "coordination-trace") {
      sprofile = neutrino::builtinSemanticProfile(target);
    } else if (profileFile.empty() && targetEntry &&
               targetEntry->externalPackage) {
      Expected<json::Value> summary =
          json::parse(targetEntry->canonicalProfileSummary);
      const json::Object *summaryObject =
          summary ? summary->getAsObject() : nullptr;
      const json::Object *semanticObject =
          summaryObject ? summaryObject->getObject("semanticProfile") : nullptr;
      if (!semanticObject)
        return fail("legality.bad_input",
                    "external target '" + target +
                        "' has an invalid verified semantic profile",
                    EXIT_LEGALITY);
      sprofile = neutrino::semanticProfileFromJson(*summaryObject);
    } else if (profileFile.empty()) {
      sprofile = neutrino::builtinSemanticProfile(target);
    } else {
      ErrorOr<std::unique_ptr<MemoryBuffer>> pb =
          MemoryBuffer::getFile(profileFile);
      if (!pb)
        return fail("legality.io",
                    "cannot read target profile " + profileFile + ": " +
                        pb.getError().message(),
                    EXIT_USAGE);
      Expected<json::Value> pv = json::parse((*pb)->getBuffer());
      if (!pv || !pv->getAsObject())
        return fail("legality.bad_input",
                    "target profile " + profileFile + " is not a JSON object",
                    EXIT_LEGALITY);
      sprofile = neutrino::semanticProfileFromJson(*pv->getAsObject());
    }
    std::vector<neutrino::Diagnostic> pdiags =
        neutrino::checkPlanLegality(coordinationPlan, sprofile);
    if (!neutrino::planIsLegal(pdiags)) {
      for (const neutrino::Diagnostic &d : pdiags) {
        errs() << "error: " << d.message << "\n";
        diags.push_back(d);
      }
      writeBundle(/*ok=*/false, {});
      return EXIT_LEGALITY;
    }
    diags.insert(diags.end(), pdiags.begin(), pdiags.end());
    return -1;
  };

  auto dispatchExternal =
      [&](const neutrino::CoordinationPlan &coordinationPlan) -> int {
    Expected<neutrino::projection::BackendProjectionGraph> graph =
        neutrino::projection::projectBackendGraph(coordinationPlan);
    if (!graph)
      return fail("spec.ast", toString(graph.takeError()), EXIT_IR);

    neutrino::backend_invocation::InvocationOptions options;
    options.requestId = 1;
    options.coreIdentity = neutrino::backend_invocation::coreIdentity();
    options.outputSpec.maxArtifacts = 1024;
    options.outputSpec.maxTotalBytes = 256u * 1024u * 1024u;
    options.outputSpec.pathPrefix = "";
    Expected<neutrino::backend_invocation::Result> invoked =
        neutrino::backend_invocation::invoke(catalog.packageFor(*targetEntry),
                                             *graph, options);
    if (!invoked)
      return fail("backend.invoke", toString(invoked.takeError()), EXIT_IR);
    Expected<std::string> receipt =
        neutrino::backend_dispatch_receipt::createApproved(*invoked);
    if (!receipt)
      return fail("backend.receipt", toString(receipt.takeError()), EXIT_IR);
    for (const neutrino::backend_invocation::Artifact &artifact :
         invoked->artifacts) {
      if (conflictsWithCoreBundleMetadata(artifact.path))
        return fail("artifact.reserved_path",
                    "external target '" + target +
                        "' returned reserved "
                        "core bundle path '" +
                        artifact.path + "'",
                    EXIT_IR);
    }
    std::vector<std::string> written;
    written.reserve(invoked->artifacts.size() + 1);
    // Reserve and publish the mandatory audit record before making any backend
    // artifact visible. A pre-existing or unsafe receipt destination therefore
    // fails with zero unaudited backend output.
    Expected<neutrino::artifact_publication::PublishedArtifact>
        publishedReceipt = neutrino::artifact_publication::publishCoreArtifact(
            neutrino::backend_dispatch_receipt::kFileName, *receipt, outStr);
    if (!publishedReceipt)
      return fail("artifact.publish", toString(publishedReceipt.takeError()),
                  EXIT_USAGE);
    std::string receiptPath =
        (std::filesystem::path(outStr) /
         neutrino::backend_dispatch_receipt::kFileName.str())
            .string();
    errs() << "wrote " << receiptPath << "\n";
    written.push_back(receiptPath);

    Expected<neutrino::artifact_publication::Result> published =
        neutrino::artifact_publication::publish(*invoked, outStr);
    if (!published)
      return fail("artifact.publish", toString(published.takeError()),
                  EXIT_USAGE);
    for (const auto &artifact : published->artifacts) {
      std::string path =
          (std::filesystem::path(outStr) / artifact.path).string();
      errs() << "wrote " << path << "\n";
      written.push_back(std::move(path));
    }
    writeBundle(/*ok=*/true, written);
    errs() << "wrote " << outStr << "/manifest.json\n";
    errs() << "wrote " << diagPath << "\n";
    return EXIT_OK;
  };

  // --from-spec: render the spec-derived artifact straight from a canonical
  // capability-spec.json, with no source or scenario. Treats the
  // spec as the ingestible external contract it is
  // (): external packages receive the same finalized projection as the
  // source path, while retained built-ins use their checked reconstruction
  // path. Harnesses that require scenario realization are out of this mode.
  if (fromSpec) {
    if (!(targetEntry && targetEntry->externalPackage) &&
#ifndef NEUTRINO_CORE_ONLY
        target != "postgres" && target != "oracle-observer" &&
#endif
        target != "coordination-plan" && target != "semantic-requirements" &&
        target != "coordination-trace" && target != "agreement-identity")
      return fail(
          "usage.target",
          "--from-spec supports "
#ifndef NEUTRINO_CORE_ONLY
          "postgres | oracle-observer | "
#endif
          "coordination-plan | semantic-requirements | coordination-trace "
          "| agreement-identity"
          " only",
          EXIT_USAGE);
    ErrorOr<std::unique_ptr<MemoryBuffer>> specBuf =
        MemoryBuffer::getFile(inputFile);
    if (!specBuf)
      return fail("source.io",
                  "cannot read capability-spec " + inputFile + ": " +
                      specBuf.getError().message(),
                  EXIT_USAGE);
    Expected<json::Value> specVal = json::parse((*specBuf)->getBuffer());
    if (!specVal)
      return fail("spec.schema",
                  "capability-spec " + inputFile +
                      " is not valid JSON: " + toString(specVal.takeError()),
                  EXIT_USAGE);
    const json::Object *specObj = specVal->getAsObject();
    if (!specObj)
      return fail("spec.schema",
                  "capability-spec " + inputFile + " is not a JSON object",
                  EXIT_USAGE);
    // agreement-identity (): recompute the portable identity from the
    // external capability-spec. Non-gated (the identity of the
    // subject-of-analysis, like the capability-spec itself) so it runs BEFORE
    // the legality gate; fails closed on a tampered spec (a capabilityHash that
    // does not recompute). Verified byte-identical to the from-MLIR target.
    if (target == "agreement-identity") {
      Expected<std::string> artifact =
          neutrino::agreementIdentityFromSpec(*specObj);
      if (!artifact)
        return fail("spec.schema", toString(artifact.takeError()), EXIT_IR);
      std::string path =
          (std::filesystem::path(outStr) / "agreement-identity.json").string();
      std::error_code ec;
      raw_fd_ostream os(path, ec);
      if (ec)
        return fail("internal", "cannot write " + path + ": " + ec.message(),
                    EXIT_USAGE);
      os << *artifact;
      os.close();
      errs() << "wrote " << path << "\n";
      writeBundle(/*ok=*/true, {path});
      return EXIT_OK;
    }
    int rc = gateLegality(*specObj);
    if (rc >= 0)
      return rc;
    // coordination-plan (): reconstruct the coordinationPlan from the
    // external spec and serialize it — the external-spec reconstruction path,
    // verified to yield the same artifact as normalizePlan on the source's
    // MLIR.
    if (target == "coordination-plan") {
      Expected<neutrino::CoordinationPlan> coordinationPlanE =
          neutrino::planFromSpec(*specObj);
      if (!coordinationPlanE) {
        std::string msg = toString(coordinationPlanE.takeError());
        return fail(codeFrom(msg, "spec.ast"), msg, EXIT_IR);
      }
      // Checked Expected propagation (never cantFail): the fault seam is folded
      // into the returned Expected, so this ordinary takeError() path produces
      // the diagnostic. ()
      Expected<std::string> planTextE =
          coordinationPlanTextChecked(*coordinationPlanE);
      if (!planTextE)
        return fail("spec.ast", toString(planTextE.takeError()), EXIT_IR);
      // Validate the complete backend projection graph from the same
      // reconstructed `CoordinationPlan` before any file is written, so an
      // invalid projection leaves no partial artifact and the waist round-trip
      // remains byte-identical to the from-source path.
      if (projectionFaultSelftest)
        return fail("spec.ast", "diag:test:forced-projection-failure", EXIT_IR);
      Expected<std::string> projTextE =
          neutrino::backendProjectionToText(*coordinationPlanE);
      if (!projTextE)
        return fail("spec.ast", toString(projTextE.takeError()), EXIT_IR);
      std::string path =
          (std::filesystem::path(outStr) / "coordination-plan.json").string();
      std::error_code ec;
      raw_fd_ostream os(path, ec);
      if (ec)
        return fail("internal", "cannot write " + path + ": " + ec.message(),
                    EXIT_USAGE);
      os << *planTextE;
      os.close();
      errs() << "wrote " << path << "\n";
      std::string projPath =
          (std::filesystem::path(outStr) / "backend-projection.json").string();
      raw_fd_ostream projOs(projPath, ec);
      if (ec)
        return fail("internal",
                    "cannot write " + projPath + ": " + ec.message(),
                    EXIT_USAGE);
      projOs << *projTextE;
      projOs.close();
      errs() << "wrote " << projPath << "\n";
      writeBundle(/*ok=*/true, {path, projPath});
      return EXIT_OK;
    }
    if (target == "semantic-requirements") {
      Expected<neutrino::CoordinationPlan> coordinationPlanE =
          neutrino::planFromSpec(*specObj);
      if (!coordinationPlanE) {
        std::string msg = toString(coordinationPlanE.takeError());
        return fail(codeFrom(msg, "spec.ast"), msg, EXIT_IR);
      }
      std::string path =
          (std::filesystem::path(outStr) / "semantic-requirements.json")
              .string();
      std::error_code ec;
      raw_fd_ostream os(path, ec);
      if (ec)
        return fail("internal", "cannot write " + path + ": " + ec.message(),
                    EXIT_USAGE);
      os << neutrino::semanticRequirementsToText(*coordinationPlanE);
      os.close();
      errs() << "wrote " << path << "\n";
      writeBundle(/*ok=*/true, {path});
      return EXIT_OK;
    }
    // coordination-trace (): reconstruct the coordination plan from the
    // external spec, then run the reference evaluator on the --scenario's
    // transition input — the spec-reconstruction path of the semantic oracle,
    // verified to reach the same trace as the from-MLIR target on the same
    // procedure.
    if (target == "coordination-trace") {
      if (scenarioFile.empty())
        return fail(
            "usage.scenario",
            "--target=coordination-trace --from-spec requires --scenario",
            EXIT_USAGE);
      Expected<neutrino::CoordinationPlan> coordinationPlanE =
          neutrino::planFromSpec(*specObj);
      if (!coordinationPlanE) {
        std::string msg = toString(coordinationPlanE.takeError());
        return fail(codeFrom(msg, "spec.ast"), msg, EXIT_IR);
      }
      // Semantic realization-legality (): the reference evaluator refuses a
      // coordination plan outside its supported subset before evaluating.
      if (int rc = gatePlanLegality(*coordinationPlanE); rc >= 0)
        return rc;
      neutrino::Scenario scenario;
      try {
        scenario = neutrino::loadScenario(scenarioFile);
      } catch (const neutrino::ScenarioError &e) {
        return fail(e.code, e.what(), EXIT_SCENARIO);
      }
      std::string path =
          (std::filesystem::path(outStr) / "coordination-trace.json").string();
      std::error_code ec;
      raw_fd_ostream os(path, ec);
      if (ec)
        return fail("internal", "cannot write " + path + ": " + ec.message(),
                    EXIT_USAGE);
      os << neutrino::coordinationTraceFromScenario(*coordinationPlanE,
                                                    scenario);
      os.close();
      errs() << "wrote " << path << "\n";
      writeBundle(/*ok=*/true, {path});
      return EXIT_OK;
    }
    if (targetEntry && targetEntry->externalPackage) {
      Expected<neutrino::CoordinationPlan> coordinationPlanE =
          neutrino::planFromSpec(*specObj);
      if (!coordinationPlanE) {
        std::string msg = toString(coordinationPlanE.takeError());
        return fail(codeFrom(msg, "spec.ast"), msg, EXIT_IR);
      }
      if (neutrino::hasSecurityViolations(*specObj))
        return fail(
            "security.gate",
            "refusing to lower an insecure capability: the Capability Security "
            "Pass found hard violations. Run --target=security for details. "
            "External-package dispatch cannot be authorized with "
            "--allow-insecure.",
            EXIT_SECURITY);
      if (int rc = gatePlanLegality(*coordinationPlanE); rc >= 0)
        return rc;
      return dispatchExternal(*coordinationPlanE);
    }
#ifndef NEUTRINO_CORE_ONLY
    // oracle-observer (S4/): renders N observer .js + aggregation from the
    // spec's attestation policy () + an observation binding. Multi-file
    // output, so it takes its own write path rather than the single-artifact
    // one.
    if (target == "oracle-observer") {
      if (bindingFile.empty())
        return fail("usage.target",
                    "--target=oracle-observer requires --binding "
                    "<observation-binding.json>",
                    EXIT_USAGE);
      ErrorOr<std::unique_ptr<MemoryBuffer>> bindBuf =
          MemoryBuffer::getFile(bindingFile);
      if (!bindBuf)
        return fail("binding.io",
                    "cannot read observation-binding " + bindingFile + ": " +
                        bindBuf.getError().message(),
                    EXIT_USAGE);
      Expected<json::Value> bindVal = json::parse((*bindBuf)->getBuffer());
      if (!bindVal || !bindVal->getAsObject())
        return fail("binding.schema",
                    "observation-binding " + bindingFile +
                        " is not a JSON object",
                    EXIT_USAGE);
      try {
        std::vector<neutrino::OracleFile> files =
            neutrino::generateOracleObserverFromSpec(*specObj,
                                                     *bindVal->getAsObject());
        std::vector<std::string> written;
        for (const neutrino::OracleFile &f : files) {
          std::string path = (std::filesystem::path(outStr) / f.path).string();
          std::filesystem::create_directories(
              std::filesystem::path(path).parent_path());
          std::error_code ec;
          raw_fd_ostream os(path, ec);
          if (ec)
            return fail("internal",
                        "cannot write " + path + ": " + ec.message(),
                        EXIT_USAGE);
          os << f.content;
          os.close();
          errs() << "wrote " << path << "\n";
          written.push_back(path);
        }
        writeBundle(/*ok=*/true, written);
        return EXIT_OK;
      } catch (const neutrino::ExprError &e) {
        return fail(e.code, e.what(), EXIT_IR);
      } catch (const std::exception &e) {
        return fail("binding.schema", e.what(), EXIT_USAGE);
      }
    }
    // Coordination-coordinationPlan normalization (): reconstruct + VERIFY
    // the coordinationPlan from the external spec BEFORE renderer dispatch (a
    // missing / non-ref / ambiguous workflow key, an undeclared/ambiguous
    // policy binding, or an unbalanced guard group is a clean diagnostic here,
    // not a fatal abort in a renderer), then hand the SAME coordinationPlan
    // instance to the renderer.
    Expected<neutrino::CoordinationPlan> coordinationPlanE =
        neutrino::planFromSpec(*specObj);
    if (!coordinationPlanE) {
      std::string msg = toString(coordinationPlanE.takeError());
      return fail(codeFrom(msg, "spec.ast"), msg, EXIT_IR);
    }
    const neutrino::CoordinationPlan &coordinationPlan = *coordinationPlanE;
    // Semantic realization-legality (): a rigid lowering refuses a
    // coordination plan its --profile does not realize, before rendering.
    if (int rc = gatePlanLegality(coordinationPlan); rc >= 0)
      return rc;
    try {
      std::string content =
          neutrino::generatePostgresProcedureFromSpec(coordinationPlan);
      std::string artifactPath =
          (std::filesystem::path(outStr) / "procedure.sql").string();
      std::filesystem::create_directories(
          std::filesystem::path(artifactPath).parent_path());
      std::error_code ec;
      raw_fd_ostream os(artifactPath, ec);
      if (ec)
        return fail("internal",
                    "cannot write " + artifactPath + ": " + ec.message(),
                    EXIT_USAGE);
      os << content;
      os.close();
      errs() << "wrote " << artifactPath << "\n";
      writeBundle(/*ok=*/true, {artifactPath});
      return EXIT_OK;
    } catch (const neutrino::ExprError &e) {
      // An ill-typed serialized AST in the external spec (re-typed on
      // ingestion): expr.type, treated like any source-level semantic error
      // (EXIT_IR).
      return fail(e.code, e.what(), EXIT_IR);
    } catch (const std::exception &e) {
      return fail("spec.schema", e.what(), EXIT_USAGE);
    }
#endif
    return fail("internal", "unhandled core target '" + target + "'",
                EXIT_USAGE);
  }

  mlir::MLIRContext ctx;
  ctx.getOrLoadDialect<neutrino::NeutrinoDialect>();

  neutrino::LoadResult loaded = neutrino::loadModule(inputFile, ctx);
  // A front-end typing / op-verifier failure carries a machine code in brackets
  // (e.g. `[expr.type]`); surface it as the diagnostic code rather than the
  // generic load-stage code, so expression/guard well-formedness stays a coded,
  // exit-4 failure with no artifact ().
  switch (loaded.status) {
  case neutrino::LoadStatus::SourceIoError:
    return fail("source.io", "cannot read " + inputFile + ": " + loaded.detail,
                EXIT_USAGE);
  case neutrino::LoadStatus::SourceParseError:
    return fail(codeFrom(loaded.detail, "source.parse"),
                loaded.detail.empty()
                    ? ("could not lower " + inputFile + " to valid IR")
                    : loaded.detail,
                EXIT_IR);
  case neutrino::LoadStatus::IrParseError:
    return fail("ir.parse", "could not parse " + inputFile, EXIT_USAGE);
  case neutrino::LoadStatus::IrVerifyError:
    return fail(codeFrom(loaded.detail, "ir.verify"),
                loaded.detail.empty()
                    ? std::string("input IR failed verification")
                    : loaded.detail,
                EXIT_IR);
  case neutrino::LoadStatus::Ok:
    break;
  }
  mlir::OwningOpRef<mlir::ModuleOp> module = std::move(loaded.module);

  try {
    neutrino::Scenario scenario;
    neutrino::ProcedureView view;

    if (targetEntry->scenarioFree) {
      // The canonical spec (D2 / ) is emitted from source alone: no
      // scenario is loaded or validated, and the procedure is selected from the
      // module directly.
      neutrino::ProcedureOp proc = neutrino::defaultProcedure(*module);
      if (!proc)
        return fail("source.procedure", "no procedure found in " + inputFile,
                    EXIT_IR);
      view = neutrino::viewOf(proc);
    } else {
      if (scenarioFile.empty())
        return fail("usage.scenario",
                    "--scenario is required for --target=" + target,
                    EXIT_USAGE);
      scenario = neutrino::loadScenario(scenarioFile);

      neutrino::ProcedureOp proc =
          neutrino::findProcedure(*module, scenario.procedure);
      if (!proc)
        return fail("scenario.procedure",
                    "procedure '" + scenario.procedure + "' not found in IR",
                    EXIT_SCENARIO);

      view = neutrino::viewOf(proc);

      // Validate the scenario against the procedure before generating.
      std::vector<std::string> problems =
          neutrino::validateScenario(view, scenario);
      if (!problems.empty()) {
        errs() << "error: scenario '" << scenarioFile
               << "' is invalid for procedure '" << scenario.procedure
               << "':\n";
        for (const std::string &p : problems) {
          errs() << "  - " << p << "\n";
          diags.push_back({"error", "scenario.invalid", p});
        }
        writeBundle(/*ok=*/false, {});
        return EXIT_SCENARIO;
      }
    }

    // Normalize once before ANY source-side emitter can consume the view.
    // normalizePlan is intentionally fallible even for parser/verifier-accepted
    // source: cross-policy completeness is a target-neutral semantic check.
    // Keeping this check at the dispatch waist prevents emitters that serialize
    // the normalized contract from reaching their internal cantFail assertions,
    // and guarantees a governed exit with no target artifact on rejection.
    Expected<neutrino::CoordinationPlan> coordinationPlanE =
        neutrino::normalizePlan(view);
    if (!coordinationPlanE) {
      std::string msg = toString(coordinationPlanE.takeError());
      return fail(codeFrom(msg, "spec.ast"), msg, EXIT_IR);
    }

    bool lowering = targetEntry->gated;

    // Spec-legality gate before the render (see gateLegality above): run it on
    // the same spec the renderer consumes (capabilitySpecJson), so an illegal
    // capability fails closed before emit.
    if (lowering && !profileFile.empty()) {
      Expected<json::Value> specVal =
          json::parse(neutrino::capabilitySpecJson(view, *coordinationPlanE));
      if (!specVal)
        return fail("internal",
                    "emitted capability-spec is not valid JSON: " +
                        toString(specVal.takeError()),
                    EXIT_USAGE);
      const json::Object *specObj = specVal->getAsObject();
      if (!specObj)
        return fail("internal", "emitted capability-spec is not a JSON object",
                    EXIT_USAGE);
      int rc = gateLegality(*specObj);
      if (rc >= 0)
        return rc;
    }

    // Security gate on lowering: refuse to emit deployable/coordination
    // artifacts for a capability with hard security violations, unless
    // explicitly overridden. Analysis targets (security/capability/coverage)
    // are never gated — they are how you diagnose the violation. `views` IS
    // gated: it is an agent-facing implementation contract, so an agent must
    // not receive narrowed views for a capability the security pass already
    // knows is invalid.
    if (lowering && (targetEntry->externalPackage || !allowInsecure) &&
        neutrino::hasSecurityViolations(view, *coordinationPlanE))
      return fail(
          "security.gate",
          "refusing to lower an insecure capability: the Capability Security "
          "Pass found hard violations. Run --target=security for details" +
              std::string(targetEntry->externalPackage
                              ? ". External-package dispatch cannot be "
                                "authorized with --allow-insecure."
                              : ", or pass --allow-insecure to override."),
          EXIT_SECURITY);

    // Semantic realization-legality gate (), before dispatch: the reference
    // evaluator + rigid lowerings refuse a coordination plan outside their
    // supported subset.
    if (realizesCoordinationPlan()) {
      int rc = gatePlanLegality(*coordinationPlanE);
      if (rc >= 0)
        return rc;
    }

    // : coordination-plan is serialized directly here with CHECKED Expected
    // propagation (like the --from-spec path), NEVER a cantFail re-assembly.
    // The coordination-plan text AND the complete backend projection graph are
    // both validated BEFORE any artifact is written, so a
    // serialization/legality failure fails closed with its stable diagnostic
    // and leaves neither coordination artifact partially written when either
    // serialization fails.
    if (target == "coordination-plan") {
      // Checked Expected propagation (never cantFail): the same shared helper
      // as the --from-spec path folds the fault seam into the returned
      // Expected, so this ordinary takeError() path produces the diagnostic.
      // ()
      Expected<std::string> planTextE =
          coordinationPlanTextChecked(*coordinationPlanE);
      if (!planTextE)
        return fail("spec.ast", toString(planTextE.takeError()), EXIT_IR);
      if (projectionFaultSelftest)
        return fail("spec.ast", "diag:test:forced-projection-failure", EXIT_IR);
      Expected<std::string> projTextE =
          neutrino::backendProjectionToText(*coordinationPlanE);
      if (!projTextE)
        return fail("spec.ast", toString(projTextE.takeError()), EXIT_IR);
      std::string coordinationPlanPath =
          (std::filesystem::path(outStr) / "coordination-plan.json").string();
      std::string projPath =
          (std::filesystem::path(outStr) / "backend-projection.json").string();
      std::error_code ec;
      raw_fd_ostream coordinationPlanOs(coordinationPlanPath, ec);
      if (ec)
        return fail("internal",
                    "cannot write " + coordinationPlanPath + ": " +
                        ec.message(),
                    EXIT_USAGE);
      coordinationPlanOs << *planTextE;
      coordinationPlanOs.close();
      raw_fd_ostream projOs(projPath, ec);
      if (ec)
        return fail("internal",
                    "cannot write " + projPath + ": " + ec.message(),
                    EXIT_USAGE);
      projOs << *projTextE;
      projOs.close();
      errs() << "wrote " << coordinationPlanPath << "\n";
      errs() << "wrote " << projPath << "\n";
      writeBundle(/*ok=*/true, {coordinationPlanPath, projPath});
      return EXIT_OK;
    }

    if (target == "capability") {
      neutrino::SelfEmittedSpec spec =
          neutrino::ingestSelfEmittedSpec(view, *coordinationPlanE);
      Expected<std::vector<neutrino::CapabilityModelArtifact>> artifacts =
          neutrino::generateCapabilityModelsFromSpec(
              spec.object(), catalog.identity(), catalog.profiles());
      if (!artifacts)
        return fail("capability.catalog", toString(artifacts.takeError()),
                    EXIT_USAGE);
      std::vector<neutrino::artifact_publication::CoreArtifact> pending;
      pending.reserve(artifacts->size() + 1);
      Expected<std::string> catalogBytes =
          neutrino::capabilityModelCatalogBytes(catalog.identity(),
                                                catalog.profiles());
      if (!catalogBytes)
        return fail("capability.catalog", toString(catalogBytes.takeError()),
                    EXIT_USAGE);
      pending.push_back({"catalog.json", std::move(*catalogBytes)});
      for (const neutrino::CapabilityModelArtifact &artifact : *artifacts)
        pending.push_back({artifact.fileName, artifact.bytes});
      Expected<std::vector<neutrino::artifact_publication::PublishedArtifact>>
          published = neutrino::artifact_publication::publishCoreArtifacts(
              pending, outStr);
      if (!published)
        return fail("artifact.publish", toString(published.takeError()),
                    EXIT_USAGE);
      std::vector<std::string> written;
      for (const auto &artifact : *published)
        written.push_back(
            (std::filesystem::path(outStr) / artifact.path).string());
      for (const std::string &path : written)
        errs() << "wrote " << path << "\n";
      writeBundle(/*ok=*/true, written);
      errs() << "wrote " << outStr << "/manifest.json\n";
      errs() << "wrote " << diagPath << "\n";
      return EXIT_OK;
    }

    if (targetEntry->externalPackage) {
      return dispatchExternal(*coordinationPlanE);
    }

    // A driver-serialized target (coordination-plan, ) registers no emit
    // function; it is handled by the checked block above and returns before
    // here. Fail closed rather than dereference a null EmitFn if a future
    // driver-serialized target reaches this generic dispatch.
    if (targetEntry->driverSerialized || !targetSpec || !targetSpec->emit)
      return fail("internal",
                  "target '" + target +
                      "' is driver-serialized and has no registered emitter",
                  EXIT_USAGE);
    std::vector<std::string> written =
        targetSpec->emit(view, scenario, outDir, *coordinationPlanE);

    for (const std::string &p : written)
      errs() << "wrote " << p << "\n";

    // Security gate: for --target=security a hard violation fails the command
    // so `make security` / agents can block before relying on the capability.
    // The failure state must be reflected in the WHOLE bundle — manifest.json
    // and diagnostics.json, not just the exit code and security.json — so an
    // agent that reads the JSON instead of the exit status still sees
    // ok:false.
    bool securityViolation =
        (target == "security" &&
         neutrino::hasSecurityViolations(view, *coordinationPlanE));
    if (securityViolation)
      diags.push_back({"error", "security.violation",
                       "capability security pass found hard violations (see " +
                           outStr + "/security.json)"});

    // Machine-readable manifest + diagnostics of the run.
    writeBundle(/*ok=*/!securityViolation, written);
    errs() << "wrote " << outStr << "/manifest.json\n";
    errs() << "wrote " << diagPath << "\n";

    if (securityViolation) {
      errs() << "error: capability security pass found hard violations (see "
             << outStr << "/security.json)\n";
      return EXIT_SECURITY;
    }
  } catch (const neutrino::ScenarioError &e) {
    // user-correctable input errors: distinct codes, not "internal".
    int exitCode = (e.code == "scenario.schema") ? EXIT_SCENARIO : EXIT_USAGE;
    return fail(e.code, e.what(), exitCode);
  } catch (const neutrino::ExprError &e) {
    // A compute expression that is unsupported or ill-typed:
    // surfaced here because expressions are parsed + typed once when the view
    // is built. It is a source-level semantic error, so it fails like a
    // parse/IR error for EVERY target, analysis targets included (expression
    // well-formedness is L1 well-formedness; see
    // docs/language/EXPRESSION_MODEL.md). The machine-readable discriminator is
    // the diagnostic code (expr.unsupported / expr.type), not scraped from the
    // message.
    return fail(e.code, e.what(), EXIT_IR);
  } catch (const std::exception &e) {
    return fail("internal", e.what(), EXIT_USAGE);
  }
  return EXIT_OK;
}
