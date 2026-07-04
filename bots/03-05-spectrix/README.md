# bots/03-05-spectrix — Long-Tail Sniper, Maker-Only BTC, Oracle Gap (v3–v5)

Curated, sanitized snapshot from the final SPECTRIX codebase (v3 → v5). **Illustrative excerpts, not a runnable package.** Read the stories in [`journey/03-long-tail-sniper.md`](../../journey/03-long-tail-sniper.md), [`journey/04-maker-btc.md`](../../journey/04-maker-btc.md), and [`journey/05-oracle-gap.md`](../../journey/05-oracle-gap.md).

This folder holds the **best things the whole project produced** — not a winning strategy (there wasn't one), but the honest measurement rig and the infrastructure that ran it.

| File | What it is |
|------|-----------|
| `oracle/calibration_gate.py` | ⭐ **The star of the graveyard.** Computes Brier score + reliability per category and sets a `graduated` flag. It's what refused to send a coin-flip live. Reusable to validate *any* predictive signal |
| `oracle/divergence.py` | Recording the divergence between a model's forecast and the market price, for forward scoring |
| `watchdog.py` | The "immortal service" watchdog — heartbeat + self-restart. Part of the launchd + `caffeinate` pattern that ran for 8 days straight and self-healed through sleep/wake |
| `db/schema.sql` | The database schema — trades, AI decisions, oracle divergences, circuit-breaker state |

> If you take one file from this whole repo, take `oracle/calibration_gate.py`. The single most valuable output of three months of work was a rig honest enough to say "there's no edge here" — and this is that rig.
