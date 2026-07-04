# 01 — Apex Predator & Shadow Sniper (v0–v1)

**Dates:** 29 March – 5 April 2026 · **Mode:** live, real money · **Outcome:** ~$45 lost, wallet banned · **Code:** [`bots/01-apex-shadow/`](../bots/01-apex-shadow/)

This is the only chapter where real money changed hands. It's also the shortest-lived and the most instructive, because it made every beginner mistake at once.

## Goal

Build a fully autonomous trading bot for Polymarket's binary markets and make money from day one. No paper trading, no warm-up — straight to a live wallet. The codebase was ambitious out of the gate: ~8,100 lines of Python (plus an aborted Rust execution layer), 38 modules, 113 tests, a Streamlit dashboard, Docker deployment, and a full risk stack (VPIN toxic-flow detection, Kelly sizing, CVaR, circuit breakers).

## Hypothesis

Two edges, in sequence:

- **v0 (Apex Predator):** classic market making. Quote a bid and an ask around fair value, capture the spread. The Avellaneda-Stoikov model would set optimal quotes.
- **v1 (Shadow Sniper):** if making markets is too hard, be event-driven instead. Four strategies at once: copy whale wallets, ride momentum, arbitrage negative-risk multi-outcome markets (where outcome prices sum to < 1), and exploit price lag between correlated markets.

## How I built it

Everything, at once. Four strategies, a full risk-management layer, a real-time WebSocket feed, order routing with "ghost orders," a correlation engine — all wired to a **live wallet on day one**. The intention was a professional-grade system. The result was a professional-grade system with no idea whether any of its four edges were real.

## What happened

**v0 lasted about four hours.** The Avellaneda-Stoikov parameters were catastrophic (gamma and kappa chosen essentially at random produced spreads up to **129%**). The bot pointed at the wrong USDC contract (native USDC instead of the bridged USDC.e that Polymarket settles in), so orders failed. With no rate limiting, it retried in a tight loop and fired **56,000+ rejected orders** in a few hours. Net: about **-$20** and a wallet that was now flagged.

**v1 lasted six days.** The event-driven rewrite was partially alive but fatally incomplete:

- A one-character API bug (`assets_ids` vs `asset_ids` in the WebSocket subscription) silently killed two of the four strategies.
- The momentum detector fired on 95% of markets at boot because it had no warm-up period — it treated the first data point as a huge "move."
- The safety gate was so restrictive it blocked *selling*.
- **There was no auto-exit.** The bot would buy and simply hold. It bought nine positions and never sold one. When the initial move reversed, every position bled out.
- Around the same time, Polymarket **banned the wallet** outright for the 56k-rejected-order spam from v0.

Net across v0+v1: roughly **-$40 of an initial ~$57**, degrading toward zero, on a dead wallet.

## Why it died

Not because the strategies were necessarily wrong — because **it was impossible to know if they were wrong**, since nothing had ever been paper-traded. The bugs (no auto-sell, wrong contract, no rate limit, no warm-up) were the *proximate* cause. The *root* cause was shipping four unvalidated strategies straight to live capital. You can't debug an edge and a codebase at the same time, on real money, at speed.

## What survived

The 5-April post-mortem for this bot cataloged **37 distinct bugs** and produced a checklist that shaped everything after. The most important lines from it:

> **Paper-trade before anything.** Never real money without at least a week of profitable paper trading that simulates slippage, fees, and latency.
>
> **One strategy at a time.** Four strategies on day one = four times the bugs.
>
> **Exit before entry.** The selling system must work *before* you're allowed to buy.

Concretely reusable and carried forward: the risk primitives (`vpin.py`, `kelly.py`, `cvar.py`), the SQLite state manager, and the paper-trading simulator — pure logic with no Polymarket-specific assumptions. Those files are in [`bots/01-apex-shadow/`](../bots/01-apex-shadow/).

Everything else — the market maker, the neg-risk scanner, the ghost-order router — was thrown away. And the biggest lesson wasn't in the code at all: **the wallet ban meant that from this point on, every remaining version was paper or shadow only.** The graveyard's real-money chapter closes here.

→ Next: [Phantom](02-phantom.md) — throw three LLMs at the most efficient market on the platform.
