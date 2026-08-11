# Security Policy

## Reporting a vulnerability

Please report suspected security issues privately using GitHub's **"Report a
vulnerability"** flow (Security → Advisories) on this repository, rather than
opening a public issue. We will acknowledge the report and coordinate a fix and
disclosure timeline with you.

Please do not disclose a vulnerability publicly until a fix is available.

## Scope and expectations

Neutrino is a compiler and language project. Some important boundaries:

- **Generated contracts are experimental and unaudited.** The Solidity and
  PostgreSQL projects Neutrino renders are coordination artifacts for
  demonstration and evaluation. They have **not** been independently audited and
  must not be treated as production-ready financial infrastructure, wallets,
  fund-custody systems, or authoritative settlement ledgers.
- **Natural-language authoring is untrusted input.** Any authoring assistance
  produces a *candidate* `.neu` translation that the compiler must verify;
  it is never a trusted component of the compiler.
- **Determinism and fail-closed behavior are security properties.** Unsupported
  syntax, invalid scenarios, and target-profile violations are rejected with
  stable diagnostic codes. Reports of paths that silently degrade instead of
  failing closed are in scope.

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest release and
`main`. Pin a specific commit or release if you need a stable surface, and
consult [`COMPATIBILITY.json`](COMPATIBILITY.json) for contract versions.
