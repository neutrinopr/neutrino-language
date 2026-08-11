//===- PostgresSchemaIdiomRecipes.td - PG schema recipe layer -------------===//
//
// The declarative recipe layer for the PostgreSQL coordination SCHEMA DDL. Each
// rail's exact-key recipe emits the COMPLETE schema — the base coordination
// tables AND the rail's quorum/temporal tables — as one ordered `PgSchemaRoot`
// of `PgSchemaSegment`s the provider concatenates.  B2 folded the base
// tables + the schema-vs-quorum splice (previously handwritten `RawSql operator+`
// in lib/targets/PostgresTarget.cpp) into these roots, so `materializePostgres
// Schema` returns the whole artifact and no handwritten section ordering remains.
//
// Each segment's exact SQL bytes come from a package-local roled provider helper
// (the coordination tables via the existing typed `PgSchemaDecl` factories, the
//  coordination-envelope leaf via its seam, fixed banners/preflights via the
// raw-text funnel). The postings base table's memo variant is a FINALIZED FACT:
// the recipe switches it on the `PostingsMemo`/`PostingsPlain` marker whose
// presence the provider reads from the verified sequence (no plan read, no
// backend Boolean). A stackable fragment `include`d by the package root.
//
//===----------------------------------------------------------------------===//

// ---- finalized memo marker (presence read from the verified sequence) -------

def FinalizedSchemaPostingsMemo : FinalizedType<"FinalizedSchemaPostingsMemo">;
def FinalizedSchemaPostingsPlain : FinalizedType<"FinalizedSchemaPostingsPlain">;

// ---- schema segment nodes (each builder -> one RawSql segment) --------------

// The coordination-envelope SQL — an exact-body security leaf whose bytes must not
// be declarativized — composed verbatim through the package-local schema
// resolver.
def PgSchemaEnvelopeNode : TargetNode<"PgSchemaEnvelope", "PgSchemaSegment", [],
                                      "schema-envelope", []>;

// A coordination table DDL rendered from the existing typed PgSchemaDecl factory
// named by the selector.
def PgSchemaObserverTableNode
    : TargetNode<"PgSchemaObserverTable", "PgSchemaSegment", [], "schema-render", ["authorizedObserverTable"]>;
def PgSchemaTemporalQuorumTableNode
    : TargetNode<"PgSchemaTemporalQuorumTable", "PgSchemaSegment", [],
                 "schema-render", ["temporalQuorumAcceptanceTable"]>;
def PgSchemaCommittedGroupTableNode
    : TargetNode<"PgSchemaCommittedGroupTable", "PgSchemaSegment", [],
                 "schema-render", ["committedGroupTable"]>;
def PgSchemaKeyClaimTableNode
    : TargetNode<"PgSchemaKeyClaimTable", "PgSchemaSegment", [], "schema-render", ["keyClaimTable"]>;
def PgSchemaQuorumTableNode
    : TargetNode<"PgSchemaQuorumTable", "PgSchemaSegment", [], "schema-render",
                 ["quorumAcceptanceTable"]>;

//  B2 base coordination tables (ledger_balance / posting_idempotency /
// postings[+memo] / coordination_status) — the same typed PgSchemaDecl factories
// the handwritten base composer rendered.
def PgSchemaLedgerBalanceTableNode
    : TargetNode<"PgSchemaLedgerBalanceTable", "PgSchemaSegment", [],
                 "schema-render", ["ledgerBalanceTable"]>;
def PgSchemaPostingIdempotencyTableNode
    : TargetNode<"PgSchemaPostingIdempotencyTable", "PgSchemaSegment", [],
                 "schema-render", ["postingIdempotencyTable"]>;
def PgSchemaPostingsTableNode
    : TargetNode<"PgSchemaPostingsTable", "PgSchemaSegment", [],
                 "schema-render", ["postingsTable"]>;
def PgSchemaPostingsWithMemoTableNode
    : TargetNode<"PgSchemaPostingsWithMemoTable", "PgSchemaSegment", [],
                 "schema-render", ["postingsWithMemoTable"]>;
def PgSchemaCoordinationStatusTableNode
    : TargetNode<"PgSchemaCoordinationStatusTable", "PgSchemaSegment", [],
                 "schema-render", ["coordinationStatusTable"]>;

// A  temporal shape preflight for the table named by the selector.
def PgSchemaTemporalPreflightQuorumNode
    : TargetNode<"PgSchemaTemporalPreflightQuorum", "PgSchemaSegment", [],
                 "schema-render", ["quorumAcceptanceTemporalPreflight"]>;
def PgSchemaTemporalPreflightCommittedNode
    : TargetNode<"PgSchemaTemporalPreflightCommitted", "PgSchemaSegment", [],
                 "schema-render", ["committedGroupPreflight"]>;
def PgSchemaTemporalPreflightKeyClaimNode
    : TargetNode<"PgSchemaTemporalPreflightKeyClaim", "PgSchemaSegment", [],
                 "schema-render", ["keyClaimPreflight"]>;

// The  base upgrade preflight for the table named by the selector.
def PgSchemaUpgradePreflightQuorumNode
    : TargetNode<"PgSchemaUpgradePreflightQuorum", "PgSchemaSegment", [],
                 "schema-render", ["quorumAcceptanceUpgradePreflight"]>;

// Fixed raw-text segments (banners + separators + the coordination_status
// preflight); the exact bytes are owned by the raw-text funnel.
def PgSchemaNewlineNode : TargetNode<"PgSchemaNewline", "PgSchemaSegment", [],
                                     "schema-raw", ["\n"]>;
def PgSchemaDoubleNewlineNode
    : TargetNode<"PgSchemaDoubleNewline", "PgSchemaSegment", [], "schema-raw", ["\n\n"]>;
def PgSchemaSingleQuorumBannerNode
    : TargetNode<"PgSchemaSingleQuorumBanner", "PgSchemaSegment", [],
                 "schema-raw", ["\n-- Oracle S2d (): M-of-N quorum acceptance guard. The observer set (N, members)\n-- is seeded at deploy (like the Solidity guard's constructor args); the threshold M is\n-- spec-portable and rendered into accept_<proc>. Signature recovery is off-chain (S4).\n"]>;
def PgSchemaBaseBannerNode
    : TargetNode<"PgSchemaBaseBanner", "PgSchemaSegment", [], "schema-raw",
                 ["-- Generated by the Neutrino Translator. Coordination tables (not source of truth).\n"]>;
def PgSchemaEvidenceBannerNode
    : TargetNode<"PgSchemaEvidenceBanner", "PgSchemaSegment", [], "schema-raw",
                 ["-- Generated by the Neutrino Translator. Evidence-only coordination (no ledger; not source of truth).\n-- Records accepted attested evidence by instance key; `reconciled` marks the accepted terminal.\n"]>;
def PgSchemaLifecycleBannerNode
    : TargetNode<"PgSchemaLifecycleBanner", "PgSchemaSegment", [], "schema-raw",
                 ["\n-- Coordination lifecycle (): attest -> execute -> reconciled, per workflow key.\n"]>;
def PgSchemaCoordinationStatusPreflightNode
    : TargetNode<"PgSchemaCoordinationStatusPreflight", "PgSchemaSegment", [],
                 "schema-raw", ["-- Upgrade preflight (): refuse a pre-(procedure, key) `coordination_status` rather than\n-- silently no-op and fail inside accept_/execute_. Drop the coordination tables and\n-- redeploy (they are not source of truth), or migrate each row to its procedure.\nDO $$ BEGIN\n  IF to_regclass('coordination_status') IS NOT NULL AND NOT EXISTS (\n       SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()\n         AND table_name = 'coordination_status' AND column_name = 'procedure') THEN\n    RAISE EXCEPTION 'coordination_status predates the (procedure, key) coordination identity (); drop the coordination tables and redeploy, or migrate each row to its procedure';\n  END IF;\nEND $$;\n"]>;

// The schema root -> concatenates its ordered segments into the RawSql artifact.
def PgSchemaRootNode : TargetNode<"PgSchemaRoot", "PgSchema", [
  TargetField<"segments", "nodes", "PgSchemaSegment", "many", 1, "unbounded">
], "schema-root", []>;

// ---- the full base coordination-table sequence (shared by the effectful /
// temporal rails). `prefix` disambiguates the memo marker slots (the generator
// emits global slot ids per name). ------------------------------------------
class PgFullBaseSchemaRecipe<string recipeId, string finalizedKind, string mode,
                             string prefix, list<RecipeOp> tail>
  : TargetIdiomRecipe<recipeId, "postgres", finalizedKind, mode, "Schema", [
      Optional<!strconcat(prefix, "PostingsMemo"), "FinalizedSchemaPostingsMemo">,
      Optional<!strconcat(prefix, "PostingsPlain"), "FinalizedSchemaPostingsPlain">
    ],
    "PgSchema", CardinalityOne,
    Sequence<[
      Emit<"PgSchemaRoot", [
        Nested<"segments", Sequence<!listconcat([
          Emit<"PgSchemaBaseBanner", []>,
          Emit<"PgSchemaLedgerBalanceTable", []>,
          Emit<"PgSchemaNewline", []>,
          Emit<"PgSchemaPostingIdempotencyTable", []>,
          Emit<"PgSchemaNewline", []>,
          // The postings base table's memo column is a finalized fact — the
          // provider reports exactly one marker present per coordination.
          OptionalOp<!strconcat(prefix, "PostingsMemo"), Sequence<[
            Emit<"PgSchemaPostingsWithMemoTable", []>
          ]>>,
          OptionalOp<!strconcat(prefix, "PostingsPlain"), Sequence<[
            Emit<"PgSchemaPostingsTable", []>
          ]>>,
          Emit<"PgSchemaLifecycleBanner", []>,
          Emit<"PgSchemaCoordinationStatusPreflight", []>,
          Emit<"PgSchemaCoordinationStatusTable", []>
        ], tail)>>
      ]>
    ]>
  >;

// ---- recipes ---------------------------------------------------------------
//
// Each recipe spells its own complete ordered segment sequence inline: no shared
// cross-rail tail fragment is bound in the table, so the table carries no
// composition decision — the only rail selection is the exact idiom key each
// recipe is keyed on, resolved by the runtime.

// Temporal rail: full base coordination tables + the temporal per-policy tables
// (envelope + observer + temporal tables).
def PgTemporalSchemaRecipe
    : PgFullBaseSchemaRecipe<"postgres.temporal.schema.v1",
                             "QuorumAcceptance.PerPolicy", "Temporal", "tsch", [
      Emit<"PgSchemaEnvelope", []>,
      Emit<"PgSchemaNewline", []>,
      Emit<"PgSchemaObserverTable", []>,
      Emit<"PgSchemaNewline", []>,
      Emit<"PgSchemaTemporalPreflightQuorum", []>,
      Emit<"PgSchemaTemporalQuorumTable", []>,
      Emit<"PgSchemaNewline", []>,
      Emit<"PgSchemaTemporalPreflightCommitted", []>,
      Emit<"PgSchemaCommittedGroupTable", []>,
      Emit<"PgSchemaDoubleNewline", []>,
      Emit<"PgSchemaTemporalPreflightKeyClaim", []>,
      Emit<"PgSchemaKeyClaimTable", []>
    ]>;

// Effectful + reviewed quorum: full base + the single-quorum () tables
// (observer + quorum_acceptance).
def PgEffectfulQuorumSchemaRecipe
    : PgFullBaseSchemaRecipe<"postgres.effectful.quorum.schema.v1",
                             "QuorumAcceptance.Single", "Effectful", "eqsch", [
      Emit<"PgSchemaSingleQuorumBanner", []>,
      Emit<"PgSchemaObserverTable", []>,
      Emit<"PgSchemaNewline", []>,
      Emit<"PgSchemaUpgradePreflightQuorum", []>,
      Emit<"PgSchemaQuorumTable", []>
    ]>;

// Effectful, self-attested (no quorum): full base only.
def PgEffectfulSelfSchemaRecipe
    : PgFullBaseSchemaRecipe<"postgres.effectful.self.schema.v1",
                             "QuorumAcceptance.None", "Effectful", "essch", []>;

// Evidence-only rail: coordination_status-only base + the single-quorum ()
// tables (observer + quorum_acceptance).
def PgEvidenceSchemaRecipe : TargetIdiomRecipe<
  "postgres.evidence.schema.v1", "postgres",
  "QuorumAcceptance.Single", "Evidence", "Schema",
  [],
  "PgSchema", CardinalityOne,
  Sequence<[
    Emit<"PgSchemaRoot", [
      Nested<"segments", Sequence<[
        Emit<"PgSchemaEvidenceBanner", []>,
        Emit<"PgSchemaCoordinationStatusPreflight", []>,
        Emit<"PgSchemaCoordinationStatusTable", []>,
        Emit<"PgSchemaSingleQuorumBanner", []>,
        Emit<"PgSchemaObserverTable", []>,
        Emit<"PgSchemaNewline", []>,
        Emit<"PgSchemaUpgradePreflightQuorum", []>,
        Emit<"PgSchemaQuorumTable", []>
      ]>>
    ]>
  ]>
>;
