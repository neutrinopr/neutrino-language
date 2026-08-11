# Paid KYC dossier verification (natural-language agreement)

**Parties.** Acme Bank (Requester) and KYC Pro Ltd (Verifier).

**Purpose.** The Requester needs a named KYC dossier verified for a case. The
Verifier performs the verification work off-chain and is paid only when a
positive verification is recorded under the agreement.

**Case and evidence.** Each case has a string case id. The dossier file itself
never goes on-chain; only a content digest of the exact dossier file bytes is
bound into the coordination inputs.

**Fee.** A verification fee of money amount `fee` in currency `currency` is
moved from the Requester's escrow ledger to the Verifier's compensation ledger
if and only if the verification input `verified` equals 1. Both legs share the
same case id as idempotency key.

**Balance.** Every value movement under this agreement must be balanced: credits
equal debits for the case.

**Roles.**
- Requester (org `acmebank`, role `requester`) funds the fee and submits case
  inputs.
- Verifier (org `kycpro`, role `verifier`) performs verification work and is
  the party compensated on a positive verdict.

**Non-goals.** This agreement does not define the off-chain verification
procedure, sanctions lists, or identity-document formats. Those remain the
Verifier's operational concern. On-chain, the agreement only coordinates fee
movement under the stated guard.
