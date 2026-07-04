"""Political/geopolitical calibration strategy.

Scans Polymarket for political markets and trades the calibration gap.
Academic research shows political prediction markets have a systematic
compression bias (slope ~1.31), meaning prices cluster toward 0.50 more
than true probabilities warrant. A 70-cent market is actually ~83% likely.

This strategy exploits that bias by:
  1. Scanning all open markets for political/geopolitical tags
  2. Computing the calibration-adjusted true probability
  3. Calculating edge = |true_prob - market_price|
  4. Sizing positions via Kelly criterion when edge > min_edge

Reference: "Domain-Specific Calibration Dynamics in Prediction Markets"
(arxiv.org/html/2602.19520v1)
"""

import json
import structlog
from datetime import datetime, timezone

from polybot.strategies.base import Strategy, TradingContext
from polybot.analysis.calibration import (
    is_political_market,
    calibration_adjusted_prob,
    get_domain_slope,
)
from polybot.trading.kelly import compute_kelly, compute_position_size
from polybot.trading.risk import PortfolioState, TradeProposal, bankroll_kelly_adjustment
from polybot.notifications.email import format_trade_email

log = structlog.get_logger()


class PoliticalStrategy(Strategy):
    """Trade calibration gaps in political/geopolitical markets."""

    name = "political"

    def __init__(self, settings, ensemble=None):
        self.interval_seconds = getattr(settings, "pol_interval_seconds", 600)
        self.kelly_multiplier = getattr(settings, "pol_kelly_mult", 0.40)
        self.max_single_pct = getattr(settings, "pol_max_single_pct", 0.20)
        self._min_edge = getattr(settings, "pol_min_edge", 0.04)
        self._min_liquidity = getattr(settings, "pol_min_liquidity", 50_000)
        self._max_positions = getattr(settings, "pol_max_positions", 5)
        self._llm_confirm_edge = float(getattr(settings, "pol_llm_confirm_edge", 0.10))
        self._settings = settings
        self._ensemble = ensemble

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run_once(self, ctx: TradingContext) -> None:
        # 1. Strategy-level enable gate
        enabled = await ctx.db.fetchval(
            "SELECT enabled FROM strategy_performance WHERE strategy = $1",
            self.name,
        )
        if enabled is False:
            log.debug("pol_disabled")
            return

        # 2. Bankroll
        state = await ctx.db.fetchrow("SELECT * FROM system_state WHERE id = 1")
        if not state:
            log.warning("pol_no_system_state")
            return

        # 3. Check circuit breaker early — avoids pointless market scan
        circuit_breaker_until = state.get("circuit_breaker_until")
        if circuit_breaker_until:
            if isinstance(circuit_breaker_until, datetime):
                now = datetime.now(timezone.utc)
                if circuit_breaker_until > now:
                    log.info("pol_circuit_breaker_active",
                             until=str(circuit_breaker_until))
                    return

        bankroll = float(state["bankroll"])

        # 4. Position cap
        open_count = await ctx.db.fetchval(
            """SELECT COUNT(*) FROM trades
               WHERE strategy = $1
                 AND status IN ('open', 'filled', 'dry_run')""",
            self.name,
        )
        open_count = open_count or 0
        slots = self._max_positions - open_count
        if slots <= 0:
            log.debug("pol_position_cap_reached", open=open_count, max=self._max_positions)
            return

        # 5. Fetch and filter markets
        markets = await ctx.scanner.fetch_markets()
        if not markets:
            log.debug("pol_no_markets_returned")
            return

        now = datetime.now(timezone.utc)
        political_markets = []
        for m in markets:
            if not is_political_market(m.get("tags", [])):
                continue
            if m.get("book_depth", 0) < self._min_liquidity:
                continue
            hours_left = (m["resolution_time"] - now).total_seconds() / 3600
            if hours_left <= 24:
                continue
            political_markets.append(m)

        log.info("pol_scan", total=len(markets), political=len(political_markets))

        if not political_markets:
            return

        # 6 & 7. Score each market: pick the best side (YES or NO)
        opportunities = []
        for m in political_markets:
            tags = m.get("tags", [])
            slope = get_domain_slope(tags)
            yes_price = m.get("yes_price", 0.50)

            true_prob = calibration_adjusted_prob(yes_price, slope)

            yes_edge = true_prob - yes_price
            no_edge = (1.0 - true_prob) - (1.0 - yes_price)

            if yes_edge >= no_edge and yes_edge > self._min_edge:
                opportunities.append({
                    "market": m,
                    "side": "YES",
                    "true_prob": true_prob,
                    "market_price": yes_price,
                    "edge": yes_edge,
                    "slope": slope,
                })
            elif no_edge > self._min_edge:
                opportunities.append({
                    "market": m,
                    "side": "NO",
                    "true_prob": true_prob,
                    "market_price": yes_price,
                    "edge": no_edge,
                    "slope": slope,
                })

        if not opportunities:
            log.debug("pol_no_edge", markets_checked=len(political_markets),
                      min_edge=self._min_edge)
            return

        # 8. Sort by edge descending, take top `slots`
        opportunities.sort(key=lambda x: x["edge"], reverse=True)
        candidates = opportunities[:slots]

        # 9. Dedup against existing open positions on the same market
        existing_rows = await ctx.db.fetch(
            """SELECT m.polymarket_id
               FROM trades t JOIN markets m ON t.market_id = m.id
               WHERE t.strategy = $1
                 AND t.status IN ('open', 'filled', 'dry_run')""",
            self.name,
        )
        existing_pids = {row["polymarket_id"] for row in (existing_rows or [])}

        for opp in candidates:
            pid = opp["market"].get("polymarket_id", "")
            if pid in existing_pids:
                log.debug("pol_dedup_skip", market=pid)
                continue

            await self._execute_trade(opp, bankroll, state, ctx)
            existing_pids.add(pid)  # prevent double-entry within this run

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------

    async def _execute_trade(self, opp: dict, bankroll: float, state, ctx: TradingContext) -> None:
        market = opp["market"]
        true_prob = opp["true_prob"]
        market_price = opp["market_price"]
        edge = opp["edge"]
        slope = opp["slope"]
        side = opp["side"]

        # Optional LLM confirmation for high-edge trades
        if self._ensemble and edge >= self._llm_confirm_edge:
            try:
                quick_prob = await self._ensemble.quick_screen(
                    market["question"], market["yes_price"],
                    market["resolution_time"].isoformat() if hasattr(market["resolution_time"], "isoformat") else str(market["resolution_time"]))
                if quick_prob is not None:
                    # Does LLM agree with our calibration direction?
                    llm_agrees = (side == "YES" and quick_prob > market["yes_price"]) or \
                                 (side == "NO" and quick_prob < market["yes_price"])
                    if not llm_agrees:
                        log.info("pol_llm_disagrees", market=market.get("polymarket_id"),
                                 side=side, calibration_edge=round(edge, 4),
                                 llm_prob=round(quick_prob, 4),
                                 market_price=market["yes_price"])
                        return
                    log.info("pol_llm_confirms", market=market.get("polymarket_id"),
                             side=side, llm_prob=round(quick_prob, 4))
            except Exception as e:
                log.warning("pol_llm_error", market=market.get("polymarket_id"), error=str(e))
                # Continue without LLM confirmation on error

        # 1. Kelly computation (maker orders → fee=0.0)
        kelly_result = compute_kelly(true_prob, market_price, fee_per_dollar=0.0)
        if kelly_result.kelly_fraction <= 0:
            log.debug("pol_zero_kelly", market=market.get("polymarket_id"))
            return

        # 2. Bankroll-tier adjustment
        kelly_adj = bankroll_kelly_adjustment(
            bankroll=bankroll,
            base_kelly=self.kelly_multiplier,
            post_breaker_until=state.get("post_breaker_until"),
            post_breaker_reduction=getattr(
                self._settings, "post_breaker_kelly_reduction", 0.50
            ),
            survival_threshold=getattr(
                self._settings, "bankroll_survival_threshold", 50.0
            ),
            growth_threshold=getattr(
                self._settings, "bankroll_growth_threshold", 500.0
            ),
        )

        # 3. Position size
        size = compute_position_size(
            bankroll=bankroll,
            kelly_fraction=kelly_result.kelly_fraction,
            kelly_mult=kelly_adj,
            confidence_mult=1.0,
            max_single_pct=self.max_single_pct,
            min_trade_size=getattr(self._settings, "min_trade_size", 1.0),
        )
        if size <= 0:
            log.debug("pol_zero_size", market=market.get("polymarket_id"))
            return

        pid = market.get("polymarket_id", "")

        # 4. Risk check (inside portfolio lock)
        async with ctx.portfolio_lock:
            open_trades = await ctx.db.fetch(
                """SELECT t.position_size_usd, m.category
                   FROM trades t JOIN markets m ON t.market_id = m.id
                   WHERE t.status IN ('open', 'filled', 'dry_run')""",
            )
            cat_deployed: dict[str, float] = {}
            for t in open_trades:
                cat = t["category"]
                cat_deployed[cat] = cat_deployed.get(cat, 0.0) + float(t["position_size_usd"])

            portfolio = PortfolioState(
                bankroll=bankroll,
                total_deployed=float(state["total_deployed"]),
                daily_pnl=float(state["daily_pnl"]),
                open_count=len(open_trades),
                category_deployed=cat_deployed,
                circuit_breaker_until=state.get("circuit_breaker_until"),
            )
            proposal = TradeProposal(
                size_usd=size,
                category=market.get("category", "politics"),
                book_depth=market.get("book_depth", self._min_liquidity),
            )
            risk_result = ctx.risk_manager.check(
                portfolio, proposal, max_single_pct=self.max_single_pct
            )
            if not risk_result.allowed:
                log.info("pol_risk_rejected",
                         market=pid, reason=risk_result.reason,
                         edge=round(edge, 4), size=size)
                return

            # 5a. Upsert market
            market_id = await ctx.db.fetchval(
                """INSERT INTO markets (polymarket_id, question, category, resolution_time,
                       current_price, volume_24h, book_depth)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)
                   ON CONFLICT (polymarket_id) DO UPDATE SET
                       current_price=$5, volume_24h=$6, book_depth=$7, last_updated=NOW()
                   RETURNING id""",
                pid,
                market.get("question", ""),
                market.get("category", "politics"),
                market.get("resolution_time"),
                market_price,
                market.get("volume_24h"),
                market.get("book_depth"),
            )

            # 5b. Analysis record
            kelly_inputs = {
                "true_prob": true_prob,
                "market_price": market_price,
                "edge": edge,
                "slope": slope,
                "source": "calibration",
            }
            analysis_id = await ctx.db.fetchval(
                """INSERT INTO analyses (market_id, model_estimates, ensemble_probability,
                   ensemble_stdev, quant_signals, edge)
                   VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                market_id,
                json.dumps([]),
                true_prob,
                0.0,
                json.dumps(kelly_inputs),
                edge,
            )

            # 5c. Place order
            if side == "YES":
                token_id = market.get("yes_token_id", "")
                buy_price = market_price
            else:
                token_id = market.get("no_token_id", "")
                buy_price = 1.0 - market_price

            result = await ctx.executor.place_order(
                token_id=token_id,
                side=side,
                size_usd=size,
                price=buy_price,
                market_id=market_id,
                analysis_id=analysis_id,
                strategy=self.name,
                kelly_inputs=kelly_inputs,
                post_only=getattr(self._settings, "use_maker_orders", True),
            )
            if not result:
                log.warning("pol_order_failed", market=pid)
                return

        log.info(
            "pol_trade",
            market=pid,
            side=side,
            edge=round(edge, 4),
            true_prob=round(true_prob, 4),
            market_price=round(market_price, 4),
            slope=slope,
            size=size,
        )

        # 6. Email notification
        await ctx.email_notifier.send(
            f"[POLYBOT] Political: {market.get('question', pid)[:60]}",
            format_trade_email(
                event="executed",
                market=market.get("question", pid),
                side=side,
                size=size,
                price=buy_price,
                edge=edge,
            ),
        )
