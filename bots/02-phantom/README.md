# bots/02-phantom — Phantom (v2)

Curated, sanitized snapshot from `polybot`, the multi-strategy Python bot behind the "SPECTRIX 2.0 / Phantom" era. **Illustrative excerpts, not a runnable package** — API keys are injected as parameters/env in the originals and are not present here. Read the story in [`journey/02-phantom.md`](../../journey/02-phantom.md).

These files show the two ideas that defined v2: a **3-AI consensus gate** and a **portfolio of strategies**.

| File | What it is |
|------|-----------|
| `analysis/ensemble.py` | The 3-AI consensus gate (Claude + GPT + Gemini). Note the keys are constructor parameters — never hardcoded |
| `analysis/calibration.py` | Turning model confidence into a calibrated probability |
| `analysis/quant.py` | Quantitative helpers (edge/EV math) |
| `analysis/win_probability.py` | Win-probability estimation |
| `strategies/base.py` | The strategy interface for the fleet |
| `strategies/political.py` | The political-calibration strategy — the "logit-space compression" idea, the closest thing to a thesis with academic backing |
| `strategies/snipe.py` | Resolution sniping — buying near-certain outcomes for capital recycling |

> The lesson of this folder isn't in any single file — it's that a positive paper P&L from all of this (+$2,491 reported) was **BTC beta, not alpha**. The engineering is fine. The edge wasn't there.
