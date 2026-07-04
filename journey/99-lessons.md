# 99 — Lessons: what three months of failure actually taught

This is the synthesis chapter — the part that's worth more than all the code. If you read only one file in this repo, read the [autopsy](../docs/AUTOPSY.md); if you read two, read this one too.

## The seven death patterns

Every bot died of some combination of these. They're ordered by how expensive they were.

1. **Edge never validated forward before going live.** A positive paper P&L on 50–100 trades is noise. Five versions in a row mistook noise for signal. The only cure is forward validation on a large, independent, multi-regime sample — which is exactly what v5 was built to do, and which is why v5 is the one that told the truth.

2. **The order book is not "inefficient."** This is the load-bearing false belief of the whole project. Liquid Polymarket markets are arbitraged by professional HFT desks. By ~30 seconds before resolution the price is already correct. The retail net-of-fees margin is approximately zero. "I can spot the mispricing" is what every retail trader thinks right before providing liquidity to someone faster.

3. **AI latency ≫ opportunity window.** A 3-model consensus takes 2–11 seconds. The repricing windows these bots chased were sub-second. The decision always arrived after the opportunity closed. If your signal is slower than your market, you don't have a signal.

4. **Static fair-price on a moving market.** A lookup table calibrated in one regime and used in another doesn't just lose its edge — it can invert it, quoting confidently into the wrong number. Any "fair value" that isn't continuously re-estimated is a liability.

5. **Asymmetric payoff mistaken for edge.** A ~49% win-rate with big-but-rare wins *looks* profitable. It's the price structure (bet NO at a low price → win rarely but large), not predictive skill. Always split results by regime and check whether the "edge" is just the shape of the payoff.

6. **Impatience → a pivot every 2–3 weeks.** Six versions in three months. An honest validation takes 30+ days *per category*. The patience budget ran out before the proof every single time. The brilliant sixth idea died exactly like the first five.

7. **More time keeping the bot alive than finding an edge.** macOS sleep, TCC prompts, app-nap, dead watchdogs, broken API pagination, 100 MB logs. The infrastructure tax on an edge that didn't exist was enormous. If you're spending most of your time on uptime, ask whether there's anything to be up *for*.

## What is now proven (not opinion — measured)

- **BTC / crypto short-duration on Polymarket: no retail edge.** It died four separate ways (v0 market maker, v2 phantom, v4 maker, v5 Deribit). Confirmed by external 2026 research: the arbitrage window shrank to ~2.7 seconds and dynamic fees of up to ~3% exist specifically to kill latency-arb. This is a structural wall. Don't.
- **Static price-comparison on sports: coin flip.** Brier 0.2377 on 332 resolutions. You're comparing two prices that are already aligned.
- **BTC–Deribit divergence: not arbitrage.** Risk-neutral option-implied probability ≠ real-world probability. The "edge" is a directional bet wearing a costume.
- **Copy-trading top wallets: mathematically losing.** High-frequency "smart money" wallets are market makers you can't copy — you eat the imitation penalty and sit below the size threshold that makes their economics work. (Floated in June, correctly never built.)

## What never to do again

- ❌ Trade BTC/crypto short-duration on Polymarket. Four deaths. Wall.
- ❌ Trust a positive paper P&L on n < 200. It's noise. It was always noise.
- ❌ Believe a bot's self-reported P&L. Read `adjusted_pnl` out of the database by hand. The bot lied every time it could.
- ❌ Mistake an asymmetric payoff (≈50% win-rate, big wins) for an edge. It's variance.
- ❌ Start over with "I have a brilliant new idea" without re-reading the autopsy first.
- ❌ Deploy real capital until a category is `graduated = TRUE` with n ≥ 200 independent samples across multiple regimes, confirmed net-of-fees. It never happened. It probably won't.

## What's genuinely reusable (for a *different* problem)

The engineering was solid; only the alpha was missing. If you need infrastructure for something that *isn't* this:

- **Immortal async service** — launchd + `caffeinate -i` + a heartbeat watchdog with `os._exit(1)` self-restart. Ran 8 days straight and self-healed through sleep/wake. See [`bots/03-05-spectrix/`](../bots/03-05-spectrix/).
- **Shadow-first / calibration gate** — Brier + reliability + `graduated` flag. Honest by construction. Reusable to validate *any* predictive signal.
- **Free data-feed integrations** — ESPN scoreboard + win-probability, Polymarket Gamma + CLOB WebSocket, Deribit options, The Odds API. All no-key or free-tier.
- **A real dataset** — 5.76M CLOB ticks + 2.55M Chainlink prices, archived for offline research.
- **Risk primitives** — VPIN toxic-flow detection, Kelly sizing, CVaR, hard limits. Pure logic, in [`bots/01-apex-shadow/`](../bots/01-apex-shadow/).

## The one-sentence version

**The most valuable thing an honest trading system can produce is a well-measured "no."** Everything in this graveyard was an expensive way of learning to trust that "no" the first time instead of the sixth.

→ Read the full [autopsy](../docs/AUTOPSY.md) · back to the [overview](00-overview.md)
