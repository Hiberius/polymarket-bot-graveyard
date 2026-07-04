# 🪦 Final Autopsy — SPECTRIX (every bot, v0 → v5)

> **The definitive closing document.** Written on **2026-06-28**, the day I decided to shut everything down.
> My exact words that day: *"turn it all off, this strategy doesn't work, it's a coin flip, there's no point."*
> **I was right.** This file exists so that the next session — or me, months from now — **doesn't repeat a single one of these mistakes.**
>
> The golden rule that guided this autopsy: **the truth is in the database, not in the bot's reports.** The historical reports lied (see "phantom +$2,489"). Every number below is pulled from PostgreSQL on 2026-06-28, not from logs or auto-generated reports.

This is a lightly edited English translation of the original autopsy. Machine-specific paths, PIDs, and restart commands have been removed; every figure is unchanged.

---

## 0. Brutal TL;DR (5 lines)

- **6 bots in 3 months** (29 Mar → 28 Jun 2026). **Zero edge found. Zero profitable live trades. Ever.**
- **Real money lost: ~$40–47** (Apex Predator + Shadow Sniper, Mar–Apr 2026, Polymarket wallet **banned**). Everything else was always **simulated / paper / shadow**.
- **Real live trades in the database: 0.** No strategy ever went to real capital after the ban.
- Every version dies on the **same wall**: an assumed edge that, measured honestly, **does not exist** for a retail trader with ~$500.
- The only thing that worked was the **shadow-first discipline of v5**: it *correctly refused* to promote a coin-flip strategy to live. The system did its job by saying "there's no edge." That "no" is the deliverable.

---

## 1. Current state — everything off (2026-06-28)

Verified in the field; does not restart on boot or login:

| Thing | State |
|-------|-------|
| Main oracle process | ✅ killed |
| Orphaned `caffeinate` | ✅ killed |
| launchd job `com.spectrix.oracle` | ✅ bootout + disable |
| launchd job `...watchdog` (v4 remnant) | ✅ bootout + disable |
| Dashboard port | ✅ free |
| LaunchAgents | ✅ zero (moved to reversible quarantine) |
| PostgreSQL `polybot` | 🟢 left alive (only to read the history; it is not "the bot") |

---

## 2. Full chronology — every bot, real dates, real outcomes

Dates from the git log and real database timestamps. Outcomes from the DB, not the reports.

### v0 — "Apex Predator" (29 Mar 2026) — **4 hours alive**

- **What:** Avellaneda-Stoikov market maker on Polymarket binaries.
- **Assumed edge:** profit from the spread by quoting bid/ask.
- **Real outcome:** **~-$20 real.** Catastrophic A-S parameters (spread up to 129%), wrong USDC address (native instead of USDC.e), **56,000+ orders rejected** by the CLOB → **wallet flagged/banned.**

### v1 — "Shadow Sniper" (30 Mar → 5 Apr 2026) — **6 days**

- **What:** 4 event-driven strategies (copy-whale, momentum, neg-risk arb, cross-venue).
- **Assumed edge:** follow the whales, momentum on binaries, neg-risk arbitrage (outcomes sum < 1).
- **Real outcome:** **~-$40 of $57** (degraded to $0). Fatal bug: **bought 9 times, never sold** (no automatic SELL) → all positions underwater after the initial move. **Same banned wallet as v0.**
- 37 bugs cataloged in the original post-mortem.
- ⚠️ **From here on: zero real money. Everything simulated / paper / shadow.**

### v2 — "SPECTRIX 2.0 / Phantom" + 12 strategies (11 Apr → 4 May 2026) — **paper**

- **What:** main strategy **Phantom** = BTC 5-minute UP/DOWN with 3-AI consensus (Opus + GPT + Gemini) on a Chainlink signal + 11 parallel strategies (mean-reversion, arb, cross-venue, forecast, live-game, news, weather, whale, political, snipe, market-maker).
- **Assumed edge:** the 3-AI ensemble predicts BTC 5-min direction better than a coin flip.
- **Real outcome from the DB** (238 phantom trades, 04-12 → 04-25):
  - raw `pnl`: **+$2,491.86** ← **this was the lie** (fills at Gamma-bid, phantom profit)
  - real `adjusted_pnl`: **+$649.11** ← more honest, but still **paper, never live**
  - The edge was **BTC beta, not alpha:** UP split 87% win-rate (riding the uptrend), DOWN split 50% (random). On a down day it would have collapsed.
- **Why dead:** the BTC 5-min book is **fully arbitraged** by professional market makers (Wintermute, GSR). At T-30s it's already at 0.98 in the right direction → buying at 0.98 to receive 1.00 = +2% gross, eaten by fees = **0% net.**

### v3 — "Long-Tail Sniper" (26 Apr → 4 May 2026) — **never deployed live**

- **What:** scanner over 480+ long-tail markets (politics, sports, pop, altcoins) with a 3-tier AI evaluator. Excludes BTC.
- **Assumed edge:** long-tail markets are priced by humans (slow, 5–15% spreads), not HFT.
- **Real outcome from the DB:** 65 `long_tail_sniper` trades (04-28 → 04-30), **P&L ~0.** Broken funnel: 13,860 signals → 75 pass tier-0 → 12 orders → **0 filled.**
- **Why dead:** elegant design, broken funnel implementation + AI latency (2–11s) > opportunity window (<1s). Four parallel proofs-of-concept converge on: *"the 5-min binary is a random walk."*

### v4 — "Maker-Only BTC" (4 May → 1 Jun 2026) — **55 days paper, 0 live**

- **What:** market maker on BTC 5m/15m/1h with `signal_engine_maker` (fair-price from a Chainlink LUT, 2.55M samples) + 3-AI Strategic Selector + 5 anti-toxic circuit breakers.
- **Assumed edge:** Chainlink fair-price + **maker rebate 20–25%** (after the 30-Mar fee change). BTC 15m/1h less efficient than 5m.
- **Real outcome from the DB** (`maker_btc_5m`, 1,585 trades, 05-19 → 06-28):
  - raw `pnl`: **-$58.34**
  - real `adjusted_pnl`: **-$277.09** ← **the true number. The maker LOST.**
  - The bot's reports said things like "+$2,489" and "all-time -$147" depending on which column they read — **the bot lied about its own P&L**, confusing raw `pnl`, `adjusted_pnl`, and the v2 phantom numbers.
- **Why dead:** no real edge. Marginal win-rate but **negative payoff** (loses more than it wins). LUT fair-price calibrated on one regime (13–25 Apr) and used 55 days later on a changed microstructure. The maker rebate doesn't cover the adverse selection. **Never did the cutover to live** (rightly).
- **Operational refrain:** 26 days of testing riddled with **BLOCKER #1→#J**: geo-block, broken Gamma pagination (bot blind for 24h), dead watchdog for 10 days, TCC/xpcproxy (bot dead 22h), macOS app-nap, a 109 MB error log. More time spent keeping it alive than finding an edge.

### v5 — "Oracle Gap" (1 Jun → 28 Jun 2026) — **shadow-only, 0 trade intent**

The conceptually correct turn: **measure the edge forward on real outcomes BEFORE risking a cent.** 5 subsystems, all really deployed and logging to the DB:

| Subsystem | What it measures | Real DB state |
|-----------|------------------|---------------|
| **Shadow Observatory** | consensus-vs-Polymarket divergence on sports; forward Brier | **332 resolutions**, Brier **0.2377**, edge **-2.86pp** |
| **In-Game Observatory** | ESPN live win-prob vs Polymarket price | in the ~4,675 `oracle_divergences` (01→28 Jun) |
| **Goal-Lag Stopwatch** | Polymarket repricing lag after a World Cup goal | **77 events** (11→28 Jun) — *flawed curves, see below* |
| **Lag Microscope** | sub-second CLOB WSS ticks + in-play Poisson | **5.76 MILLION ticks**, 53 sessions |
| **BTC–Deribit** | option-implied P(BTC>K) from Deribit vs Polymarket ladder | **35 resolved**, WR 49%, +423pp |

- **Real outcome — sports:** Brier **0.2377** (0.25 = coin flip), realized edge **-2.86pp**, "would have won" 48.2%. **Zero edge.** The calibration gate set `graduated=FALSE` on **all** categories. ✅ **The gate worked: it refused to send a non-edge live.**
- **Real outcome — BTC-Deribit:** 35 resolved, **WR 49% = coin flip.** The +423pp is **variance in disguise:** 17 wins × +56.5pp vs 18 losses × -29.8pp is a *mechanical* asymmetric payoff (bet NO on high strikes at a low price → win rarely but big), not an edge. The 35 trades are **strongly correlated** (the same BTC move resolves 4–5 strikes the same day) → real independent sample ~8–10 days. **Indistinguishable from directional luck.**
- **Goal-Lag technical flaw:** the 77 curves saved only `{t, price}`, with no anchor to the goal event or a pre-goal baseline → **trajectories that can't be turned into a clean lag distribution.** It was accumulating semi-unusable data. (That was the bug I was about to fix when I said stop.)

---

## 3. The real numbers (from the database, 2026-06-28)

### Simulated / paper trades — 2,179 total (11 Apr → 28 Jun)

| strategy | n | raw `pnl` | REAL `adjusted_pnl` | period |
|----------|---|-----------|---------------------|--------|
| `maker_btc_5m` (v4) | 1,585 | -$58.34 | **-$277.09** | 19 May → 28 Jun |
| `phantom` (v2) | 238 | **+$2,491.86** ⚠️lie | **+$649.11** | 12 Apr → 25 Apr |
| `news_catalyst` | 24 | -$123.62 | $0.00 | 12 Apr → 18 Apr |
| `forecast` | 9 | -$10.37 | — | 11 Apr → 13 Apr |
| weather, snipe, arb, whale, political, LTS | ~330 | ~$0 | ~$0 | Apr |
| **TOTAL** | **2,179** | +$2,299.52 | **+$372.02** | — |

> ⚠️ The "+$372 adjusted" total **is not real money**: it's dominated by the +$649 phantom paper of April (never live) minus the -$277 maker. **None of these trades ever touched real capital.**

### Shadow v5 — the proof of the absence of edge

| metric | value | reading |
|--------|-------|---------|
| Sports Brier (n=332) | **0.2377** | 0.25 = random → **coin flip** |
| Realized sports edge | **-2.86pp** | negative → **loses** |
| Graduated categories | **0 / 4** | gate said NO to everything |
| BTC-Deribit (n=35) | WR **49%** | coin flip |

### Real money, all-time

| | amount |
|-|--------|
| Real losses (v0+v1, banned wallet) | **~-$40 to -$47** |
| Live trades in the DB after the ban | **0** |
| Real profit, all versions | **$0** |

---

## 4. Recurring death pattern (why EVERYTHING failed)

1. **Edge never validated forward before live.** Positive paper on n=50–100 (statistical noise) → belief in an edge → it doesn't exist. v5 was built to break this, and it *proved* the absence of edge instead of betting on it.
2. **Polymarket book overrated as "inefficient."** Liquid markets are arbitraged by professional HFT. At T-30s the price is already right. Retail margin ~0 net of fees.
3. **AI latency > opportunity window.** 3-AI consensus = 2–11s. Repricing window = <1s to a few seconds. The decision arrives after the fact.
4. **Static fair-price on a moving market.** LUT calibrated on one regime, used on another. The edge vanishes or inverts.
5. **Asymmetric payoff mistaken for edge.** WR 49% + wins bigger than losses *looks* like profit but is the price structure (NO at a low price), not a predictive advantage.
6. **Human impatience → a pivot every 2–3 weeks.** 6 versions in 3 months. Every honest validation needs 30+ days × N categories. The patience budget always runs out before the proof.
7. **More time keeping the bot alive than finding the edge.** The v4 BLOCKER #1→#J: macOS sleep, TCC, app-nap, Gamma flap, dead watchdogs, 100 MB logs. A huge infrastructure tax on a nonexistent edge.

---

## 5. What we learned (the residual value, the one positive thing)

No profit. But these truths are now **proven with real data**, not opinions:

1. **BTC short-duration on Polymarket: NO retail edge.** Died four times (v0 MM, v2 phantom 5m, v4 maker 5m/15m/1h, v5 Deribit). Confirmed by external 2026 research (arb window 12s→2.7s, dynamic fees up to 3.15% built specifically to kill latency-arb). **Structural wall. Never again.**
2. **Static sport price comparison: coin flip.** Brier 0.2377 on n=332. You're measuring two already-aligned prices. Refuted.
3. **News-lag / in-game lag:** the framework logged **5.76M ticks** reliably, but **no calibrated edge emerged** in the time available. Not 100% refuted, but not proven — and it needs tight polling (cost) for an uncertain edge.
4. **BTC-Deribit divergence:** WR 49%. Risk-neutral (option) divergence ≠ real probability. Not arbitrage — a directional bet in disguise.
5. **Copy-trading top traders** (floated in June): mathematically losing. High-frequency wallets are market makers you can't copy (you eat the imitation penalty + you're below the ~$5k threshold). Never built, rightly.
6. **Shadow-first discipline WORKS as a shield.** It's the only part of the project that did exactly its job: measure honestly and **say no.** The value of SPECTRIX isn't the P&L (zero) — it's being able to state *"these edges don't exist for me"* with proof in hand instead of hope.

---

## 6. What never to do again (if the temptation returns months from now)

- ❌ **DON'T** trade BTC/crypto short-duration on Polymarket. Four deaths. Wall.
- ❌ **DON'T** trust a positive paper P&L on n<200. It's noise. It was always noise.
- ❌ **DON'T** believe a bot-generated report. Read `adjusted_pnl` from the DB by hand. The bot lied every time it could.
- ❌ **DON'T** mistake an asymmetric payoff (WR ~50%, big wins) for an edge. It's variance.
- ❌ **DON'T** restart with "I have a brilliant new idea" without re-reading this file first. The sixth brilliant idea died like the first five.
- ❌ **DON'T** deploy real capital until a category is `graduated=TRUE` in the calibration gate **with n≥200 independent samples across multiple regimes** + a **net-of-fees** confirmation. It never happened. It probably won't.

---

## 7. What's reusable (if one day, for a DIFFERENT problem)

The engineering was solid; the alpha was missing. If you ever need infrastructure (for something that is **not** this):

- **Immortal asyncio service:** launchd + `caffeinate -i` + watchdog with heartbeat + `os._exit(1)` self-restart. Held 8 days straight and self-healed through sleep/wake. Good pattern.
- **Shadow-first / calibration gate framework:** Brier + reliability + graduated flag. It's honest and it works. Reusable to validate *any* predictive signal.
- **Free data feeds already integrated:** ESPN scoreboard + win-prob, Gamma, CLOB WebSocket, Deribit, The Odds API. All no-key or free-tier.
- **DB schema + FastAPI dashboard.**
- **5.76M CLOB ticks + 2.55M Chainlink prices** archived: a real dataset if offline research is ever needed.

---

## 8. Final verdict

**SPECTRIX is closed.** 6 versions, 3 months, ~$45 real lost, $0 profit, 0 profitable live trades.

The decision of 2026-06-28 — *"it's a coin flip, turn it all off"* — is the most lucid moment of the whole project. It's not a defeat: it's the only version that **stopped lying to itself.** The first five chased a nonexistent edge with growing hope; the sixth **measured** it and had the courage to read the result: coin flip.

The system worked in the end. It said: *there's nothing here.* And we believed it.

The end.

---

*Originally generated on 2026-06-28. Numbers from PostgreSQL `polybot`, not from the bot's reports. Historical reconstruction cross-checked from git log + archived docs + DB.*
