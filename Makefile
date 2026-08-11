# Neutrino translator developer commands. See docs/testing/TESTING.md.

.DEFAULT_GOAL := build

# CMake build, generated artifacts, and packages use separate overridable trees.
BUILD_DIR    ?= out
ARTIFACT_DIR ?= build
DIST_DIR     ?= dist

EXAMPLE       := test/ir/pipeline/Inputs/core_sample_installment/source/core_sample_installment.neu
SCENARIO      := test/ir/pipeline/Inputs/core_sample_installment/scenario/core_sample_installment_happy_path.json
MLIR          := $(ARTIFACT_DIR)/core_sample_installment.mlir

EXAMPLE2      := test/ir/pipeline/Inputs/core_scheme_settlement/source/core_scheme_settlement.neu
SCENARIO2     := test/ir/pipeline/Inputs/core_scheme_settlement/scenario/core_scheme_settlement_happy_path.json

# Override on Linux with LLVM_PREFIX=/usr/lib/llvm-15.
LLVM_PREFIX   ?= $(shell brew --prefix llvm 2>/dev/null || brew --prefix llvm@15 2>/dev/null || llvm-config-15 --prefix 2>/dev/null || llvm-config --prefix 2>/dev/null)
SOLC          ?= $(shell command -v solc 2>/dev/null)
FORGE         ?= $(CURDIR)/.foundry/bin/forge

# The prebuilt macOS Forge hard-links libusb under the DEFAULT Homebrew prefix, so a box with any
# other prefix aborts in dyld before conformance is measured (). Carry the declared search
# prefix through a NEUTRAL variable because macOS SIP strips DYLD_* from the acceptance wrapper's
# environment; run.sh / the goldens checker / neutrino-equiv re-materialise it at the actual Forge
# process boundary. scripts/gates/check_forge_toolchain.py is the SINGLE derivation authority —
# cmake configures the ctest rows from the same call, so nothing here may re-derive it.
FORGE_LIBRARY_PATH := $(shell python3 scripts/gates/check_forge_toolchain.py --print-library-path 2>/dev/null)
ifneq ($(FORGE_LIBRARY_PATH),)
FORGE_ENV     := FORGE_DYLD_LIBRARY_PATH="$(FORGE_LIBRARY_PATH)"
endif
FORGE_ENV     ?=

OPT       := $(BUILD_DIR)/tools/neutrino-opt/neutrino-opt
TRANSLATE := $(BUILD_DIR)/tools/neutrino-translate/neutrino-translate
EMIT      := $(BUILD_DIR)/tools/neutrino-emit/neutrino-emit
GEN       := $(BUILD_DIR)/tools/neutrino-gen/neutrino-gen
EQUIV     := $(BUILD_DIR)/tools/neutrino-equiv/neutrino-equiv
BUNDLE    := $(BUILD_DIR)/tools/neutrino-bundle/neutrino-bundle

FILECHECK ?= $(LLVM_PREFIX)/bin/FileCheck

# Keep network-dependent gtest configuration opt-in.
BUILD_UNITTESTS ?= OFF

# Grouping keeps the public command surface fully phony.
BUILD_TARGETS := build configure compile-db setup-foundry setup-build-tools-verifier clean clean-artifacts clean-build \
	forge-toolchain-check forge-toolchain-receipt forge-toolchain-verify
QUALITY_TARGETS := fmt fmt-check tidy test test-fast test-full ir-test ir-test-terminal unittest \
	asan ubsan asan-ubsan cpp-coverage acceptance acceptance-suite
PIPELINE_TARGETS := translate verify emit demo language-metadata grammar linguist \
	regen-target-node-registry regen-postgres-recipe-builders regen-postgres-ddl-builders regen-generalism-cells run-generalism-matrix \
	bundle slot capability views mutation fork property coverage security capability-check validate cross-rail
BACKEND_TARGETS := solidity-test solidity-explicit-time-test solidity-reference-test oracle-coordination-test oracle-temporal-test \
	compliant-transfer-backend-test postgres-quorum-guard-test cross-border-acceptance-test db-test equivalence equivalence-scheme
RELEASE_TARGETS := generate-sample-artifacts native-build-gate release-manifest release-gate release smoke
CORE_ONLY_TARGETS := core-only-verify

.PHONY: $(BUILD_TARGETS) $(QUALITY_TARGETS) $(PIPELINE_TARGETS) $(BACKEND_TARGETS) $(RELEASE_TARGETS) $(CORE_ONLY_TARGETS)

# The EXECUTED entrypoint for the backend-free core contract (). Everything
# it drives already existed; nothing drove it. `cmake/NeutrinoCoreOnly.cmake` is
# included only under `if(NEUTRINO_CORE_ONLY)`, so the `core-only*` targets and
# their ctest rows exist only inside a core-only configure -- and no target and no
# workflow ever performed that configure, leaving the gate that proves acceptance
# bullet 1 runnable only by hand. This runs it, in its own isolated build tree so
# it can never inherit a cache in which the backends were configured.
core-only-verify:
	python3 scripts/gates/run_core_only_verify.py --llvm-prefix "$(LLVM_PREFIX)"

# Always pass this value so an empty setting clears CMake's cached launcher.
CMAKE_LAUNCHER ?=

# Configure without compiling.
configure:
	cmake -S . -B $(BUILD_DIR) -G Ninja \
		-DMLIR_DIR="$(LLVM_PREFIX)/lib/cmake/mlir" \
		-DLLVM_DIR="$(LLVM_PREFIX)/lib/cmake/llvm" \
		-DCMAKE_C_COMPILER_LAUNCHER="$(CMAKE_LAUNCHER)" \
		-DCMAKE_CXX_COMPILER_LAUNCHER="$(CMAKE_LAUNCHER)" \
		-DNEUTRINO_BUILD_UNITTESTS=$(BUILD_UNITTESTS) \
		-DCMAKE_BUILD_TYPE=Release $(EXTRA_CMAKE)

build: configure
	ninja -C $(BUILD_DIR) postgres-mutation-input-reconciliation neutrino-opt neutrino-translate neutrino-emit neutrino-gen neutrino-gen-schema-mutated neutrino-gen-coordination-status-mutated neutrino-gen-ledger-balance-mutated neutrino-gen-posting-idempotency-table-mutated neutrino-gen-committed-group-table-mutated neutrino-gen-postings-base-mutated neutrino-gen-postings-memo-mutated neutrino-gen-key-claim-table-mutated neutrino-gen-quorum-acceptance-table-mutated neutrino-gen-temporal-quorum-acceptance-table-mutated neutrino-equiv neutrino-bundle \
	  spec-contract-smoke backend-solidity-smoke backend-postgres-smoke slot-spec-smoke security-policy-smoke capability-profile-smoke oracle-observer-smoke coverage-spec-smoke views-spec-smoke \
	  solidity-model-test postgres-model-test \
	  solidity-localdecl-render-committed solidity-localdecl-render-mutated \
	  solidity-assign-render-committed solidity-assign-render-mutated \
	  solidity-compound-render-committed solidity-compound-render-mutated \
	  solidity-doccomment-render-committed solidity-doccomment-render-mutated \
	  solidity-spdx-render-committed solidity-spdx-render-mutated \
	  solidity-pragma-render-committed solidity-pragma-render-mutated \
	  solidity-import-render-committed solidity-import-render-mutated \
	  solidity-enum-render-committed solidity-enum-render-mutated \
	  solidity-storage-render-committed solidity-storage-render-mutated \
	  solidity-event-render-committed solidity-event-render-mutated \
	  solidity-functionsig-render-committed solidity-functionsig-render-mutated \
	  solidity-contractshell-render-committed solidity-contractshell-render-mutated \
	  solidity-interfacesig-render-committed solidity-interfacesig-render-mutated \
	  solidity-interfaceshell-render-committed solidity-interfaceshell-render-mutated \
	  postgres-progressflag-render-committed postgres-progressflag-render-mutated \
	  postgres-postingidempotency-render-committed postgres-postingidempotency-render-mutated \
	  postgres-keyclaiminsert-render-committed postgres-keyclaiminsert-render-mutated \
	  postgres-committedgroupinsert-render-committed postgres-committedgroupinsert-render-mutated \
	  postgres-quorumacceptinsert-render-committed postgres-quorumacceptinsert-render-mutated \
	  postgres-temporalacceptinsert-render-committed postgres-temporalacceptinsert-render-mutated \
	  postgres-idempotentreturn-render-committed postgres-idempotentreturn-render-mutated \
	  postgres-evidenceclaimcomment-render-committed postgres-evidenceclaimcomment-render-mutated \
	  postgres-policycaseselect-render-committed postgres-policycaseselect-render-mutated \
	  postgres-effectledgercomment-render-committed postgres-effectledgercomment-render-mutated \
	  postgres-idempotencyguardcomment-render-committed postgres-idempotencyguardcomment-render-mutated \
	  postgres-balancedinvariantcomment-render-committed postgres-balancedinvariantcomment-render-mutated \
	  postgres-effect-render-committed postgres-effect-render-mutated \
	  postgres-callablesig-render-mutated \
	  postgres-declaresection-render-mutated \
	  postgres-callablebody-render-mutated \
	  postgres-callableclose-render-mutated \
	  postgres-if-render-mutated \
	  postgres-flatif-render-mutated \
	  postgres-idempotencyguard-render-mutated-real \
	  postgres-balancedinvariant-render-mutated-real \
	  lines-fixture-render-committed lines-fixture-render-mutated \
	  framed-lines-fixture-render-committed \
	  framed-lines-fixture-render-header framed-lines-fixture-render-item \
	  framed-lines-fixture-render-footer framed-lines-fixture-render-placeholder

# clang-tidy needs the compile database and every generated header, not binaries.
compile-db: configure
	ninja -C $(BUILD_DIR) NeutrinoIncGen

# Format changed C++ lines relative to FMT_BASE.
FMT_BASE ?= origin/main
fmt-check:
	bash scripts/run_fmt.sh check $(FMT_BASE)

fmt:
	bash scripts/run_fmt.sh apply $(FMT_BASE)

# Static analysis; see .clang-tidy.
tidy: compile-db
	bash scripts/run_tidy.sh

setup-foundry:
	FOUNDRY_DIR=$(CURDIR)/.foundry bash -c 'curl -L --silent https://foundry.paradigm.xyz | bash && $(CURDIR)/.foundry/bin/foundryup'
	@echo "foundry installed under .foundry (needs: brew install libusb)"
	@echo "next: make forge-toolchain-check  (see docs/testing/FORGE_TOOLCHAIN.md)"

# Forge provisioning (). `check` asserts the configured forge's native closure resolves and
# that the guard bites; `receipt`/`verify` record and re-check this machine's tool identity.
FORGE_RECEIPT ?= docs/testing/forge-toolchain-receipts/macos-self-hosted.receipt.json

forge-toolchain-check:
	python3 scripts/gates/check_forge_toolchain.py --preflight
	python3 scripts/gates/check_forge_toolchain.py --selftest

forge-toolchain-receipt:
	python3 scripts/gates/check_forge_toolchain.py --emit-receipt $(FORGE_RECEIPT)

forge-toolchain-verify:
	python3 scripts/gates/check_forge_toolchain.py --verify-receipt $(FORGE_RECEIPT)

# Core pipeline
translate: build
	@mkdir -p $(ARTIFACT_DIR)
	$(TRANSLATE) $(EXAMPLE) -o $(MLIR)

verify: translate
	$(OPT) $(MLIR) >/dev/null && echo "OK: verified by neutrino-opt"

# `events` is an inspection view, not a backend.
emit: build
	@mkdir -p $(ARTIFACT_DIR)
	$(EMIT) --kind=events $(EXAMPLE) -o $(ARTIFACT_DIR)/events.txt
	@echo "wrote $(ARTIFACT_DIR)/events.txt (inspection); backends: neutrino-gen --target=postgres|solidity"

# Regenerate committed language metadata after grammar or value-model changes.
language-metadata: build
	$(TRANSLATE) --language-metadata > docs/language-metadata.json
	@echo "wrote docs/language-metadata.json"

# Generate the TextMate grammar from language-metadata.json.
grammar:
	python3 scripts/generators/generate_tmgrammar.py > docs/neutrino.tmLanguage.json
	@echo "wrote docs/neutrino.tmLanguage.json"

# Package the generated grammar for GitHub Linguist.
linguist:
	python3 scripts/generators/generate_linguist_assets.py --write
	@echo "wrote linguist/ package"

# [/] Regenerate EVERY registered target-node metadata registry from its .td source of truth via
# the pinned llvm-tblgen. Backends are discovered from lib/backends/**/*TargetNodes.td (the target/model/
# X-macro are registry-derived from the record), so a new backend is covered by adding its .td — no edit
# here. The committed .inc is checked fresh by the `target-node-registry` ctest; run this after editing a
# *TargetNodes.td.
regen-target-node-registry:
	@set -e; \
	found=0; \
	for td in $$(find lib/backends -name '*TargetNodes.td' | sort); do \
		found=1; \
		dir=$$(dirname "$$td"); stem=$$(basename "$$td" TargetNodes.td); \
		gendir="$$dir"; \
		if [ "$$(basename "$$dir")" = model ] && [ -d "$$(dirname "$$dir")/generated" ]; then \
			gendir="$$(dirname "$$dir")/generated"; \
		fi; \
		python3 scripts/generators/gen_target_node_registry.py \
			--td "$$td" \
			--out "$$gendir/$${stem}TargetNodes.inc" \
			--printer-out "$$gendir/$${stem}PrinterHandlers.inc" \
			--enums-out "$$gendir/$${stem}TargetEnums.inc" || exit 1; \
	done; \
	if [ "$$found" = 0 ]; then \
		echo "regen-target-node-registry: no *TargetNodes.td found (fail closed)" >&2; exit 1; \
	fi

# : regenerate the committed PostgreSQL recipe node builders from
# PostgresTargetNodes.td. The committed .inc pair is checked fresh by
# test/checks/fast/postgres_recipe_builders_freshness_test.py.
regen-postgres-recipe-builders:
	python3 scripts/generators/backend_recipe_gen.py --profile postgres-recipe-builders \
		--td lib/backends/postgres/model/PostgresTargetNodes.td \
		--tblgen $(LLVM_PREFIX)/bin/llvm-tblgen \
		-I lib/backends \
		--decl-out lib/backends/postgres/generated/PostgresRecipeBuilders.decl.inc \
		--def-out lib/backends/postgres/generated/PostgresRecipeBuilders.inc

#  (Group C): regenerate the authenticated PostgreSQL raw-DDL carrier
# construction (pgddl::DdlCap::forge / rawSql / operator+) from the closed
# PostgresDdlCarrier.td descriptor. The committed .inc is byte-checked at build
# (CMake compare_files) and by the census freshness probe.
regen-postgres-ddl-builders:
	python3 scripts/generators/backend_recipe_gen.py --profile postgres-ddl-builders \
		--td lib/backends/postgres/model/PostgresDdlCarrier.td \
		--tblgen $(LLVM_PREFIX)/bin/llvm-tblgen \
		-I lib/backends \
		-o lib/backends/postgres/generated/PgDdlBuilders.inc

# [] Regenerate the backend-generalism cell manifest from the capability-spec schema + Solidity
# classification + the 16  seed cells. The committed manifest is checked fresh + coverage-ratcheted
# by check_generalism_cell_coverage.py; run this after a schema/classification/seed change.
regen-generalism-cells:
	python3 scripts/generators/gen_generalism_cells.py

# [] M6 generalism S2: drive the 32 schema-derived cells through the canonical stack (waist ->
# reference evaluator -> rigid Solidity/Postgres targets -> neutrino-equiv) and emit one
# generalism-result envelope per exact execution identity — each carrying genuine per-run S4 evidence
# signed + verified through the pinned build-tools verifier — plus a run manifest referencing all 32
# cells (for  to classify). Needs the built binaries + `make setup-build-tools-verifier`; results
# land in test/generalism/results/ (generated, git-ignored). --validate runs the UNMODIFIED  validator.
run-generalism-matrix:
	python3 scripts/generators/run_generalism_matrix.py --validate

demo: translate verify emit
	@echo ""
	@echo "demo complete — artifacts in $(ARTIFACT_DIR)/"

# Backend / e2e acceptance checks (). The recipe + skip-when-absent lives once in
# test/acceptance/run.sh, registered as labeled CTest tests (cmake/NeutrinoAcceptanceTests.cmake).
# These targets are thin `ctest -R` wrappers; NEUTRINO_REQUIRE_TOOLS=1 makes a missing
# solc/forge/docker a HARD failure here (CI must not silently skip its evidence), whereas a
# bare `ctest -L acceptance` skips what it cannot provision. FORGE/SOLC are exported so
# run.sh's detection matches this repo's pinned Foundry layout.
_ACCEPTANCE_ENV = NEUTRINO_REQUIRE_TOOLS=1 $(FORGE_ENV) FORGE="$(FORGE)" SOLC="$(SOLC)"
define _run_acceptance
	$(_ACCEPTANCE_ENV) ctest --test-dir $(BUILD_DIR) -R '^$(1)$$' --output-on-failure
endef

solidity-test: build
	NEU_SOURCE="$(EXAMPLE)" NEU_SCENARIO="$(SCENARIO)" $(call _run_acceptance,acceptance-solidity)

# : generated Foundry coverage for both sides of the explicit timestamp
# guard, wired into final-head full CI below.
solidity-explicit-time-test: build
	$(call _run_acceptance,acceptance-solidity-explicit-time)

# The reviewed oracle reference contract is a HAND-AUTHORED Foundry project — it needs
# neither neutrino-gen nor an MLIR build, and its dedicated CI runner (oracle-reference.yml)
# provisions only solc + Foundry. So this target invokes run.sh DIRECTLY (no `build`, no ctest),
# preserving the build-free shape; `ctest -L acceptance` still runs it via acceptance-solidity-reference.
solidity-reference-test:
	NEUTRINO_REQUIRE_TOOLS=1 $(FORGE_ENV) FORGE="$(FORGE)" SOLC="$(SOLC)" \
		bash test/acceptance/run.sh solidity-reference "" $(ARTIFACT_DIR)

# Test quorum coordination in generated Solidity.
oracle-coordination-test: build
	$(call _run_acceptance,acceptance-oracle-coordination)

#  activation: the per-policy temporal commit-ledger contract + behavioral matrix.
oracle-temporal-test: build
	$(call _run_acceptance,acceptance-oracle-temporal)

# Exercise compliance guard values 0, 1, and 2 on both backends.
compliant-transfer-backend-test: build
	$(call _run_acceptance,acceptance-compliant-transfer)

# Exercise PostgreSQL quorum admission failures against a real database.
postgres-quorum-guard-test: build
	$(call _run_acceptance,acceptance-postgres-quorum-guard)

# M5 signature domain () slice 3: the four BEHAVIORAL acceptance tests for the three cross-border
# oracle legs on a real PostgreSQL container — happy / missing-quorum-blocks / insurance-payout /
# adversarial. Postgres rail only (no solc/forge).
cross-border-acceptance-test: build
	$(call _run_acceptance,acceptance-cross-border)

db-test: build
	NEU_SOURCE="$(EXAMPLE)" NEU_SCENARIO="$(SCENARIO)" $(call _run_acceptance,acceptance-db)

equivalence: build
	NEU_SOURCE="$(EXAMPLE)" NEU_SCENARIO="$(SCENARIO)" $(call _run_acceptance,acceptance-equivalence)

equivalence-scheme: build
	NEU_SOURCE="$(EXAMPLE2)" NEU_SCENARIO="$(SCENARIO2)" $(call _run_acceptance,acceptance-equivalence-scheme)

# The whole heavy suite in one selection (skips what the box can't provision unless REQUIRE is set).
acceptance-suite: build
	$(FORGE_ENV) FORGE="$(FORGE)" SOLC="$(SOLC)" \
		ctest --test-dir $(BUILD_DIR) -L acceptance --output-on-failure

# Check read-only sibling-repository boundaries.
cross-rail: build
	python3 scripts/rails/cross_rail_dry_run.py

slot: build
	@mkdir -p $(ARTIFACT_DIR)
	$(GEN) --target=slot --scenario=$(SCENARIO) $(EXAMPLE) -o $(ARTIFACT_DIR)/slot
	@echo "wrote $(ARTIFACT_DIR)/slot/ (capability/operations/compensation/transcript/envelope.schema)"

capability: build
	@mkdir -p $(ARTIFACT_DIR)
	@set -eu; \
		run_dir=$$(mktemp -d "$(ARTIFACT_DIR)/capability-run.XXXXXX"); \
		$(GEN) --target=capability --scenario=$(SCENARIO) $(EXAMPLE) -o "$$run_dir"; \
		echo "wrote $$run_dir/ (one model per verified target profile)"

views: build
	@mkdir -p $(ARTIFACT_DIR)/views
	$(GEN) --target=views --scenario=$(SCENARIO) $(EXAMPLE) -o $(ARTIFACT_DIR)/views
	@echo "wrote $(ARTIFACT_DIR)/views/<participant>.json (per-participant narrowed views)"

# Mutation-test frontend and verifier invariants.
mutation: build
	@mkdir -p $(ARTIFACT_DIR)/mutation
	python3 scripts/mutation_test.py --source $(EXAMPLE) --translate $(TRANSLATE) \
		--opt $(OPT) --out $(ARTIFACT_DIR)/mutation

# Scaffold a minor capability-version fork.
fork: build
	@mkdir -p $(ARTIFACT_DIR)/fork
	python3 scripts/generators/fork_capability.py --source $(EXAMPLE) --bump minor \
		--out $(ARTIFACT_DIR)/fork/forked.neu --manifest $(ARTIFACT_DIR)/fork/fork-manifest.json

# Run seeded property tests for conservation and determinism.
property: build
	@mkdir -p $(ARTIFACT_DIR)/property
	python3 scripts/property_test.py --source $(EXAMPLE) --scenario $(SCENARIO) \
		--equiv $(EQUIV) --out $(ARTIFACT_DIR)/property

# Generate semantic language-level coverage (distinct from C++ coverage).
coverage: build
	@mkdir -p $(ARTIFACT_DIR)
	$(GEN) --target=coverage --scenario=$(SCENARIO) $(EXAMPLE) -o $(ARTIFACT_DIR)/coverage
	@echo "wrote $(ARTIFACT_DIR)/coverage/coverage.json (language-level coverage + maturity ceiling)"

# Generate the capability security report.
security: build
	@mkdir -p $(ARTIFACT_DIR)/security
	$(GEN) --target=security --scenario=$(SCENARIO) $(EXAMPLE) -o $(ARTIFACT_DIR)/security
	@echo "wrote $(ARTIFACT_DIR)/security/security.json (Capability Security Pass)"

# Check that Verified capability claims have supporting evidence.
capability-check: build
	@mkdir -p $(ARTIFACT_DIR)
	@set -eu; \
		run_dir=$$(mktemp -d "$(ARTIFACT_DIR)/capability-check-run.XXXXXX"); \
		models="$$run_dir/models"; spec_dir="$$run_dir/spec"; \
		$(GEN) --verified-target-profile-catalog > "$$run_dir/trusted-catalog.json"; \
		$(GEN) --target=capability --scenario=$(SCENARIO) $(EXAMPLE) -o "$$models" >/dev/null; \
		$(GEN) --target=capability-spec $(EXAMPLE) -o "$$spec_dir" >/dev/null; \
		python3 scripts/gates/check_capability_claims.py --capability "$$models" \
			--scenario $(SCENARIO) --spec "$$spec_dir/capability-spec.json" \
			--trusted-catalog "$$run_dir/trusted-catalog.json" \
			--model-schema lib/policy/capability-profile/backend-capability-model-v1.schema.json \
			--out "$$run_dir/check"; \
		echo "capability claims verified in $$run_dir"

# Validate generated backends; optional validators skip when unavailable.
validate: build
	@mkdir -p $(ARTIFACT_DIR)/validate
	$(GEN) --target=solidity --scenario=$(SCENARIO) $(EXAMPLE) -o $(ARTIFACT_DIR)/validate/solidity >/dev/null
	$(GEN) --target=postgres --scenario=$(SCENARIO) $(EXAMPLE) -o $(ARTIFACT_DIR)/validate/postgres >/dev/null
	python3 scripts/validators/validate_backends.py --solidity $(ARTIFACT_DIR)/validate/solidity \
		--postgres $(ARTIFACT_DIR)/validate/postgres --out $(ARTIFACT_DIR)/validate/report --solc "$(SOLC)"

# Build an input bundle and render its requested targets.
bundle: build
	@mkdir -p $(ARTIFACT_DIR)/inbundle
	cp $(EXAMPLE) $(ARTIFACT_DIR)/inbundle/source.neu
	cp $(SCENARIO) $(ARTIFACT_DIR)/inbundle/scenario.json
	printf '{ "targets": ["solidity", "postgres"] }\n' > $(ARTIFACT_DIR)/inbundle/target.json
	NEUTRINO_GEN="$(GEN)" $(BUNDLE) $(ARTIFACT_DIR)/inbundle -o $(ARTIFACT_DIR)/outbundle
	@echo "--- $(ARTIFACT_DIR)/outbundle/bundle.json ---"
	@cat $(ARTIFACT_DIR)/outbundle/bundle.json

# Tests; see docs/testing/TESTING.md.
test-fast:
	python3 -m unittest discover -s test/checks/fast -p '*_test.py' -t test/checks/fast

# Fast, golden, and s5f have separate entry points and prerequisites.
test: build
	ctest --test-dir $(BUILD_DIR) --output-on-failure -LE 'umbrella|fast|golden|s5f|acceptance'

test-full: test

# Run only the lit/FileCheck IR suite.
ir-test: build
	ctest --test-dir $(BUILD_DIR) -R '^lit$$' --output-on-failure

# 's terminal entrypoint ( Stage B / ). DELIBERATELY NOT a registered
# CTest: terminal mode refuses a dirty tree and binds provenance to HEAD^, so a
# registered row would be swept into ordinary selections and fail on any developer's
# working tree. The registered `lit` row above stays NON-terminal, which is what keeps
# the ratchet enforcing the floor at every later head while refusal/provenance stay
# terminal-only. Invoke explicitly, and record the exact command in  BEFORE the run.
ir-test-terminal: build
	python3 $(CURDIR)/scripts/gates/run_lit_suite_accounting.py \
	  --lit $$(command -v lit) \
	  --suite $(BUILD_DIR)/test/ir \
	  --report $(BUILD_DIR)/test/ir/lit-suite-accounting.json \
	  --baseline $(CURDIR)/docs/m6-lit-suite-accounting-baseline.json \
	  --terminal

# Enable gtest only for the unit-test target.
unittest: BUILD_UNITTESTS = ON
unittest: configure
	ninja -C $(BUILD_DIR) NeutrinoUnitTests
	ctest --test-dir $(BUILD_DIR) -R '^unittests$$' --output-on-failure

# Isolated sanitizer and C++ coverage builds; see SANITIZERS_COVERAGE.md.
ASAN_OPTIONS  ?= detect_leaks=0:halt_on_error=0
UBSAN_OPTIONS ?= print_stacktrace=1:halt_on_error=0
# Coverage tools must match the compiler that writes the profile.
ifeq ($(shell uname -s),Darwin)
LLVM_PROFDATA ?= xcrun llvm-profdata
LLVM_COV      ?= xcrun llvm-cov
else
LLVM_PROFDATA ?= $(LLVM_PREFIX)/bin/llvm-profdata
LLVM_COV      ?= $(LLVM_PREFIX)/bin/llvm-cov
endif

asan:
	@echo "== AddressSanitizer: build our targets + run the full C++ suite (out-asan) =="
	ASAN_OPTIONS="$(ASAN_OPTIONS)" $(MAKE) BUILD_DIR=out-asan EXTRA_CMAKE="-DNEUTRINO_ENABLE_ASAN=ON" test

ubsan:
	@echo "== UndefinedBehaviorSanitizer: build our targets + run the full C++ suite (out-ubsan) =="
	UBSAN_OPTIONS="$(UBSAN_OPTIONS)" $(MAKE) BUILD_DIR=out-ubsan EXTRA_CMAKE="-DNEUTRINO_ENABLE_UBSAN=ON" test

asan-ubsan:
	@echo "== ASan + UBSan: build our targets + run the full C++ suite (out-asan-ubsan) =="
	ASAN_OPTIONS="$(ASAN_OPTIONS)" UBSAN_OPTIONS="$(UBSAN_OPTIONS)" \
		$(MAKE) BUILD_DIR=out-asan-ubsan \
		EXTRA_CMAKE="-DNEUTRINO_ENABLE_ASAN=ON -DNEUTRINO_ENABLE_UBSAN=ON" test

cpp-coverage:
	@echo "== clang source-based coverage: build instrumented + run the full C++ suite (out-cov) =="
	@rm -f out-cov/*.profraw
	LLVM_PROFILE_FILE="$(CURDIR)/out-cov/neutrino-%p.profraw" \
		$(MAKE) BUILD_DIR=out-cov EXTRA_CMAKE="-DNEUTRINO_ENABLE_COVERAGE=ON" test
	bash scripts/run_cpp_coverage.sh out-cov "$(LLVM_PROFDATA)" "$(LLVM_COV)"

# Generate and compare sample artifacts through the Ninja DAG.
generate-sample-artifacts: configure
	ninja -C $(BUILD_DIR) generate-sample-artifacts

# Compile every generated artifact claimed as native.
native-build-gate:
	@mkdir -p $(ARTIFACT_DIR)
	python3 scripts/gates/native_build_gate.py --run --summary-out $(ARTIFACT_DIR)/native-build-summary.json

# Full local acceptance. The heavy forge/docker suite runs via `acceptance-suite`
# (ctest -L acceptance), which SKIPS what this box can't provision — so `make acceptance`
# is safe to run anywhere. CI's PR gates call the specific `*-test` wrappers, which set
# NEUTRINO_REQUIRE_TOOLS=1 and therefore fail rather than skip on a provisioned runner.
acceptance: tidy test acceptance-suite validate capability-check mutation property security cross-rail
	@echo ""
	@echo "acceptance complete: self-test + both domains across IR, Solidity, PostgreSQL + backend validation"

# Build the digest-pinned release artifact manifest.
release-manifest: validate native-build-gate
	@mkdir -p $(ARTIFACT_DIR)/release
	python3 scripts/generators/make_release_manifest.py \
		--translate $(TRANSLATE) --solc "$(SOLC)" \
		--native-summary $(ARTIFACT_DIR)/native-build-summary.json \
		--validate-report $(ARTIFACT_DIR)/validate/report/validation.json \
		--out $(ARTIFACT_DIR)/release/release-artifact-manifest.json

# Release readiness excludes heavyweight acceptance-only integration checks.
release-gate: test release-manifest
	@echo ""
	@echo "release-gate complete: build + self-test + backend validation + native-build gate + release manifest"

# Package the six tools and checksums.
release: build
	bash scripts/make_release.sh --tools "$(BUILD_DIR)/tools" --out "$(DIST_DIR)"

# Smoke-test extracted binaries.
smoke: release
	@rm -rf $(DIST_DIR)/_smoke && mkdir -p $(DIST_DIR)/_smoke
	@TARBALL=$$(ls $(DIST_DIR)/neutrino-translator-*.tar.gz | head -1); tar -C $(DIST_DIR)/_smoke -xzf $$TARBALL
	@BINDIR=$$(dirname $$(find $(DIST_DIR)/_smoke -name neutrino-gen -type f | head -1)); \
	  NEUTRINO_TOOLS_DIR=$$BINDIR bash scripts/smoke_test.sh

clean-artifacts:
	rm -rf $(ARTIFACT_DIR) $(DIST_DIR)

clean-build:
	rm -rf $(BUILD_DIR) out-asan out-ubsan out-asan-ubsan out-cov

clean: clean-artifacts clean-build
