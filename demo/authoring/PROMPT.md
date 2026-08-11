# Authoring prompt — natural language → Neutrino L1 (`.neu`)

You are translating a multi-party coordination agreement into Neutrino L1
source. You are an **untrusted proposer**. The Neutrino translator will
compile and verify the result; invalid or unbalanced programs are refused.

## Output form

Emit **only** a single Neutrino procedure source file (`.neu` syntax). No
markdown fences, no commentary.

## Grammar contract (minimal)

```
procedure <name> {
    trigger <identifier>
    version "x.y.z"

    participant <Name> {
        role = "<role>"
        org  = "<org>"
    }
    // one or more participants

    allow "<orgA>" with "<orgB>" {
        "<orgA>" as "<roleA>"
        "<orgB>" as "<roleB>"
    }

    input <name> : string | party | money | currency | number
    // as needed

    debit <name> {
        ledger          = "<ledger.path>"
        owner           = "<role>"
        participant     = "<ParticipantName>"
        party           = %party_input
        amount          = %money_input
        currency        = %currency_input
        idempotency_key = %string_input
        when            = <guard>   // optional
    }

    credit <name> { ... same fields ... }

    assert balanced
}
```

## Hard rules

1. If the agreement moves value (any debit/credit), you **must** declare
   `assert balanced`.
2. Debit and credit amounts for a pay-for-work pair must match under the same
   guard and share the same idempotency key.
3. Use only roles and orgs named in the agreement.
4. Do not invent wallets, custody, or off-chain APIs in L1.
5. Dossier content stays off-chain; at most a digest/string input may appear.

## Task

Translate `agreement.md` (paid KYC dossier verification) into a procedure that
encodes the fee movement: Requester pays Verifier iff verification is
positive (`verified == 1`), balanced by construction.
