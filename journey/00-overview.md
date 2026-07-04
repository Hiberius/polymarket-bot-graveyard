# 00 — Overview: the whole arc

This is a chronological logbook. Six bots, built and killed one after another over three months, each one a reaction to how the last one failed. Read them in order — the point is the *trajectory*, not any single bot.

## The throughline

Every version was born from the same seductive belief: **"prediction markets are inefficient, and I can find the inefficiency with better tooling."** Every version discovered — in a different, more expensive way — that the inefficiency it was chasing either didn't exist, was already arbitraged away by professionals, or was noise it had mistaken for signal.

The arc has a shape:

1. **Over-ambition** (v0–v1): a huge multi-strategy engine shipped straight to real money. Lost ~$45 and got the wallet banned in two weeks.
2. **The AI phase** (v2–v3): "if the edge is hard to find, throw three LLMs at it." The models were slow and the markets they targeted were the most efficient ones on the platform.
3. **The maker phase** (v4): "stop predicting, just collect the spread and the rebate." The rebate didn't cover the adverse selection. The maker lost money for 55 days straight.
4. **The honest phase** (v5): "stop trading entirely — just *measure* whether an edge exists before risking a cent." It measured. There was no edge. It refused to trade. **This is the only version that succeeded at its actual job.**

## The timeline

| Version | Codename | Dates | Mode | Real money? |
|---------|----------|-------|------|-------------|
| v0 | Apex Predator | 29 Mar 2026 (4 hours) | live | yes — ~-$20 |
| v1 | Shadow Sniper | 30 Mar – 5 Apr 2026 | live | yes — ~-$40, wallet **banned** |
| v2 | Phantom | 11 Apr – 4 May 2026 | paper | no |
| v3 | Long-Tail Sniper | 26 Apr – 4 May 2026 | never deployed live | no |
| v4 | Maker-Only BTC | 4 May – 1 Jun 2026 | paper (55 days) | no |
| v5 | Oracle Gap | 1 Jun – 28 Jun 2026 | shadow-only | no |

> There's also a **prologue**: before the SPECTRIX line, the same codebase existed as a Rust + Python + Docker "trading-engine" — an over-engineered start that folded directly into v0/v1. Its own 5-April post-mortem is quoted in [chapter 01](01-apex-and-shadow.md).

## The final numbers (from the database, not the bot's logs)

- Real capital lost across all versions: **~$45** (v0 + v1 only).
- Profitable **live** trades, ever: **0**.
- Total profit, all versions: **$0**.
- The largest reported "profit" (+$2,491 on the Phantom strategy) was an **accounting artifact** — the bot valued paper fills at a price it could never actually get. Corrected, it was a smaller paper number, and it was never real.

The single most important habit this project taught: **read `adjusted_pnl` out of the database by hand. Never trust a bot's self-report.** Every bot in this graveyard lied about its own performance the moment it was allowed to.

## Chapters

1. [Apex Predator & Shadow Sniper](01-apex-and-shadow.md) — the real-money disaster (v0–v1)
2. [Phantom](02-phantom.md) — BTC 5-minute markets and the 3-AI consensus (v2)
3. [Long-Tail Sniper](03-long-tail-sniper.md) — the elegant scanner with broken plumbing (v3)
4. [Maker-Only BTC](04-maker-btc.md) — when the market maker itself loses money (v4)
5. [Oracle Gap](05-oracle-gap.md) — the version that measured instead of guessing (v5)
6. [Lessons](99-lessons.md) — the seven death patterns, what's reusable, what never to do again
