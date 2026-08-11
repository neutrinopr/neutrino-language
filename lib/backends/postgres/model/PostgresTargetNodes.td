//===- PostgresTargetNodes.td - typed PostgreSQL target-model node metadata =//
//
// The single source of truth for the PostgreSQL typed-target-model statement
// kinds and their node metadata (the PostgreSQL parallel of
// SolidityTargetNodes.td, ). It LABELS already-legalized node shapes — it
// does NOT read capability-spec fields, select workflow keys, or discover
// policy/balance/lifecycle semantics; that all stays in the
// CoordinationPlan->PostgresModel legalization boundary (the anti-inference
// boundary is authoritative).
//
// scripts/generators/gen_target_node_registry.py runs the pinned
// `llvm-tblgen --dump-json` over this file and emits the committed, deterministic
// X-macro registry PostgresTargetNodes.inc, which PostgresModel.h expands into
// the PgStmt::Kind enum, plus the generated-printer handler include
// PostgresPrinterHandlers.inc for the migrated (generated=1) node(s). The other
// kinds stay handwritten dispatch (generated=0) during the partial migration —
// they are registered here so the enum has a single source and the
// check_target_node_registry.py reconciliation is complete. Standalone `.td` (no
// MLIR/ODS include); the backend stays MLIR-free and leaf-only.
//
//===----------------------------------------------------------------------===//

include "TargetPrinter.td"

// Schema declarations are a distinct closed carrier. It intentionally has no
// production kinds until a matching handwritten table declaration is retired.
def PgSchemaDeclModel
    : TargetPrinterModel<"postgres", "PgSchemaDecl", "PG", 0>;
def PgStmtModel : TargetPrinterModel<"postgres", "PgStmt", "PG", 1>;

//  G1-S1: the PostgreSQL coordination_status spelling IDIOM, keyed by the
// projected (ExecutionMode, LifecycleRole). The `Success` role maps to the
// `reconciled` column atom in every mode; the effectful self-attest checkpoint
// (`AcceptedOrAttested`) maps to `attested`. Atoms only — the legalizer builds
// the surrounding SQL (`AND ` + atom, or the statusWrite column) and consumes
// the projected (mode, role) from the verified projection; the table maps that
// pair to an atom, never selecting a role. (Postgres has no pre-success `None`
// atom — it gates on predicates — so it declares no `Initial` row.)
def : LifecycleAtom<"Evidence", "Success", "reconciled">;
def : LifecycleAtom<"Effectful", "Success", "reconciled">;
def : LifecycleAtom<"Effectful", "AcceptedOrAttested", "attested">;
def : LifecycleAtom<"Temporal", "Success", "reconciled">;

class PgSchemaNode<int ord, string handler, bit leaf, string feature,
                   string layout = "", string syntax = "",
                   list<PrinterField> fields = [], bit generated = 0,
                   string closeSyntax = "", string listField = "",
                   string listInner = "", string listOuter = "",
                   list<EnumField> enumFields = [],
                   string itemSyntax = "",
                   list<PrinterField> itemFields = [],
                   string emptyItemSyntax = "">
    : TargetPrinterNode<"postgres", "PgSchemaDecl", ord, handler, leaf,
                        feature, layout, syntax, fields, generated,
                        closeSyntax, "PG", listField, listInner, listOuter,
                        enumFields, itemSyntax, itemFields, emptyItemSyntax>;

// One typed target-model statement kind. `Ordinal` fixes the enum's integer
// identity (kept identical to the pre-migration hand-written enum, so the
// PostgreSQL byte-goldens are unchanged). `generated=1` means the kind is
// emitted by the shared generated printer driver; `generated=0` (the default)
// means it stays a handwritten dispatch case during the partial  migration
// and carries no printer syntax/layout here.
class PgNode<int ord, string handler, bit leaf, string feature,
             string layout = "", string syntax = "",
             list<PrinterField> fields = [], bit generated = 0,
             string closeSyntax = "", string listField = "",
             string listInner = "", string listOuter = "",
             list<EnumField> enumFields = [],
             string itemSyntax = "",
             list<PrinterField> itemFields = [],
             string emptyItemSyntax = "">
    : TargetPrinterNode<"postgres", "PgStmt", ord, handler, leaf, feature,
                        layout, syntax, fields, generated, closeSyntax, "PG",
                        listField, listInner, listOuter, enumFields,
                        itemSyntax, itemFields, emptyItemSyntax>;

// : shared by the single-policy and temporal quorum schema paths. This is
// a fixed target DDL shape: policy, replay, and state-selection decisions stay
// in the schema materializers; the node owns only exact syntax.
def AuthorizedObserverTable
    : PgSchemaNode<0, "authorized-observer-table", /*leaf=*/1,
                   "attestation-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS authorized_observer (\n    observer_set text NOT NULL,\n    observer_id  text NOT NULL,\n    PRIMARY KEY (observer_set, observer_id)\n);",
                   [], /*generated=*/1>;

// : shared by the effectful and evidence-only coordination schema paths.
// C++ retains rail selection and upgrade-preflight ordering; this node owns
// only the byte-identical fixed table syntax selected by both paths.
def CoordinationStatusTable
    : PgSchemaNode<1, "coordination-status-table", /*leaf=*/1,
                   "coordination-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS coordination_status (\n    procedure       text    NOT NULL,\n    idempotency_key text    NOT NULL,\n    attested        boolean NOT NULL DEFAULT false,\n    reconciled      boolean NOT NULL DEFAULT false,\n    PRIMARY KEY (procedure, idempotency_key)\n);",
                   [], /*generated=*/1>;

// The effectful schema selects this fixed ledger table before its replay and
// postings tables; the node owns only the byte-stable declaration syntax.
def LedgerBalanceTable
    : PgSchemaNode<2, "ledger-balance-table", /*leaf=*/1,
                   "effectful-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS ledger_balance (\n    ledger     text   NOT NULL,\n    party      text   NOT NULL,\n    currency   text   NOT NULL,\n    balance    bigint NOT NULL DEFAULT 0,\n    PRIMARY KEY (ledger, party, currency)\n);",
                   [], /*generated=*/1>;

// The effectful schema selects this fixed replay table between the ledger and
// postings tables; the node owns only the byte-stable declaration syntax.
def PostingIdempotencyTable
    : PgSchemaNode<3, "posting-idempotency-table", /*leaf=*/1,
                   "effectful-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS posting_idempotency (\n    idempotency_key text NOT NULL,\n    entry           text NOT NULL,\n    PRIMARY KEY (idempotency_key, entry)\n);",
                   [], /*generated=*/1>;

// The temporal schema selects this fixed commit-ledger table after quorum
// acceptance and before key claims; the node owns only its exact DDL syntax.
def CommittedGroupTable
    : PgSchemaNode<4, "committed-group-table", /*leaf=*/1,
                   "temporal-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS committed_group (\n    procedure       text        NOT NULL,\n    idempotency_key text        NOT NULL,\n    group_ordinal   int         NOT NULL,\n    committed_at    timestamptz NOT NULL DEFAULT now(),\n    PRIMARY KEY (procedure, idempotency_key, group_ordinal)\n);",
                   [], /*generated=*/1>;

// The effectful postings ledger table. The memo column is present ONLY when
// some effect declares a memo — a legalization decision that selects
// postingsWithMemoTable() vs postingsTable() in C++; the memo flag never enters
// the `.td`. Each is a fixed, byte-stable DDL shape ending through `);`; the
// trailing blank line before the lifecycle comment stays C++-owned. The two
// records are distinct schema kinds, NOT a discriminated one.
def PostingsTable
    : PgSchemaNode<5, "postings-table", /*leaf=*/1,
                   "effectful-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS postings (\n    id             bigserial PRIMARY KEY,\n    procedure      text   NOT NULL,\n    entry          text   NOT NULL,\n    ledger         text   NOT NULL,\n    party          text   NOT NULL,\n    amount         bigint NOT NULL,\n    currency       text   NOT NULL,\n    signed_amount  bigint NOT NULL,\n    idempotency_key text  NOT NULL\n);",
                   [], /*generated=*/1>;
def PostingsWithMemoTable
    : PgSchemaNode<6, "postings-with-memo-table", /*leaf=*/1,
                   "effectful-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS postings (\n    id             bigserial PRIMARY KEY,\n    procedure      text   NOT NULL,\n    entry          text   NOT NULL,\n    ledger         text   NOT NULL,\n    party          text   NOT NULL,\n    amount         bigint NOT NULL,\n    currency       text   NOT NULL,\n    signed_amount  bigint NOT NULL,\n    idempotency_key text  NOT NULL,\n    memo           text\n);",
                   [], /*generated=*/1>;

// The temporal schema selects this fixed claim-binding table after the preflight
// and commit-ledger tables; the node owns only its exact DDL syntax (the C++
// retains the temporal-shape preflight and declaration ordering).
def KeyClaimTable
    : PgSchemaNode<7, "key-claim-table", /*leaf=*/1,
                   "temporal-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS key_claim (\n    procedure       text        NOT NULL,\n    idempotency_key text        NOT NULL,\n    execution_claim text        NOT NULL,\n    bound_at        timestamptz NOT NULL DEFAULT now(),\n    PRIMARY KEY (procedure, idempotency_key)\n);",
                   [], /*generated=*/1>;

// The single-policy quorum schema selects this fixed acceptance table after its
// preflight; the node owns only the exact DDL shape (the C++ retains the
// single/quorum path decision, the upgrade preflight and declaration ordering).
// Distinct from the temporal quorum_acceptance shape, which carries the extra
// policy/execution_claim columns.
def QuorumAcceptanceTable
    : PgSchemaNode<8, "quorum-acceptance-table", /*leaf=*/1,
                   "quorum-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS quorum_acceptance (\n    procedure            text        NOT NULL,\n    claim_id             text        NOT NULL,\n    canonical_claim_hash text        NOT NULL,\n    observer_count       int         NOT NULL,\n    accepted_at          timestamptz NOT NULL DEFAULT now(),\n    PRIMARY KEY (procedure, claim_id)\n);",
                   [], /*generated=*/1>;

// The temporal per-policy quorum schema selects this fixed acceptance table
// after its temporal-shape preflight; the node owns only the exact DDL shape
// (the C++ retains the temporal path decision, the preflight and declaration
// ordering). Distinct from the single-policy quorum_acceptance shape: it carries
// the extra policy/execution_claim columns and the per-policy primary key.
def TemporalQuorumAcceptanceTable
    : PgSchemaNode<9, "temporal-quorum-acceptance-table", /*leaf=*/1,
                   "temporal-schema", "lines",
                   "CREATE TABLE IF NOT EXISTS quorum_acceptance (\n    procedure            text        NOT NULL,\n    claim_id             text        NOT NULL,\n    policy               text        NOT NULL,\n    canonical_claim_hash text        NOT NULL,\n    execution_claim      text        NOT NULL,\n    observer_count       int         NOT NULL,\n    accepted_at          timestamptz NOT NULL DEFAULT now(),\n    PRIMARY KEY (procedure, claim_id, policy)\n);",
                   [], /*generated=*/1>;

//  B3: the  temporal-shape +  upgrade preflights as typed
// zero-field schema nodes (byte-exact DO $$ text owned in .td, generated
// printer); the recipe composes them, replacing the handwritten composers.
def QuorumAcceptanceTemporalPreflight
    : PgSchemaNode<10, "quorum-acceptance-temporal-preflight", /*leaf=*/1,
                   "temporal-schema", "lines",
                   "-- Temporal upgrade preflight (): the per-policy `quorum_acceptance` shape differs from the\n-- single-shot one; refuse a pre-existing table that lacks the full column set or the\n-- (procedure, claim_id, policy)-style primary key (a `CREATE TABLE IF NOT EXISTS` would silently\n-- no-op and fail later inside accept_/execute_). Drop the coordination tables and redeploy,\n-- or migrate the table to the temporal shape.\nDO $$\nDECLARE\n  v_missing text;\n  v_pk text[];\nBEGIN\n  IF to_regclass('quorum_acceptance') IS NOT NULL THEN\n    SELECT string_agg(c, ', ') INTO v_missing FROM unnest(ARRAY['procedure', 'claim_id', 'policy', 'canonical_claim_hash', 'execution_claim', 'observer_count']) c\n      WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns\n        WHERE table_schema = current_schema() AND table_name = 'quorum_acceptance' AND column_name = c);\n    IF v_missing IS NOT NULL THEN\n      RAISE EXCEPTION 'quorum_acceptance predates the  temporal per-policy shape (missing column(s): %); drop the coordination tables and redeploy, or migrate to the temporal shape', v_missing;\n    END IF;\n    SELECT coalesce(array_agg(a.attname ORDER BY a.attname), ARRAY[]::text[]) INTO v_pk\n      FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)\n      WHERE i.indrelid = to_regclass('quorum_acceptance') AND i.indisprimary;\n    IF v_pk <> ARRAY['claim_id', 'policy', 'procedure']::text[] THEN\n      RAISE EXCEPTION 'quorum_acceptance predates the  temporal per-policy shape (primary key is %, needs (procedure, claim_id, policy)); drop the coordination tables and redeploy, or migrate to the temporal shape', v_pk;\n    END IF;\n  END IF;\nEND $$;",
                   [], /*generated=*/1>;
def CommittedGroupPreflight
    : PgSchemaNode<11, "committed-group-preflight", /*leaf=*/1,
                   "temporal-schema", "lines",
                   "-- Temporal upgrade preflight (): the per-policy `committed_group` shape differs from the\n-- single-shot one; refuse a pre-existing table that lacks the full column set or the\n-- (procedure, claim_id, policy)-style primary key (a `CREATE TABLE IF NOT EXISTS` would silently\n-- no-op and fail later inside accept_/execute_). Drop the coordination tables and redeploy,\n-- or migrate the table to the temporal shape.\nDO $$\nDECLARE\n  v_missing text;\n  v_pk text[];\nBEGIN\n  IF to_regclass('committed_group') IS NOT NULL THEN\n    SELECT string_agg(c, ', ') INTO v_missing FROM unnest(ARRAY['procedure', 'idempotency_key', 'group_ordinal']) c\n      WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns\n        WHERE table_schema = current_schema() AND table_name = 'committed_group' AND column_name = c);\n    IF v_missing IS NOT NULL THEN\n      RAISE EXCEPTION 'committed_group predates the  temporal per-policy shape (missing column(s): %); drop the coordination tables and redeploy, or migrate to the temporal shape', v_missing;\n    END IF;\n    SELECT coalesce(array_agg(a.attname ORDER BY a.attname), ARRAY[]::text[]) INTO v_pk\n      FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)\n      WHERE i.indrelid = to_regclass('committed_group') AND i.indisprimary;\n    IF v_pk <> ARRAY['group_ordinal', 'idempotency_key', 'procedure']::text[] THEN\n      RAISE EXCEPTION 'committed_group predates the  temporal per-policy shape (primary key is %, needs (procedure, idempotency_key, group_ordinal)); drop the coordination tables and redeploy, or migrate to the temporal shape', v_pk;\n    END IF;\n  END IF;\nEND $$;",
                   [], /*generated=*/1>;
def KeyClaimPreflight
    : PgSchemaNode<12, "key-claim-preflight", /*leaf=*/1,
                   "temporal-schema", "lines",
                   "-- Temporal upgrade preflight (): the per-policy `key_claim` shape differs from the\n-- single-shot one; refuse a pre-existing table that lacks the full column set or the\n-- (procedure, claim_id, policy)-style primary key (a `CREATE TABLE IF NOT EXISTS` would silently\n-- no-op and fail later inside accept_/execute_). Drop the coordination tables and redeploy,\n-- or migrate the table to the temporal shape.\nDO $$\nDECLARE\n  v_missing text;\n  v_pk text[];\nBEGIN\n  IF to_regclass('key_claim') IS NOT NULL THEN\n    SELECT string_agg(c, ', ') INTO v_missing FROM unnest(ARRAY['procedure', 'idempotency_key', 'execution_claim']) c\n      WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns\n        WHERE table_schema = current_schema() AND table_name = 'key_claim' AND column_name = c);\n    IF v_missing IS NOT NULL THEN\n      RAISE EXCEPTION 'key_claim predates the  temporal per-policy shape (missing column(s): %); drop the coordination tables and redeploy, or migrate to the temporal shape', v_missing;\n    END IF;\n    SELECT coalesce(array_agg(a.attname ORDER BY a.attname), ARRAY[]::text[]) INTO v_pk\n      FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)\n      WHERE i.indrelid = to_regclass('key_claim') AND i.indisprimary;\n    IF v_pk <> ARRAY['idempotency_key', 'procedure']::text[] THEN\n      RAISE EXCEPTION 'key_claim predates the  temporal per-policy shape (primary key is %, needs (procedure, idempotency_key)); drop the coordination tables and redeploy, or migrate to the temporal shape', v_pk;\n    END IF;\n  END IF;\nEND $$;",
                   [], /*generated=*/1>;
def QuorumAcceptanceUpgradePreflight
    : PgSchemaNode<13, "quorum-acceptance-upgrade-preflight", /*leaf=*/1,
                   "quorum-schema", "lines",
                   "-- Upgrade preflight (): refuse a pre-(procedure, key) `quorum_acceptance` rather than\n-- silently no-op and fail inside accept_/execute_. Drop the coordination tables and\n-- redeploy (they are not source of truth), or migrate each row to its procedure.\nDO $$ BEGIN\n  IF to_regclass('quorum_acceptance') IS NOT NULL AND NOT EXISTS (\n       SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()\n         AND table_name = 'quorum_acceptance' AND column_name = 'procedure') THEN\n    RAISE EXCEPTION 'quorum_acceptance predates the (procedure, key) coordination identity (); drop the coordination tables and redeploy, or migrate each row to its procedure';\n  END IF;\nEND $$;",
                   [], /*generated=*/1>;

// The migrated node projects the model operand at ordinal 0 into `${value}`.
def FValue : PrinterField<"value", 0>;

// The posting-idempotency INSERT projects its two model operands: the workflow
// key at ordinal 0 into `${key}` and the entry name at ordinal 1 into `${entry}`.
def FKey   : PrinterField<"key",   0>;
def FEntry : PrinterField<"entry", 1>;

// The key-claim INSERT projects its two model operands: the procedure at ordinal
// 0 into `${proc}` and the idempotency key at ordinal 1 into `${key}`. (The
// existing FKey binds `key` at ordinal 0, so this node needs distinct field defs.)
def FKcProc : PrinterField<"proc", 0>;
def FKcKey  : PrinterField<"key",  1>;

// The committed-group INSERT reuses the proc/key operands (ordinals 0/1) and
// adds the group ordinal at ordinal 2 into `${ordinal}`.
def FCgOrdinal : PrinterField<"ordinal", 2>;

// The temporal-accept policy CASE item projects each per-policy tuple: the
// policy input at tuple index 0 into `${input}`, the observer set at index 1
// into `${observerSet}`, and the quorum threshold M at index 2 into
// `${quorum}`. (Item fields index the repeated group tuple, NOT scalar
// operands.)
def FPolInput       : PrinterField<"input",       0>;
def FPolObserverSet : PrinterField<"observerSet", 1>;
def FPolQuorum      : PrinterField<"quorum",      2>;

// The per-effect ledger comment header projects four dense model operands: the
// leg kind at ordinal 0 into `${kind}`, the effect name at ordinal 1 into
// `${name}`, the ledger at ordinal 2 into `${ledger}`, and the ALREADY-DECIDED
// guard clause at ordinal 3 into `${suffix}`. The suffix's presence/content is a
// legalization decision (empty, or " when <guardSql>"), computed upstream and
// carried verbatim — the node never branches on it.
def FEffKind   : PrinterField<"kind",   0>;
def FEffName   : PrinterField<"name",   1>;
def FEffLedger : PrinterField<"ledger", 2>;
def FEffSuffix : PrinterField<"suffix", 3>;

// The not-yet-migrated handwritten kinds (generated=0): registered so the enum
// has a single source and the registry reconciliation is complete; their
// per-shape SQL stays in exact target-node renderer adapters selected by
// generated typed-node traversal (SqlEmitter framing). They are not recipe
// leaf hooks.
def Line          : PgNode<0, "line",           /*leaf=*/1, "framing">;
// : the empty-line separator — a fieldless `blank` layout node (no syntax,
// no operands). Retires the `pgtext::renderBlank` render adapter; the generated
// printer emits the empty line directly.
def Blank : PgNode<1, "blank", /*leaf=*/1, "framing", "blank", "", [],
                   /*generated=*/1>;
// : the `RAISE EXCEPTION '<msg>'[, <arg>];` diagnostic — a FIXED single-line
// shape owned here via the generic `line` layout. `${msg}` is a fixed diagnostic
// literal or an already-lowered/escaped message (negativeMessage); `${arg}` is an
// already-lowered identifier. The no-arg and with-arg forms are byte-distinct
// (the trailing `, <arg>` changes the line), so they are TWO kinds. Retires the
// handwritten `pgtext::raise` / `pgtext::renderRaise` render composers.
def FRaiseMsg : PrinterField<"msg", 0>;
def FRaiseArg : PrinterField<"arg", 1>;
def Raise : PgNode<2, "raise", /*leaf=*/1, "revert",
                   "line", "RAISE EXCEPTION '${msg}';", [FRaiseMsg],
                   /*generated=*/1>;
def RaiseArg : PgNode<26, "raise-arg", /*leaf=*/1, "revert",
                      "line", "RAISE EXCEPTION '${msg}', ${arg};",
                      [FRaiseMsg, FRaiseArg], /*generated=*/1>;
// : the PL/pgSQL `<var> := <expr>;` assignment — a FIXED single-line shape
// owned here via the generic `line` layout (the generalization of the already
// migrated `ProgressFlag` node). Both `${var}` and `${expr}` are already-lowered
// operands; which line exists is fixed. Retires the handwritten `pgtext::assign`
// render composer (the last raw-Line author for assignments).
def FAssignVar  : PrinterField<"var",  0>;
def FAssignExpr : PrinterField<"expr", 1>;
def Assign : PgNode<3, "assign", /*leaf=*/1, "compute",
                    "line", "${var} := ${expr};", [FAssignVar, FAssignExpr],
                    /*generated=*/1>;

//  family-1: the indented `IF <cond> THEN … END IF;` guard container — the
// real block nesting structure, NOT a flat reinterpreted string. A `block`
// layout owns the whole frame topology: the lowered predicate projects into
// `${cond}`, and the then-branch statements are the node's CHILDREN (walked +
// rendered recursively by the generated typed-node traversal, never
// reconstructed), which the generated printer nests one level between the
// `IF … THEN` open and the `END IF;` close. C++ supplies only the predicate +
// the typed children — the frame is TableGen-owned. Retires the handwritten
// `ct::block("IF " + cond + " THEN", "END IF;", …)` framing from the sql::
// emitter.
def FCond : PrinterField<"cond", 0>;
def If : PgNode<4, "if", /*leaf=*/0, "condition",
                "block", /*syntax=*/"IF ${cond} THEN", [FCond], /*generated=*/1,
                /*closeSyntax=*/"END IF;">;

//  family-1 (flat): the  conditional-effect guard — the SAME
// `IF <cond> THEN … END IF;` framing as `If`, but its then-branch legs stay at
// the guard's OWN indent (flat siblings), not nested one level. The only
// difference from `If` is the `flat-block` layout: it frames the typed CHILDREN
// with the same open/close but adds no indent to them (a nested `If` block
// among the legs still self-indents). Reuses the same `${cond}` predicate
// (operand 0); the generated traversal renders the complete carrier without
// another adapter or authority. Retires the handwritten `case Stmt::Kind::FlatIf:`
// (hand-pushed `IF … THEN` + flat legs + `END IF;`) from the sql:: emitter.
def FlatIf : PgNode<5, "flat-if", /*leaf=*/0, "condition",
                    "flat-block", /*syntax=*/"IF ${cond} THEN", [FCond],
                    /*generated=*/1, /*closeSyntax=*/"END IF;">;
// : the coordination_status lifecycle write — a FIXED two-line INSERT +
// ON CONFLICT owned here as ONE closed literal idiom via the generic `lines`
// layout. The `${field}` status column, `${proc}` procedure literal, and
// `${pkey}` idempotency key are already-lowered operands; which lines exist is
// fixed. The DO-NOTHING and DO-UPDATE tails are byte-distinct fixed shapes, so
// they are TWO kinds (NOT a doUpdate Boolean on the render path): the evidence
// rail selects StatusWrite (DO NOTHING); the effectful/temporal rails select
// StatusWriteUpdate (DO UPDATE SET). Retires the handwritten `pgtext::statusWrite`
// render composer.
def FSwProc  : PrinterField<"proc",  0>;
def FSwKey   : PrinterField<"pkey",  1>;
def FSwField : PrinterField<"field", 2>;
def StatusWrite : PgNode<6, "status-write", /*leaf=*/1, "status-transition",
                  "lines",
                  "INSERT INTO coordination_status(procedure, idempotency_key, ${field}) VALUES (${proc}, ${pkey}, true)\nON CONFLICT (procedure, idempotency_key) DO NOTHING;",
                  [FSwProc, FSwKey, FSwField], /*generated=*/1>;
def StatusWriteUpdate : PgNode<25, "status-write-update", /*leaf=*/1, "status-transition",
                        "lines",
                        "INSERT INTO coordination_status(procedure, idempotency_key, ${field}) VALUES (${proc}, ${pkey}, true)\nON CONFLICT (procedure, idempotency_key) DO UPDATE SET ${field} = true;",
                        [FSwProc, FSwKey, FSwField], /*generated=*/1>;
// : the per-effect ledger-balance upsert (4 fixed lines) via the generic
// `lines` layout. `${ledger}` is the string.escape-hook-escaped ledger (recipe
// binds it via Hook); party/currency/signedAmount are already-lowered operands.
// `${balanceColumn}` is a fixed target-shape atom injected by the sealed
// generated factory: it is not caller- or projection-selectable. This keeps the
// table free of assignment-bearing balance authority while the finalized
// signedAmount value remains the sole accumulation input. Retires the
// handwritten `pgtext::ledgerUpsert` render composer.
def FLuLedger : PrinterField<"ledger", 0>;
def FLuParty : PrinterField<"party", 1>;
def FLuCurrency : PrinterField<"currency", 2>;
def FLuSigned : PrinterField<"signedAmount", 3>;
def FLuBalanceColumn : PrinterField<"balanceColumn", 4>;
def LedgerUpsert : PgNode<7, "ledger-upsert", /*leaf=*/1, "effect",
                   "lines",
                   "INSERT INTO ledger_balance(ledger, party, currency, balance)\nVALUES ('${ledger}', ${party}, ${currency}, ${signedAmount})\nON CONFLICT (ledger, party, currency)\nDO UPDATE SET ${balanceColumn} = ledger_balance.${balanceColumn} + (${signedAmount});",
                   [FLuLedger, FLuParty, FLuCurrency, FLuSigned,
                    FLuBalanceColumn],
                   /*generated=*/1>;
// : the per-effect postings INSERT (2 fixed lines). The memo column is
// present ONLY for a posting whose finalized FinalizedPostingMemo is Present —
// selected per-posting by the recipe OptionalOp, NOT a below-waist memo test —
// so it is TWO byte-distinct kinds (no-memo / with-memo). proc/entry/ledger/memo
// are string.escape-hook-escaped operands; party/amount/currency/signedAmount are
// already-lowered; `key` carries its `p_` prefix in the template. Retires the
// handwritten `pgtext::postingInsert` render composer.
def FPiProc : PrinterField<"proc", 0>;
def FPiEntry : PrinterField<"entry", 1>;
def FPiLedger : PrinterField<"ledger", 2>;
def FPiParty : PrinterField<"party", 3>;
def FPiAmount : PrinterField<"amount", 4>;
def FPiCurrency : PrinterField<"currency", 5>;
def FPiSigned : PrinterField<"signedAmount", 6>;
def FPiKey : PrinterField<"key", 7>;
def FPiMemo : PrinterField<"memo", 8>;
def PostingInsert : PgNode<8, "posting-insert", /*leaf=*/1, "effect",
                    "lines",
                    "INSERT INTO postings(procedure, entry, ledger, party, amount, currency, signed_amount, idempotency_key)\nVALUES ('${proc}', '${entry}', '${ledger}', ${party}, ${amount}, ${currency}, ${signedAmount}, p_${key});",
                    [FPiProc, FPiEntry, FPiLedger, FPiParty, FPiAmount,
                     FPiCurrency, FPiSigned, FPiKey], /*generated=*/1>;
def PostingInsertWithMemo : PgNode<27, "posting-insert-with-memo", /*leaf=*/1, "effect",
                            "lines",
                            "INSERT INTO postings(procedure, entry, ledger, party, amount, currency, signed_amount, idempotency_key, memo)\nVALUES ('${proc}', '${entry}', '${ledger}', ${party}, ${amount}, ${currency}, ${signedAmount}, p_${key}, '${memo}');",
                            [FPiProc, FPiEntry, FPiLedger, FPiParty, FPiAmount,
                             FPiCurrency, FPiSigned, FPiKey, FPiMemo],
                            /*generated=*/1>;
// : the temporal per-(key,group) progress-flag assign `v_progress := <bool>;`
// — a CLOSED value vocabulary {true,false}. The whole `v_progress := ;` framing
// is owned here (literal target syntax); `value` is the already-decided boolean
// literal. The FIRST PostgreSQL statement class migrated off the raw `pgLine`
// seam into the generated printer.
def ProgressFlag  : PgNode<9, "progress-flag",  /*leaf=*/1, "temporal-progress",
                           "line", "v_progress := ${value};", [FValue],
                           /*generated=*/1>;
// : the effectful replay-guard `posting_idempotency` INSERT — a FIXED
// three-line statement (header / VALUES / ON CONFLICT) owned here as ONE closed
// literal idiom via the generic `lines` layout. Only the `${key}`/`${entry}`
// VALUES are legalization-decided; which lines exist is fixed. Migrated off the
// three raw `pgLine` seam sites into the generated printer.
def PostingIdempotency : PgNode<10, "posting-idempotency", /*leaf=*/1, "effectful",
                          "lines",
                          "INSERT INTO posting_idempotency(idempotency_key, entry)\nVALUES (${key}, '${entry}')\nON CONFLICT DO NOTHING;",
                          [FKey, FEntry], /*generated=*/1>;
// : the temporal-claim `key_claim` INSERT — a FIXED two-line statement
// (header / VALUES) owned here as ONE closed literal idiom via the generic
// `lines` layout. Only the `${proc}`/`${key}` VALUES are legalization-decided;
// `v_claim` is a PL/pgSQL variable name (literal template text, not an operand)
// and which lines exist is fixed. Migrated off the two raw `pgLine` seam sites
// into the generated printer.
def KeyClaimInsert : PgNode<11, "key-claim-insert", /*leaf=*/1, "temporal-claim",
                     "lines",
                     "INSERT INTO key_claim(procedure, idempotency_key, execution_claim)\nVALUES (${proc}, ${key}, v_claim);",
                     [FKcProc, FKcKey], /*generated=*/1>;
// : the temporal-claim `committed_group` INSERT — a FIXED two-line statement
// (header / VALUES) owned here as ONE closed literal idiom via the generic
// `lines` layout. The `${proc}`/`${key}` VALUES reuse the key-claim operands;
// `${ordinal}` is the already-decided group ordinal. Which lines exist is fixed.
// Migrated off the two raw `pgLine` seam sites into the generated printer.
def CommittedGroupInsert : PgNode<12, "committed-group-insert", /*leaf=*/1, "temporal-claim",
                           "lines",
                           "INSERT INTO committed_group(procedure, idempotency_key, group_ordinal)\nVALUES (${proc}, ${key}, ${ordinal});",
                           [FKcProc, FKcKey, FCgOrdinal], /*generated=*/1>;
// : the quorum-accept `quorum_acceptance` INSERT — a FIXED two-line
// statement (header / VALUES) owned here as ONE closed literal idiom via the
// generic `lines` layout. Only the `${proc}`/`${key}` VALUES are
// legalization-decided; `p_canonical_claim_hash` and the nested
// `(SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id))` observer-count
// subquery are literal template text (not operands) and which lines exist is
// fixed. Migrated off the two raw `pgLine` seam sites into the generated printer.
def QuorumAcceptInsert : PgNode<13, "quorum-accept-insert", /*leaf=*/1, "quorum-accept",
                         "lines",
                         "INSERT INTO quorum_acceptance(procedure, claim_id, canonical_claim_hash, observer_count)\nVALUES (${proc}, ${key}, p_canonical_claim_hash, (SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id)));",
                         [FKcProc, FKcKey], /*generated=*/1>;
// : the temporal-accept `quorum_acceptance` INSERT — the temporal-rail
// sibling of QuorumAcceptInsert. A FIXED two-line statement (header / VALUES)
// owned here as ONE closed literal idiom via the generic `lines` layout. Only
// the `${proc}`/`${key}` VALUES are legalization-decided; `p_policy`,
// `p_canonical_claim_hash`, `p_execution_claim` and the nested
// `(SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id))` observer-count
// subquery are literal template text (not operands) and which lines exist is
// fixed. Migrated off the two raw `pgLine` seam sites into the generated printer.
def TemporalAcceptInsert : PgNode<14, "temporal-accept-insert", /*leaf=*/1, "quorum-accept",
                           "lines",
                           "INSERT INTO quorum_acceptance(procedure, claim_id, policy, canonical_claim_hash, execution_claim, observer_count)\nVALUES (${proc}, ${key}, p_policy, p_canonical_claim_hash, p_execution_claim, (SELECT count(DISTINCT o.id) FROM unnest(p_observers) o(id)));",
                           [FKcProc, FKcKey], /*generated=*/1>;
// : the idempotency-guard early-return `RETURN;  -- already processed; no
// double posting` — the replay-safe control-flow exit inside the effectful
// `NOT FOUND` guard. A 0-OPERAND CONSTANT node: a SINGLE fixed `line` with NO
// projected fields (empty `[]`), so its Syntax is pure literal target text with
// no `${...}` placeholders. Architect-approved as a credited typed control-flow
// node (not generic framing). Migrated off the raw `pgLine` seam site into the
// generated printer; the shared `line`/codetext::Line handler renders it.
def IdempotentReturn : PgNode<15, "idempotent-return", /*leaf=*/1, "control-flow",
                       "line", "RETURN;  -- already processed; no double posting",
                       [], /*generated=*/1>;
// : the evidence-only claim comment `-- Evidence-only: atomically CLAIM the
// accepted terminal; move NO ledger value.` — the fixed banner inside
// legalizeEvidence marking the atomic terminal claim that moves NO ledger value.
// A 0-OPERAND CONSTANT node: a SINGLE fixed `line` with NO projected fields
// (empty `[]`), so its Syntax is pure literal target text with no `${...}`
// placeholders. Migrated off the raw `pgLine` seam site into the generated
// printer; the shared `line`/codetext::Line handler renders it.
def EvidenceClaimComment : PgNode<16, "evidence-claim-comment", /*leaf=*/1, "evidence",
                           "line",
                           "-- Evidence-only: atomically CLAIM the accepted terminal; move NO ledger value.",
                           [], /*generated=*/1>;
// : the temporal-accept per-policy resolver `CASE p_policy … END CASE;` — a
// FIXED-FRAME block owned here as ONE closed literal idiom via the generic
// `framed-lines` layout: a fixed HEADER (`CASE p_policy`), one `WHEN` item line
// repeated ONCE PER declared attestation policy, and a fixed FOOTER (the
// `ELSE RAISE …` unknown-policy guard + `END CASE;`). WHICH item lines exist is
// model data (the per-policy tuple count); the item SHAPE and the header/footer
// are fixed literals. Only the per-policy `${input}`/`${observerSet}`/`${quorum}`
// tuple values are legalization-decided. Migrated off the FOUR raw pgLine seam
// sites (header / repeated WHEN / ELSE / END CASE) into the generated printer.
def PolicyCaseSelect : PgNode<17, "policy-case-select", /*leaf=*/1, "temporal-accept-gate",
                       "framed-lines",
                       /*header=*/"CASE p_policy",
                       /*fields=*/[], /*generated=*/1,
                       /*footer=*/"  ELSE RAISE EXCEPTION 'unknown attestation policy %', p_policy;\nEND CASE;",
                       /*listField=*/"", /*listInner=*/"", /*listOuter=*/"", /*enumFields=*/[],
                       /*itemSyntax=*/"  WHEN ${input} THEN v_set := ${observerSet}; v_m := ${quorum};",
                       /*itemFields=*/[FPolInput, FPolObserverSet, FPolQuorum]>;
//  (C1): the per-effect ledger comment header
// `-- <kind> <name> (<ledger>)[ when <guard>]` inside legalizeEffectful — the
// SOLE remaining EXECUTABLE raw pgLine site. A single projected `line` (NOT a
// framed group: each header is one placeholder-bearing line interleaved with its
// effect's typed legs, so it is not a contiguous item block, and framed-lines
// projects only in item lines with FIXED-literal header/footer). The fixed `-- `
// / ` (` / `)` shape is owned here; `${kind}`/`${name}`/`${ledger}` are dense
// operands and `${suffix}` is the already-decided guard clause (empty, or
// " when <guardSql>") — the node lays out the tuple and never selects on values.
// Migrated off the last raw executable pgLine seam site into the generated
// printer; banks the executable ratchet 1 -> 0.
def EffectLedgerComment : PgNode<18, "effect-ledger-comment", /*leaf=*/1, "effectful",
                          "line",
                          "-- ${kind} ${name} (${ledger})${suffix}",
                          [FEffKind, FEffName, FEffLedger, FEffSuffix],
                          /*generated=*/1>;
//  C2: the effectful replay/idempotency guard comment is a fixed banner at
// the legalization decision site. A 0-OPERAND CONSTANT node owns the complete
// single-line shape; no arbitrary comment text or semantic choice crosses the
// generated-printer boundary. The remaining balanced-invariant comment stays
// on the governed raw seam until the separate C3 closure slice.
def IdempotencyGuardComment
    : PgNode<19, "idempotency-guard-comment", /*leaf=*/1, "comment",
             "line",
             "-- idempotency guard (replay-safe): one row per workflow key",
             [], /*generated=*/1>;
//  C3: the balanced-workflow invariant banner is a fixed comment at the
// legalization decision site. A zero-operand constant node owns the complete
// line; no arbitrary text crosses the generated-printer boundary. This retires
// the final governed raw comment and permits the raw PgStmt seam to disappear.
def BalancedInvariantComment
    : PgNode<20, "balanced-invariant-comment", /*leaf=*/1, "comment",
             "line",
             "-- balanced invariant: this workflow key must net to zero",
             [], /*generated=*/1>;

// The callable name projects the model operand at ordinal 0 into `${name}`.
def FCallableName : PrinterField<"name", 0>;
//  slice 1 (T2-P2): the outer callable HEADER framing — the
// `CREATE OR REPLACE FUNCTION ${name}(${params})` signature plus the fixed
// void-return / plpgsql-language clauses and the body-open — owned
// here as ONE closed idiom via the generic `lines` layout. `${name}` is the sole
// scalar operand; `${params}` is the  §7 REPEATED-field (list) projection —
// each parameter is the space-join of its non-empty `[name, type]` tuple (so
// `p_amount bigint`), items joined by `, `. Both the per-parameter shape and the
// separator are TableGen-owned; legalization decides the p_-prefixed name + the
// lowered SQL type. RETURNS/LANGUAGE are fixed literal clauses (no SECURITY
// clause is emitted — the security posture is the post-hoc REVOKE trailer, not a
// SECURITY DEFINER clause). The matching `$$;` body-close is a SEPARATE
// callable identity (CallableClose) that stays handwritten until the follow-up
// endpoint slice. Retires the handwritten SqlEmitter addFunction header lines +
// the PgParam::render join.
def CallableSig : PgNode<21, "callable-sig", /*leaf=*/1, "callable",
                  "lines",
                  "CREATE OR REPLACE FUNCTION ${name}(${params})\nRETURNS void\nLANGUAGE plpgsql\nAS $$",
                  [FCallableName], /*generated=*/1,
                  /*closeSyntax=*/"", /*listField=*/"params",
                  /*listInner=*/" ", /*listOuter=*/", ">;

def FDeclareName : PrinterField<"name", 0>;
def FDeclareType : PrinterField<"type", 1, " ">;
def FDeclareInitializer : PrinterField<"initializer", 2, " := ">;
//  slice 2: C++ decides whether a DECLARE section exists and supplies one
// legalized [name, type, initializer] tuple per variable. This node owns the
// fixed header, indentation, separators, optional initializer introducer, and
// terminator. A DECLARE section has no closing token.
def DeclareSection
    : PgNode<22, "declare-section", /*leaf=*/1, "callable",
             "framed-lines", /*header=*/"DECLARE",
             /*fields=*/[], /*generated=*/1,
             /*footer=*/"", /*listField=*/"", /*listInner=*/"",
             /*listOuter=*/"", /*enumFields=*/[],
             /*itemSyntax=*/"    ${name}${type}${initializer};",
             /*itemFields=*/[FDeclareName, FDeclareType,
                             FDeclareInitializer],
             // : the node fully owns its EMPTY case — when there are no
             // computed values it renders `DECLARE` + this sentinel, so the
             // model no longer appends a raw comment string outside the node.
             /*emptyItemSyntax=*/"    -- (no computed values)">;

//  slice 3: the outer callable BODY block — the real `BEGIN … END;` nesting
// structure, NOT a flat reinterpreted string. A `block` layout owns the whole
// block frame topology: the already-typed body statements are the node's CHILDREN
// (the PostgreSQL model supplies them via sql::renderStatements and never
// reconstructs the frame), and the generated printer nests them one level with the
// printer's four-space indentation between the `BEGIN` open and the `END;` close.
// C++ supplies only the children — the frame order/nesting is TableGen-owned.
def CallableBody
    : PgNode<23, "callable-body", /*leaf=*/0, "callable",
             "block", /*syntax=*/"BEGIN", [], /*generated=*/1,
             /*closeSyntax=*/"END;">;
//  endpoint: the trailing `$$;` dollar-quote function-close — a fixed leaf
// `line` node placed after the CallableBody block at depth zero. codetext forbids
// a multi-line block delimiter, so `$$;` cannot fold into the block close; it is
// its own node. Migrating it retires the LAST handwritten callable identity, so
// the PostgreSQL callable inventory reaches ZERO.
def CallableClose
    : PgNode<24, "callable-close", /*leaf=*/1, "callable",
             "line", /*syntax=*/"$$;", [], /*generated=*/1>;

// : nodes whose CONSTRUCTION is extracted to generated recipe builders
// (the concrete PgStmt shape is generated from this schema, not handwritten).
// A marker only — it references an existing PgNode; the printer registry
// generator ignores this class. The first extracted vertical is CallableClose
// (a zero-field close terminator: no slots, hooks, or inputs).
class RecipeBuilderNode<PgNode node, string sectionRole = ""> {
  PgNode Node = node;
  string SectionRole = sectionRole;
}
def : RecipeBuilderNode<CallableClose, "Close">;
// : the evidence-only claim banner — a zero-field leaf whose construction is
// extracted to the generated builder so the handwritten factory can be retired.
def : RecipeBuilderNode<EvidenceClaimComment>;
//  common callable-section batch: construction of the signature,
// declaration, and body nodes is generated from their real scalar/list/body
// schema. The shared renderer consumes these builders; no rail recipe or
// materializer owns a parallel construction path.
def : RecipeBuilderNode<CallableSig, "Signature">;
def : RecipeBuilderNode<DeclareSection, "Declaration">;
def : RecipeBuilderNode<CallableBody, "BodyBlock">;

// Closed target-node renderer adapters. These are NOT recipe leaf hooks:
// every row names a complete typed PgStmt selected and ordered by a recipe (or
// an exact  body). The generator merely forwards the node's declared
// carrier fields to the syntax-only pgtext renderer; no statement is returned
// through the  RegisteredHookId ABI.
class RecipePrinterAdapterArg<string storage, int index = 0> {
  string Storage = storage;
  int Index = index;
}
class RecipePrinterAdapterNode<PgNode node, string adapter,
                               list<RecipePrinterAdapterArg> args> {
  PgNode Node = node;
  string Adapter = adapter;
  list<RecipePrinterAdapterArg> Args = args;
}

//  B1: schema for the public typed factory entries that remain callable
// while  owns PostgresModel.cpp. `Storage` names the exact closed PgStmt
// carrier slot; generation validates the type/slot pairing and emits both the
// class declaration and construction body. This deletes handwritten factories
// without changing or duplicating any production call site.
class RecipeFactoryArg<string name, string cppType, string storage,
                       bit optionalEmpty = 0, int partOrdinal = -1,
                       int operandOrdinal = -1, string trueLiteral = "",
                       string falseLiteral = "",
                       string fixedLiteral = ""> {
  string Name = name;
  string CppType = cppType;
  string Storage = storage;
  bit OptionalEmpty = optionalEmpty;
  int PartOrdinal = partOrdinal;
  int OperandOrdinal = operandOrdinal;
  string TrueLiteral = trueLiteral;
  string FalseLiteral = falseLiteral;
  string FixedLiteral = fixedLiteral;
}
class RecipeFactoryNode<PgNode node, string factory,
                        list<RecipeFactoryArg> args> {
  PgNode Node = node;
  string Factory = factory;
  list<RecipeFactoryArg> Args = args;
}
class RecipeStringOperandArg<string name, int ordinal>
    : RecipeFactoryArg<name, "string", "operands", 0, -1, ordinal>;
class RecipeBoolLiteralOperandArg<string name, int ordinal,
                                  string trueLiteral, string falseLiteral>
    : RecipeFactoryArg<name, "bool", "operands", 0, -1, ordinal,
                       trueLiteral, falseLiteral>;
// A target-shape atom injected by the generated factory, not accepted from a
// caller and not selected from projection data. This is the PostgreSQL analog
// of a fixed literal builder argument: it can name syntax such as a column,
// while the neighboring operands remain finalized target expressions.
class RecipeFixedLiteralOperandArg<string name, int ordinal, string literal>
    : RecipeFactoryArg<name, "fixed-string", "operands", 0, -1, ordinal,
                       "", "", literal>;
class RecipeBodyArg<string name>
    : RecipeFactoryArg<name, "stmt-list", "body">;
class RecipeGroupArg<string name>
    : RecipeFactoryArg<name, "string-groups", "group">;

def B1RaiseMessage : RecipeStringOperandArg<"msg", 0>;
def B1RaiseArgument : RecipeStringOperandArg<"arg", 1>;
def B1AssignTarget : RecipeStringOperandArg<"var", 0>;
def B1AssignExpression : RecipeStringOperandArg<"expr", 1>;
def B1StatusProcedure : RecipeStringOperandArg<"proc", 0>;
def B1StatusKey : RecipeStringOperandArg<"pkey", 1>;
def B1StatusField : RecipeStringOperandArg<"field", 2>;
def B1LedgerName : RecipeStringOperandArg<"ledger", 0>;
def B1LedgerParty : RecipeStringOperandArg<"party", 1>;
def B1LedgerCurrency : RecipeStringOperandArg<"currency", 2>;
def B1LedgerSignedAmount : RecipeStringOperandArg<"signedAmount", 3>;
def B1LedgerBalanceColumn
    : RecipeFixedLiteralOperandArg<"balanceColumn", 4, "balance">;
def B1PostingProcedure : RecipeStringOperandArg<"proc", 0>;
def B1PostingEntry : RecipeStringOperandArg<"entry", 1>;
def B1PostingLedger : RecipeStringOperandArg<"ledger", 2>;
def B1PostingParty : RecipeStringOperandArg<"party", 3>;
def B1PostingAmount : RecipeStringOperandArg<"amount", 4>;
def B1PostingCurrency : RecipeStringOperandArg<"currency", 5>;
def B1PostingSignedAmount : RecipeStringOperandArg<"signedAmount", 6>;
def B1PostingKey : RecipeStringOperandArg<"key", 7>;
def B1PostingMemo : RecipeStringOperandArg<"memo", 8>;
def B1GuardCondition : RecipeStringOperandArg<"cond", 0>;
def B1GuardBody : RecipeBodyArg<"body">;
def B1ProgressValue
    : RecipeBoolLiteralOperandArg<"value", 0, "true", "false">;
def B1ReplayKey : RecipeStringOperandArg<"key", 0>;
def B1ReplayEntry : RecipeStringOperandArg<"entry", 1>;
def B1InsertProcedure : RecipeStringOperandArg<"proc", 0>;
def B1InsertKey : RecipeStringOperandArg<"key", 1>;
def B1GroupOrdinal : RecipeStringOperandArg<"ordinal", 2>;
def B1Policies : RecipeGroupArg<"policies">;
def B1EffectKind : RecipeStringOperandArg<"kind", 0>;
def B1EffectName : RecipeStringOperandArg<"name", 1>;
def B1EffectLedger : RecipeStringOperandArg<"ledger", 2>;
def B1EffectSuffix : RecipeStringOperandArg<"suffix", 3>;

def : RecipeFactoryNode<Blank, "blank", []>;
def : RecipeFactoryNode<Raise, "raise", [B1RaiseMessage]>;
def : RecipeFactoryNode<RaiseArg, "raiseArg",
                        [B1RaiseMessage, B1RaiseArgument]>;
def : RecipeFactoryNode<Assign, "assign",
                        [B1AssignTarget, B1AssignExpression]>;
def : RecipeFactoryNode<StatusWrite, "statusWrite",
                        [B1StatusProcedure, B1StatusKey, B1StatusField]>;
def : RecipeFactoryNode<StatusWriteUpdate, "statusWriteUpdate",
                        [B1StatusProcedure, B1StatusKey, B1StatusField]>;
def : RecipeFactoryNode<LedgerUpsert, "ledgerUpsert",
                        [B1LedgerName, B1LedgerParty, B1LedgerCurrency,
                         B1LedgerSignedAmount, B1LedgerBalanceColumn]>;
def : RecipeFactoryNode<PostingInsert, "postingInsert",
                        [B1PostingProcedure, B1PostingEntry, B1PostingLedger,
                         B1PostingParty, B1PostingAmount, B1PostingCurrency,
                         B1PostingSignedAmount, B1PostingKey]>;
def : RecipeFactoryNode<PostingInsertWithMemo, "postingInsertWithMemo",
                        [B1PostingProcedure, B1PostingEntry, B1PostingLedger,
                         B1PostingParty, B1PostingAmount, B1PostingCurrency,
                         B1PostingSignedAmount, B1PostingKey, B1PostingMemo]>;
def : RecipeFactoryNode<If, "ifThen",
                        [B1GuardCondition, B1GuardBody]>;
def : RecipeFactoryNode<FlatIf, "flatIf",
                        [B1GuardCondition, B1GuardBody]>;
def : RecipeFactoryNode<ProgressFlag, "progressFlag", [B1ProgressValue]>;
def : RecipeFactoryNode<PostingIdempotency, "postingIdempotency",
                        [B1ReplayKey, B1ReplayEntry]>;
def : RecipeFactoryNode<KeyClaimInsert, "keyClaimInsert",
                        [B1InsertProcedure, B1InsertKey]>;
def : RecipeFactoryNode<CommittedGroupInsert, "committedGroupInsert",
                        [B1InsertProcedure, B1InsertKey, B1GroupOrdinal]>;
def : RecipeFactoryNode<QuorumAcceptInsert, "quorumAcceptInsert",
                        [B1InsertProcedure, B1InsertKey]>;
// : the temporal per-policy accept INSERT — the last handwritten PgStmt
// factory, extracted to the generated B1 schema (same (proc, key) operand
// carrier as the single-quorum/key-claim inserts).
def : RecipeFactoryNode<TemporalAcceptInsert, "temporalAcceptInsert",
                        [B1InsertProcedure, B1InsertKey]>;
def : RecipeFactoryNode<PolicyCaseSelect, "policyCaseSelect", [B1Policies]>;
def : RecipeFactoryNode<EffectLedgerComment, "effectLedgerComment",
                        [B1EffectKind, B1EffectName, B1EffectLedger,
                         B1EffectSuffix]>;
def : RecipeFactoryNode<IdempotencyGuardComment,
                        "idempotencyGuardComment", []>;
def : RecipeFactoryNode<BalancedInvariantComment,
                        "balancedInvariantComment", []>;
def : RecipeFactoryNode<IdempotentReturn, "idempotentReturn", []>;
