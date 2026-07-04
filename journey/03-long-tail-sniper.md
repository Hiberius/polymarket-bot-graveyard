# 03 — Long-Tail Sniper (v3)

**Dates:** 26 April – 4 May 2026 · **Mode:** never deployed live · **Outcome:** ~0 P&L, 0 fills · **Code:** folded into [`bots/02-phantom/`](../bots/02-phantom/) (same codebase, different scanner)

The reaction to Phantom was correct in theory and broken in practice. If the liquid BTC markets are too efficient, go where the money isn't looking.

## Goal

Stop trading the crowded BTC markets entirely. Instead, scan the **long tail** — 480+ smaller markets across politics, sports, pop culture, and altcoins — and snipe the ones that were visibly mispriced.

## Hypothesis

The long tail is priced by **humans**, not high-frequency market makers. Humans are slow, they leave spreads of 5–15%, and they don't reprice instantly when new information lands. A fast scanner with an AI evaluator should be able to find markets where the price hadn't caught up to reality and take the other side before a human did.

This is a genuinely reasonable thesis. It's probably the *closest* any of these bots came to a real edge. It died on plumbing, not on the idea.

## How I built it

A scanner over the full long-tail universe feeding a **three-tier AI evaluator**: cheap heuristics filtered the universe down, then progressively more expensive model calls scored the survivors, and only the highest-confidence signals became orders.

## What happened

The funnel numbers tell the whole story:

```
13,860 signals detected
     ↓  (tier-0 filter)
     75 passed
     ↓  (AI evaluation → order)
     12 orders placed
     ↓
      0 filled
```

65 trades were recorded over three days (28–30 April) with a P&L of essentially **zero**. Nothing actually executed. The bot could *see* opportunities and never *caught* one.

## Why it died

Two compounding failures:

1. **The funnel was broken.** A 13,860 → 0 collapse isn't selectivity, it's a bug — signals were being dropped or malformed at each stage rather than filtered on merit.
2. **The AI was too slow for the window it was fixed on.** Evaluation took 2–11 seconds. Even in the long tail, the specific mispricings the bot chased closed in under a second. By the time three tiers of models had rendered a verdict, the opportunity was gone.

There's a deeper lesson hiding here. v3 was the fourth independent proof-of-concept (after the market maker, the phantom, and various sub-experiments) to converge on the same conclusion: **the short-window binary is, for a retail bot, a random walk.** You cannot out-react the machines, and the "slow human" markets either don't move enough to beat the spread or move faster than your evaluator when they do.

## What survived

- **The multi-tier evaluator pattern** (cheap filter → expensive model, only on survivors) is the right way to spend an AI budget. It just can't beat sub-second windows.
- The hard realization that **latency is a first-class constraint**, not an implementation detail. From here on, "how fast is the opportunity vs. how fast is my decision?" became the first question asked of any strategy — and it's why the maker phase (v4) tried to stop *reacting* altogether.

→ Next: [Maker-Only BTC](04-maker-btc.md) — stop predicting; collect the spread and the rebate.
