"""DivergenceEngine — detect tradeable gaps between external truth and Polymarket.

For sports, reuses the battle-tested `odds_client` consensus (devigged,
multi-book average) as `external_fair_prob` and compares it to the Polymarket
price. Edge is reported in percentage points, net of an estimated fee +
slippage.

HONESTY NOTE (anti-phantom-profit, the v1-v4 killer)
----------------------------------------------------
The Polymarket price returned by The Odds API (region `us_ex`) is an
aggregated MID, not the executable top-of-book ASK. Using a mid as if it were
the fill price is exactly the optimism that produced phantom backtest profits.
So we split the two concerns the engine measures:

  * PREDICTIVE calibration (Brier): external_fair vs realized outcome. Does
    NOT depend on the Polymarket price at all → fully valid in shadow today.
  * EXECUTABLE edge: external_fair vs the price we'd actually pay. In shadow
    we record it with `ask_source='odds_api_screen'` and
    `edge_executable_verified=False`. A category may calibrate predictively
    now, but GRADUATING IT TO LIVE additionally requires wiring the real CLOB
    top-of-book ask (clob_v2.get_order_book) — a hard gate, not a shortcut.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from polybot.analysis.odds_client import compute_consensus, find_polymarket_prices

log = structlog.get_logger()

# Rough taker-fee estimate for non-crypto categories (pp). Sports/politics on
# Polymarket are NOT subject to the punitive 15m-crypto dynamic fees.
DEFAULT_FEE_PP = 1.0
DEFAULT_SLIPPAGE_PP = 1.0


@dataclass(frozen=True)
class Divergence:
    """One detected gap. Immutable; persisted to oracle_divergences."""

    polymarket_id: str          # join key (event id until real condition_id wired)
    category: str
    side: str                   # 'YES' | 'NO'
    external_fair_prob: float
    poly_executable_ask: float  # screen price in shadow; real CLOB ask before live
    edge_pp: float
    fee_est: float = DEFAULT_FEE_PP
    slippage_est: float = DEFAULT_SLIPPAGE_PP
    feed_sources: dict[str, Any] = field(default_factory=dict)
    would_trade: bool = False
    max_feed_age_s: int | None = None
    decided_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


def compute_sports_divergences(
    events: list[dict],
    *,
    min_edge_pp: float,
    fee_pp: float = DEFAULT_FEE_PP,
    slippage_pp: float = DEFAULT_SLIPPAGE_PP,
) -> list[Divergence]:
    """From raw Odds-API events, build Divergences.

    `would_trade` is True only when the executable edge (after fee+slippage)
    clears `min_edge_pp`. Because the ask here is a screen mid, would_trade in
    shadow is advisory — graduation to live re-checks against the real CLOB.
    """
    out: list[Divergence] = []
    for event in events:
        consensus = compute_consensus(event.get("bookmakers", []))
        poly = find_polymarket_prices(event.get("bookmakers", []))
        if not consensus or not poly:
            continue
        event_id = event.get("id", "")
        sport = event.get("sport_key", "")
        for outcome, fair in consensus.items():
            if outcome not in poly:
                continue
            ask = float(poly[outcome])
            fair = float(fair)
            # Edge of BUYING this outcome on Polymarket vs our fair estimate.
            gross_edge_pp = (fair - ask) * 100.0
            net_edge_pp = gross_edge_pp - fee_pp - slippage_pp
            side = "YES" if gross_edge_pp > 0 else "NO"
            out.append(Divergence(
                polymarket_id=f"{sport}:{event_id}:{outcome}",
                category="sports",
                side=side,
                external_fair_prob=round(fair, 4),
                poly_executable_ask=round(ask, 4),
                edge_pp=round(net_edge_pp, 3),
                fee_est=fee_pp,
                slippage_est=slippage_pp,
                feed_sources={
                    "sports_odds": {"consensus": round(fair, 4)},
                    "ask_source": "odds_api_screen",
                    "edge_executable_verified": False,
                    "sport": sport,
                    "event_id": event_id,
                    "outcome": outcome,
                    "home_team": event.get("home_team", ""),
                    "away_team": event.get("away_team", ""),
                    "commence_time": event.get("commence_time", ""),
                },
                would_trade=net_edge_pp >= min_edge_pp,
            ))
    return out


async def persist_divergences(
    db: Any,
    divergences: list[Divergence],
    *,
    shadow_mode: bool,
) -> int:
    """Insert divergences into oracle_divergences. Returns rows written."""
    import json
    written = 0
    for d in divergences:
        try:
            await db.execute(
                """
                INSERT INTO oracle_divergences
                  (decided_at, polymarket_id, category, side,
                   external_fair_prob, poly_executable_ask, fee_est,
                   slippage_est, edge_pp, feed_sources, would_trade_bool,
                   shadow_mode, max_feed_age_s)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12,$13)
                """,
                d.decided_at, d.polymarket_id, d.category, d.side,
                d.external_fair_prob, d.poly_executable_ask, d.fee_est,
                d.slippage_est, d.edge_pp, json.dumps(d.feed_sources),
                d.would_trade, shadow_mode, d.max_feed_age_s,
            )
            written += 1
        except Exception as exc:  # noqa: BLE001
            log.error("divergence_persist_failed",
                      market=d.polymarket_id, err=str(exc)[:160])
    return written
