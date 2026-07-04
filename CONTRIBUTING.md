# Contributing to the Graveyard

This is an open post-mortem. Contributions are welcome — and **negative results are first-class here.** There are two ways in.

## 🔬 Track 1 — Autopsy & discussion

The point of this repo is honest analysis. You can help make it better:

- **Challenge a diagnosis.** Think a "why it died" is wrong or incomplete? Open an issue with your reasoning. Being corrected is the whole spirit of this project.
- **Share your own post-mortem.** Built a prediction-market bot that failed? Tell the story. Use the [Share a post-mortem](.github/ISSUE_TEMPLATE/share_postmortem.yml) template. What you tried, what you assumed, how you measured, why it died.
- **Add structural context.** Know research, data, or a market-microstructure reason that explains why one of these edges decayed? That's gold. Link it.

No profit required. A well-documented failure is exactly what belongs here.

## ⚒️ Track 2 — Revive a strategy

Some of these bots were *close*. If you want to pick one up:

1. **Fork** the repo.
2. Pick a documented failure mode from a chapter in [`journey/`](journey/00-overview.md).
3. Fix it, and — this is the rule — **shadow-validate before you claim an edge.** Run it forward against real outcomes on a large, independent, multi-regime sample, net of fees, before you conclude anything. The [`calibration_gate.py`](bots/03-05-spectrix/oracle/calibration_gate.py) pattern exists for exactly this.
4. Report back with an [issue](.github/ISSUE_TEMPLATE/revive_strategy.yml) — including your forward numbers, honestly. A negative result is a valid, valuable result.

## Ground rules

- **Be honest with numbers.** Read results out of your database, not your bot's self-report. (Ours lied; assume yours does too.)
- **Never post secrets.** No API keys, wallet keys, seed phrases, or private RPC URLs in issues or PRs.
- **This is not investment advice** and contributions must not present it as such. See [DISCLAIMER.md](DISCLAIMER.md).
- Keep discussion technical and respectful.

## Editorial / docs PRs

Fixing a typo, tightening a chapter, or improving a diagram? Just open a PR. Prose lives under [CC BY 4.0](LICENSE-DOCS); code lives under [MIT](LICENSE).
