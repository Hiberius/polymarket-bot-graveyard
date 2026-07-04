# Security Policy

This repository contains **sanitized, illustrative code snapshots** — no live execution layer, no wallet client, no API keys. The `bots/` folders are partial by design and cannot trade as-is.

## No secrets by construction

Before publication, every file in `bots/` was scanned for secrets (private keys, API keys, wallet seeds, connection strings, tokens). API credentials in the original code are injected as constructor parameters or environment variables and were never hardcoded. If you believe something sensitive slipped through anyway, please report it.

## Reporting

- **A leaked secret or sensitive data in this repo:** please report privately via GitHub's
  [Report a vulnerability](https://github.com/Hiberius/polymarket-bot-graveyard/security/advisories/new)
  feature, or open a minimal issue that does **not** paste the sensitive value.
- **In your own contributions:** never include real keys, wallet material, or private endpoints in issues or PRs.

## Supported

This is an archival / educational repository. There is no supported runtime and no security patch cadence — it is a record of software that has been shut down.
