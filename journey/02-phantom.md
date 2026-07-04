# 02 — Phantom (v2)

**Dates:** 11 April – 4 May 2026 · **Mode:** paper only · **Outcome:** "profitable" — and that was a lie · **Code:** [`bots/02-phantom/`](../bots/02-phantom/)

With the live wallet banned, v2 was a clean-sheet rebuild ("SPECTRIX 2.0"). It's the version that taught me the difference between **beta** and **alpha**, the hard way, over a fake $2,491 profit.

## Goal

Predict the direction of Bitcoin over a 5-minute window and trade Polymarket's BTC "up or down" binary markets accordingly. If a 5-minute candle was going to close green, buy UP; if red, buy DOWN. Do it with enough confidence to beat the fees.

## Hypothesis

A single model is a coin toss, but an **ensemble of three frontier LLMs** (Claude Opus + GPT + Gemini), fed the same Chainlink price signal and market context, would agree on direction *more often than chance* — and that agreement, gated to only trade when all three concur, would be an edge. Around this "Phantom" core, eleven other strategies ran in parallel (mean-reversion, arbitrage, cross-venue, forecast, live-game, news, weather, whale, political, snipe, market-maker) as a portfolio of shots on goal.

## How I built it

A single async process running the fleet, a 3-AI consensus gate (2-of-3 to approve, 2-of-3 to reject), a Postgres database for every decision and trade, and a live dashboard. The code artifact for this era is [`polybot`](../bots/02-phantom/) — the strategy modules (`snipe`, `political`, `mean_reversion`, `cross_venue`, `market_maker`, `forecast`, `live_game`) and the analysis layer (`ensemble`, `calibration`, `quant`, `win_probability`) all live there.

## What happened

Over 238 paper trades (12–25 April) the Phantom strategy reported **+$2,491.86**. For a few days it felt like the edge had finally shown up.

It hadn't. Two things were wrong:

1. **The number was fake.** The bot recorded fills at the Gamma mid/bid price it *wished* it had gotten, not a price it could realistically be filled at. Corrected for that (`adjusted_pnl`), the "profit" shrank dramatically — and it was still paper. Never a cent of it was real.
2. **The "edge" was beta, not alpha.** Splitting the trades by direction told the whole story: the UP trades won ~87% of the time; the DOWN trades won ~50% — a coin flip. The bot wasn't *predicting* Bitcoin. It was **long Bitcoin during an uptrend** and mistaking the trend for skill. On a down day, the same logic would have collapsed.

## Why it died

Because BTC 5-minute markets are the **most efficient, most arbitraged markets on the platform**, not the least. They're a magnet for professional market-making desks (Wintermute, GSR and the like). By 30 seconds before resolution, the price is already at ~$0.98 in the correct direction. Buying at $0.98 to receive $1.00 is a +2% gross return — and Polymarket's fees eat exactly that, leaving **~0% net**. There is no room for a retail LLM ensemble that takes several seconds to make up its mind.

This is death #1 of what would eventually be four separate deaths for "trade short-duration BTC on Polymarket."

## What survived

- **The 3-AI consensus gate** as an *engineering* pattern is genuinely nice (independent models, majority approve/reject). What it isn't, is a source of alpha on an efficient market.
- **The discipline of splitting results by regime** (UP vs DOWN) became a permanent habit — it's the cheapest way to catch a beta-masquerading-as-alpha result before it costs you.
- The realization that **a positive paper P&L on ~200 trades means nothing** without a forward-validated, regime-split, net-of-fees breakdown. This directly motivated the shadow-first design of v5.

→ Next: [Long-Tail Sniper](03-long-tail-sniper.md) — if the liquid markets are too efficient, hunt the slow ones.
