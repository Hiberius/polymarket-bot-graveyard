# bots/01-apex-shadow — Apex Predator & Shadow Sniper (v0–v1)

Curated, sanitized snapshot from the original ~8,100-line trading engine that ran as v0/v1. **These are illustrative excerpts, not a runnable package** — the execution layer, wallet client, config, and API keys have been deliberately left out. Read the story in [`journey/01-apex-and-shadow.md`](../../journey/01-apex-and-shadow.md).

The files here are the parts worth keeping: the **risk primitives**. They're pure logic with no Polymarket-specific assumptions, and they're the one thing this disaster produced that's reusable anywhere.

| File | What it is |
|------|-----------|
| `risk/vpin.py` | VPIN toxic-flow detector — estimates whether recent order flow is informed (i.e. picking you off) |
| `risk/kelly.py` | Kelly-criterion position sizing (fractional Kelly) |
| `risk/cvar.py` | Conditional Value-at-Risk, for tail-loss-aware sizing |
| `risk/limits.py` | Hard limits: exposure cap, drawdown, daily loss |
| `strategy/base.py` | The `Strategy` base class every strategy implemented |
| `strategy/momentum_sniper.py` | Momentum detector — and a case study in the "95% false positives at boot with no warm-up" bug |
| `strategy/safety_gate.py` | Pre-trade safety checks — including the inventory guard that was *supposed* to prevent "buy and never sell" |

> ⚠️ `safety_gate.py` is here as a lesson, not a template: in v1 it was simultaneously too strict (it blocked selling) and too loose (it never enforced an exit). The [chapter](../../journey/01-apex-and-shadow.md) explains what went wrong.
