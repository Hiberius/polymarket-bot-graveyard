# 04 — Maker-Only BTC (v4)

**Dates:** 4 May – 1 June 2026 · **Mode:** paper (55 days) · **Outcome:** the maker *lost* money · **Code:** in [`bots/03-05-spectrix/`](../bots/03-05-spectrix/)

Three versions had failed at *predicting*. So v4 tried to stop predicting. This is the longest-running bot in the graveyard — 55 continuous days — and the one that most thoroughly disproved its own thesis.

## Goal

Be a **market maker**, not a predictor. Quote both sides of BTC binary markets (5-minute, 15-minute, and 1-hour), collect the spread, and — crucially — earn the **maker rebate** that Polymarket had introduced in a late-March fee change. Don't guess direction; get paid to provide liquidity.

## Hypothesis

Two supports:

1. A **fair-price signal** derived from Chainlink, backed by a lookup table built from 2.55 million historical price samples, would tell the bot where "true" value was so it could quote around it intelligently.
2. The **maker rebate (~20–25%)** would turn a break-even spread-capture into a profit. And the 15-minute and 1-hour markets, being less crowded than the 5-minute, would be less efficient and safer to make.

A 3-AI "Strategic Selector" chose which markets to make, and **five circuit breakers** watched for toxic flow (informed traders picking off stale quotes).

## How I built it

A `signal_engine_maker` computing fair value from the Chainlink lookup table, the strategic selector on top, five anti-toxicity circuit breakers, and the whole thing wired into the immortal async service (launchd + `caffeinate` + watchdog) so it could run unattended for weeks. It did run for weeks.

## What happened

Over 1,585 paper trades on the 5-minute maker (19 May – 28 June), the honest, fill-adjusted P&L was about **-$277**. The maker didn't break even. **It lost.**

And it lied about it. Depending on which database column a report read — raw `pnl`, `adjusted_pnl`, or leftover Phantom paper numbers from v2 — the same bot would claim "+$2,489" or "all-time -$147" or the true "-$277" on the same day. Reconciling those columns by hand was the only way to know what had actually happened.

## Why it died

- **The rebate never covered the adverse selection.** A maker gets filled precisely when it's wrong — when an informed trader takes the other side of a stale quote. On efficient BTC markets, that adverse selection cost more than the rebate paid. The win-rate was marginal but the **payoff was negative**: the bot lost more on its losers than it made on its winners.
- **The fair-price table was static on a moving market.** The 2.55M-sample lookup table was calibrated on one regime (mid-April) and then used 55 days later on a microstructure that had changed underneath it. A stale fair-price is worse than no fair-price — it quotes confidently into the wrong number.
- **It never went live** — correctly. The cutover to real capital was gated behind profitability that never arrived.

There's a second, quieter cause of death: **the infrastructure tax.** Those 55 days were a running battle with the operating system — geo-blocks, a broken Gamma API pagination that left the bot blind for 24 hours, a watchdog that silently died for 10 days, macOS TCC and app-nap suspending the process, a 109 MB error log. I spent more time keeping this bot *alive* than looking for an edge. That imbalance — enormous operational effort defending a strategy with no edge — is its own kind of failure, and it's what finally forced the rethink behind v5.

## What survived

- **The immortal async service** (launchd + `caffeinate -i` + heartbeat watchdog with `os._exit(1)` self-restart) genuinely works — it ran for 8 days straight and self-healed through sleep/wake cycles. It's the single most reusable piece of infrastructure in the whole project. See [`journey/99-lessons.md`](99-lessons.md).
- The **maker rebate ≠ free money** lesson, learned in full: rebates are compensation for adverse selection, and on an efficient book the compensation is priced correctly *against* you.
- The exhaustion of the "just collect the spread" idea, which cleared the way for the only honest question left: *does an edge exist here at all, before I risk anything?*

→ Next: [Oracle Gap](05-oracle-gap.md) — the version that stopped trading and started measuring.
