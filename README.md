# 🪦 Polymarket Bot Graveyard

> Six autonomous trading bots. Three months. Zero edge found. This is the honest, step-by-step post-mortem of every one of them — what I set out to do, how each died, and the one thing that finally worked.

[![CI](https://github.com/Hiberius/polymarket-bot-graveyard/actions/workflows/ci.yml/badge.svg)](https://github.com/Hiberius/polymarket-bot-graveyard/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docs: CC BY 4.0](https://img.shields.io/badge/Docs-CC%20BY%204.0-lightgrey.svg)](LICENSE-DOCS)
[![Built with Claude Fable 5](https://img.shields.io/badge/Built%20with-Claude%20Fable%205-8A2BE2.svg)](https://www.anthropic.com/)

**This is not a "how I made money" repo. It's the opposite.** Between March and June 2026 I built, ran, and killed six generations of automated trading bots on [Polymarket](https://polymarket.com), one after another, each convinced it had found an edge the last one missed. None had. I'm publishing the whole graveyard — code, plans, and a brutally honest autopsy — because a documented failure is worth more than a hidden one, and because the *reasons* these failed are structural and reusable knowledge.

If you're about to build a prediction-market bot: **read this first.** It might save you three months.

---

## TL;DR

- **6 bots in 3 months** (29 Mar → 28 Jun 2026). **Zero edge found. Zero profitable live trades. Ever.**
- **Real money lost: roughly $45**, all in the first two weeks (v0 + v1), after which the Polymarket wallet was **banned** for order-spam. Everything after that was paper / shadow only.
- Every version dies on the **same wall**: an assumed edge that, measured honestly, **does not exist** for a retail trader with a few hundred dollars.
- The only thing that ever worked was the **shadow-first discipline of the last version** — it *correctly refused* to promote a coin-flip strategy to live trading. The system's job was to say "there's no edge here," and it did. **That "no" is the deliverable.**

---

## The journey at a glance

```
v0  Apex Predator     29 Mar        4 hours     market maker        → ~-$20 real, wallet flagged
v1  Shadow Sniper     30 Mar–5 Apr  6 days       4 event strategies  → ~-$40 real, wallet BANNED
── real money ends here. everything below is paper / shadow ──
v2  Phantom           11 Apr–4 May  paper        BTC 5-min + 3-AI    → "profit" was a lie (beta, not alpha)
v3  Long-Tail Sniper  26 Apr–4 May  never live   480+ market scanner → funnel broke, AI too slow
v4  Maker-Only BTC    4 May–1 Jun   55 days paper Chainlink maker     → the maker LOST money
v5  Oracle Gap        1 Jun–28 Jun  shadow-only  measure edge first  → proved there was no edge ✅
```

See the [full timeline diagram](assets/timeline.svg) and the chapter-by-chapter walkthrough in [`journey/`](journey/).

---

## The scoreboard

Each bot, what it bet on, and why it died. Outcomes are qualitative on purpose — the point isn't the exact P&L (it was tiny), it's the **pattern**.

| # | Codename | What it tried | How it died | Lesson |
|---|----------|---------------|-------------|--------|
| v0 | **Apex Predator** | Avellaneda-Stoikov market maker on binary markets | Insane spread params (up to 129%), wrong USDC address, 56,000+ rejected orders → wallet flagged | Don't ship a market maker you haven't paper-traded for a day |
| v1 | **Shadow Sniper** | Copy-whale + momentum + neg-risk arb + cross-venue | Bought 9 times, **never sold** (no auto-exit). Same wallet got banned | Build the *exit* before the entry |
| v2 | **Phantom** | BTC 5-min UP/DOWN via 3-AI consensus (Claude+GPT+Gemini) | The "+profit" was **BTC beta, not alpha** — it just rode an uptrend. 5-min book is fully arbitraged by pros | A positive paper P&L on 100 trades is noise |
| v3 | **Long-Tail Sniper** | AI scanner over 480+ "slow" markets (politics, sports, pop) | Funnel collapsed: 13,860 signals → 0 fills. AI latency (2–11s) ≫ opportunity window (<1s) | Elegant design, broken plumbing, too slow |
| v4 | **Maker-Only BTC** | Chainlink fair-price maker + maker rebate on BTC 5m/15m/1h | 55 days of paper, adjusted P&L **negative** — the maker lost. Static fair-price on a moving market | Rebates don't cover adverse selection |
| v5 | **Oracle Gap** | Measure edge *forward on real outcomes* before risking a cent | Proved the edge didn't exist (sport Brier 0.2377 ≈ coin-flip; BTC-Deribit win-rate 49%). Gate said **no** to everything | This is the version that told the truth |

---

## Why *everything* failed — the recurring death patterns

The same handful of mistakes killed all six. If you recognize yourself in these, stop and read the [autopsy](docs/AUTOPSY.md).

1. **Edge never validated forward before going live.** A positive paper P&L on 50–100 trades is statistical noise. Every bot believed the noise.
2. **The order book was treated as "inefficient." It isn't.** Liquid Polymarket books are arbitraged by professional HFT (Wintermute, GSR). By T-30s the price is already right. Retail net-of-fees margin ≈ 0.
3. **AI latency > opportunity window.** A 3-model consensus takes 2–11 seconds. The repricing window is under a second. The decision always arrives too late.
4. **Static fair-price on a market that moves.** A lookup table calibrated in one regime, used in another, either loses its edge or inverts it.
5. **Asymmetric payoff mistaken for edge.** A ~49% win-rate with big-but-rare wins *looks* like profit. It's the price structure (betting NO at a low price), not a predictive advantage.
6. **Impatience → a new "brilliant idea" every 2–3 weeks.** Six versions in three months. An honest validation takes 30+ days per category. The patience budget always ran out before the proof.
7. **More time spent keeping the bot alive than finding an edge.** macOS sleep, TCC prompts, app-nap, dead watchdogs, 100 MB error logs. An enormous infrastructure tax on an edge that never existed.

---

## What actually worked (the residual value)

No profit — but these are now **proven with real data**, not opinions:

- **BTC short-duration on Polymarket has no retail edge.** It died four separate ways (v0, v2, v4, v5). It's a structural wall, confirmed by external 2026 research (arb window shrank to ~2.7s; dynamic fees up to ~3% exist specifically to kill latency-arb).
- **Shadow-first validation works as a shield.** Measuring a signal forward against real outcomes and *refusing to trade until it graduates* is the only part of this project that did its job perfectly. It said "there's nothing here," and it was right.
- **The engineering was solid; the alpha was missing.** The immortal async service, the calibration gate, the free data-feed integrations, and a 5.76-million-tick dataset are genuinely reusable — for a *different* problem. See [`journey/99-lessons.md`](journey/99-lessons.md).

---

## How to read this repo

```
polymarket-bot-graveyard/
├── journey/          ← START HERE. One chapter per bot, in order. Same skeleton each time:
│                        Goal → Hypothesis → How I built it → What happened → Why it died → What survived
├── bots/             ← curated, sanitized code snapshots of each bot (the "greatest hits", secret-free)
├── docs/AUTOPSY.md   ← the full, unflinching final autopsy (real numbers, from the database)
└── assets/           ← timeline diagram
```

Best path: [`journey/00-overview.md`](journey/00-overview.md) → the numbered chapters → [`docs/AUTOPSY.md`](docs/AUTOPSY.md).

---

## Contributing — two ways in

This graveyard is open. See [CONTRIBUTING.md](CONTRIBUTING.md).

- 🔬 **Autopsy & discussion** — think a failure diagnosis is wrong? Have your own prediction-market post-mortem? Know a structural reason an edge decayed? Open a [discussion issue](.github/ISSUE_TEMPLATE/share_postmortem.yml). Negative results welcome.
- ⚒️ **Revive a strategy** — some of these were *close*. Fork it, fix a documented failure mode, run it forward honestly, and report back with an [issue](.github/ISSUE_TEMPLATE/revive_strategy.yml). The rule: **shadow-validate before you claim an edge.**

---

## Disclaimer

This repository is a **retrospective and educational** account of my own experiments. It is **not financial advice**, not a strategy you should run with real money, and not an endorsement of prediction-market trading. Automated trading can lose money quickly; I lost real money doing exactly what's documented here. Prediction markets are legally restricted in many jurisdictions — check your own. You are responsible for what you do with this. See [DISCLAIMER.md](DISCLAIMER.md).

---

## License

- **Code** (everything in `bots/`): [MIT](LICENSE)
- **Writing** (`journey/`, `docs/`, this README): [CC BY 4.0](LICENSE-DOCS)

Built and documented with [Claude Fable 5](https://www.anthropic.com/). The autopsy numbers come from the bot's PostgreSQL database, not its self-reported logs — because the bot lied about its own P&L, and that's a lesson too.
