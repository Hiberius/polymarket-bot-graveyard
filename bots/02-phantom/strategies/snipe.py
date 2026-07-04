import json
import structlog
from datetime import datetime, timezone
from polybot.strategies.base import Strategy, TradingContext
from polybot.trading.risk import PortfolioState, TradeProposal, bankroll_kelly_adjustment
from polybot.trading.kelly import compute_position_size
from polybot.analysis.prompts import build_snipe_prompt, parse_snipe_response
from polybot.notifications.email import format_trade_email
from polybot.analysis.odds_client import compute_consensus

log = structlog.get_logger()


def classify_snipe_tier(price: float, hours_remaining: float, max_hours: float = 120.0) -> int | None:
    """
    Classify a market into snipe tiers based on price extremity and time remaining.

    Tier 0: Near-certain outcome, no LLM needed
    Tier 1: Likely resolved, LLM verification required
    Tier 2: Strong lean, conservative sizing
    Tier 3: Moderate lean, widest window, most conservative

    Returns None if not a snipe candidate.
    """
    if hours_remaining > max_hours or hours_remaining <= 0:
        return None

    # Tier 0: Very extreme prices, close to resolution (high confidence)
    if hours_remaining <= 24.0:
        if price >= 0.95 or price <= 0.05:
            return 0

    # Tier 1: Extreme prices, moderate time window (LLM verify)
    if hours_remaining <= 12.0:
        if price >= 0.85 or price <= 0.15:
            return 1

    # Tier 2: Strong lean, wider window (conservative)
    if hours_remaining <= 72.0:
        if price >= 0.80 or price <= 0.20:
            return 2

    # Tier 3: Moderate lean, widest window (most conservative)
    if hours_remaining <= 120.0:
        if price >= 0.75 or price <= 0.25:
            return 3

    return None


def compute_snipe_edge(buy_price: float, fee_per_dollar: float = 0.0) -> float:
    """
    Compute net edge for a snipe trade.

    For YES bets: edge = (1.0 - buy_price) - fee_per_dollar
    fee_per_dollar is 0.0 for maker orders, or feeRate*(1-price) for takers.
    """
    return (1.0 - buy_price) - fee_per_dollar


def compute_tiered_kelly_scale(net_edge: float) -> float:
    """Scale Kelly multiplier based on edge magnitude. Higher edge = larger position."""
    if net_edge >= 0.05:
        return 2.0
    if net_edge >= 0.03:
        return 1.5
    return 1.0


def check_snipe_cooldown(
    polymarket_id: str,
    current_price: float,
    cooldowns: dict[str, dict],
    cooldown_hours: float,
    reentry_threshold: float,
) -> bool:
    """Return True if the market is clear to enter, False if blocked by cooldown."""
    if polymarket_id not in cooldowns:
        return True
    entry = cooldowns[polymarket_id]
    elapsed_hours = (datetime.now(timezone.utc) - entry["exit_time"]).total_seconds() / 3600
    if elapsed_hours >= cooldown_hours:
        return True
    # Still in cooldown — check if price moved enough for re-entry
    price_delta = abs(current_price - entry["exit_price"])
    return price_delta >= reentry_threshold


async def verify_snipe_via_odds(
    odds_client,
    question: str,
    side: str,
    min_consensus: float = 0.85,
) -> bool:
    """Verify a snipe candidate using sportsbook consensus instead of LLM.

    Searches The Odds API events for a matching event by team name,
    then checks if the sportsbook consensus supports the snipe direction.

    Returns True if sportsbook consensus confirms the snipe, False otherwise.
    """
    if odds_client.credits_exhausted:
        return False
    q_lower = question.lower()

    for sport in ["basketball_nba", "icehockey_nhl", "soccer_epl",
                   "soccer_uefa_champs_league", "soccer_usa_mls"]:
        try:
            events = await odds_client.fetch_odds(sport)
        except Exception:
            continue

        for event in events:
            home = event.get("home_team", "").lower()
            away = event.get("away_team", "").lower()

            matched_team = None
            if home and home in q_lower:
                matched_team = event.get("home_team")
            elif away and away in q_lower:
                matched_team = event.get("away_team")

            if not matched_team:
                continue

            consensus = compute_consensus(event.get("bookmakers", []))
            if not consensus or matched_team not in consensus:
                continue

            team_prob = consensus[matched_team]

            if side == "YES" and team_prob >= min_consensus:
                log.info("snipe_odds_verified", team=matched_team,
                         consensus=round(team_prob, 3), side=side)
                return True
            elif side == "NO" and team_prob <= (1.0 - min_consensus):
                log.info("snipe_odds_verified", team=matched_team,
                         consensus=round(team_prob, 3), side=side)
                return True

    return False


class ResolutionSnipeStrategy(Strategy):
    name = "snipe"

    def __init__(self, settings, ensemble=None, odds_client=None):
        self.interval_seconds = settings.snipe_interval_seconds
        self.kelly_multiplier = settings.snipe_kelly_mult
        self.max_single_pct = settings.snipe_max_single_pct
        self._min_net_edge = settings.snipe_min_net_edge
        self._min_confidence = settings.snipe_min_confidence
        self._max_hours = settings.snipe_hours_max
        self._use_maker = settings.use_maker_orders
        self._ensemble = ensemble
        self._cooldown_hours = settings.snipe_cooldown_hours
        self._reentry_threshold = settings.snipe_reentry_threshold
        self._max_entries_per_market = settings.snipe_max_entries_per_market
        self._market_cooldowns: dict[str, dict] = {}
        self._odds_client = odds_client
        self._odds_verification_enabled = getattr(settings, 'snipe_odds_verification_enabled', False)
        self._odds_min_consensus = getattr(settings, 'snipe_odds_min_consensus', 0.85)
        self._max_concurrent = getattr(settings, 'snipe_max_concurrent', 3)

    async def run_once(self, ctx: TradingContext) -> None:
        enabled = await ctx.db.fetchval(
            "SELECT enabled FROM strategy_performance WHERE strategy = 'snipe'")
        if enabled is False:
            return

        # Check concurrent position cap
        open_snipe_count = await ctx.db.fetchval(
            """SELECT COUNT(*) FROM trades
               WHERE strategy = 'snipe'
                 AND status IN ('open', 'filled', 'dry_run')""")
        if (open_snipe_count or 0) >= self._max_concurrent:
            log.info("snipe_max_concurrent_reached", open=open_snipe_count,
                     max=self._max_concurrent)
            return

        # Refresh per-market cooldowns from recently closed snipe trades
        recent_exits = await ctx.db.fetch(
            """SELECT m.polymarket_id, t.closed_at, t.exit_price
               FROM trades t JOIN markets m ON t.market_id = m.id
               WHERE t.strategy = 'snipe'
                 AND t.status IN ('dry_run_resolved', 'closed')
                 AND t.closed_at > NOW() - INTERVAL '24 hours'
               ORDER BY t.closed_at DESC""")
        for row in recent_exits:
            pid = row["polymarket_id"]
            if pid not in self._market_cooldowns or row["closed_at"] > self._market_cooldowns[pid]["exit_time"]:
                self._market_cooldowns[pid] = {
                    "exit_time": row["closed_at"],
                    "exit_price": float(row["exit_price"]),
                }

        # Load learned snipe parameters
        snipe_learned = await ctx.db.fetchval(
            "SELECT learned_params FROM strategy_performance WHERE strategy = 'snipe'")
        if snipe_learned:
            try:
                import json
                sp = json.loads(snipe_learned) if isinstance(snipe_learned, str) else snipe_learned
                if sp.get("snipe_sample_size", 0) >= 5:
                    learned_edge = sp.get("optimal_min_edge")
                    if learned_edge is not None:
                        self._min_net_edge = max(0.01, min(0.10, learned_edge))
                        log.debug("snipe_learned_edge", min_edge=self._min_net_edge)
            except (json.JSONDecodeError, TypeError):
                pass

        raw_markets = await ctx.scanner.fetch_markets()
        now = datetime.now(timezone.utc)

        # Pre-fetch bankroll for cumulative exposure checks (avoids lock per candidate)
        state_row = await ctx.db.fetchrow("SELECT bankroll FROM system_state WHERE id = 1")
        bankroll_snapshot = float(state_row["bankroll"]) if state_row else 0.0
        max_market_exposure_pct = getattr(ctx.settings, "snipe_max_market_exposure_pct", 0.30)

        snipe_candidates = 0
        for m in raw_markets:
            hours_remaining = (m["resolution_time"] - now).total_seconds() / 3600
            tier = classify_snipe_tier(m["yes_price"], hours_remaining, self._max_hours)
            if tier is None:
                continue

            snipe_candidates += 1
            log.info("snipe_candidate", market=m["polymarket_id"],
                     price=m["yes_price"], hours=round(hours_remaining, 1), tier=tier)

            if m["yes_price"] >= 0.75:
                side, buy_price = "YES", m["yes_price"]
            elif m["yes_price"] <= 0.25:
                side, buy_price = "NO", 1 - m["yes_price"]
            else:
                log.debug("snipe_rejected_price_range", market=m["polymarket_id"],
                          price=m["yes_price"])
                continue

            from polybot.trading.fees import get_fee_rate, compute_taker_fee_per_dollar
            category = m.get("category", "unknown")
            if self._use_maker:
                fee_per_dollar = 0.0
            else:
                fee_per_dollar = compute_taker_fee_per_dollar(buy_price, get_fee_rate(category))
            net_edge = compute_snipe_edge(buy_price, fee_per_dollar)
            if net_edge < self._min_net_edge:
                log.debug("snipe_rejected_edge", market=m["polymarket_id"],
                          edge=round(net_edge, 4), min_edge=self._min_net_edge)
                continue

            # Per-market cooldown check
            if not check_snipe_cooldown(
                m["polymarket_id"], buy_price, self._market_cooldowns,
                self._cooldown_hours, self._reentry_threshold,
            ):
                log.debug("snipe_cooldown_blocked", market=m["polymarket_id"])
                continue

            # 24h entry cap per market
            entries_24h = await ctx.db.fetchval(
                """SELECT COUNT(*) FROM trades t JOIN markets m ON t.market_id = m.id
                   WHERE m.polymarket_id = $1 AND t.strategy = 'snipe'
                     AND t.opened_at > NOW() - INTERVAL '24 hours'""",
                m["polymarket_id"])
            if entries_24h and entries_24h >= self._max_entries_per_market:
                log.debug("snipe_entry_cap", market=m["polymarket_id"],
                          entries=entries_24h, max=self._max_entries_per_market)
                continue

            # Per-market cumulative USD exposure cap
            cumulative_exposure = await ctx.db.fetchval(
                """SELECT COALESCE(SUM(position_size_usd), 0) FROM trades t
                   JOIN markets m2 ON t.market_id = m2.id
                   WHERE m2.polymarket_id = $1 AND t.strategy = 'snipe'
                     AND t.status IN ('open', 'filled', 'dry_run')""",
                m["polymarket_id"])
            max_market_exposure = bankroll_snapshot * max_market_exposure_pct
            if float(cumulative_exposure) >= max_market_exposure:
                log.debug("snipe_cumulative_cap", market=m["polymarket_id"],
                          exposure=float(cumulative_exposure), max=round(max_market_exposure, 2))
                continue

            if tier in (1, 2, 3):
                verified = False

                # Try odds-based verification first (faster, cheaper, no LLM)
                if self._odds_client and self._odds_verification_enabled:
                    try:
                        verified = await verify_snipe_via_odds(
                            odds_client=self._odds_client,
                            question=m["question"],
                            side=side,
                            min_consensus=self._odds_min_consensus,
                        )
                        if verified:
                            log.info("snipe_verified_via_odds", market=m["polymarket_id"],
                                     tier=tier, side=side)
                    except Exception as e:
                        log.error("snipe_odds_verify_error", error=str(e))

                # Fall back to LLM if odds verification didn't confirm
                if not verified and self._ensemble:
                    tier_max_hours = {1: 12.0, 2: getattr(ctx.settings, "snipe_tier2_llm_max_hours", 48.0), 3: getattr(ctx.settings, "snipe_tier3_llm_max_hours", 120.0)}
                    if hours_remaining > tier_max_hours.get(tier, 12.0):
                        log.info("snipe_rejected_far_future", market=m["polymarket_id"],
                                 hours=round(hours_remaining, 1), tier=tier)
                        continue
                    prompt = build_snipe_prompt(m["question"], str(m["resolution_time"]), hours_remaining, m["yes_price"])
                    try:
                        response = await self._ensemble._google.aio.models.generate_content(
                            model="gemini-2.5-flash", contents=prompt)
                        parsed = parse_snipe_response(response.text)
                        if not parsed or not parsed["determined"] or parsed["confidence"] < self._min_confidence:
                            log.info("snipe_rejected_llm", market=m["polymarket_id"],
                                     tier=tier, parsed=parsed)
                            continue
                        if parsed["outcome"] == "NO" and side == "YES":
                            log.info("snipe_rejected_llm_disagree", market=m["polymarket_id"],
                                     side=side, llm_outcome=parsed["outcome"])
                            continue
                        if parsed["outcome"] == "YES" and side == "NO":
                            log.info("snipe_rejected_llm_disagree", market=m["polymarket_id"],
                                     side=side, llm_outcome=parsed["outcome"])
                            continue
                        verified = True
                    except Exception as e:
                        log.error("snipe_llm_error", error=str(e))
                        continue

                if not verified:
                    log.debug("snipe_not_verified", market=m["polymarket_id"], tier=tier)
                    continue

            async with ctx.portfolio_lock:
                state_row = await ctx.db.fetchrow("SELECT * FROM system_state WHERE id = 1")
                if not state_row:
                    continue
                bankroll = float(state_row["bankroll"])
                kelly_adj = bankroll_kelly_adjustment(
                    bankroll=bankroll, base_kelly=self.kelly_multiplier,
                    post_breaker_until=state_row.get("post_breaker_until"),
                    post_breaker_reduction=ctx.settings.post_breaker_kelly_reduction,
                    survival_threshold=ctx.settings.bankroll_survival_threshold,
                    growth_threshold=ctx.settings.bankroll_growth_threshold,
                )
                # Tier-dependent kelly scaling
                tier_kelly_scale = {0: 1.0, 1: 0.85, 2: 0.55, 3: 0.30}
                kelly_adj *= tier_kelly_scale.get(tier, 1.0)
                # Tiered edge sizing: larger positions on higher edge
                kelly_adj *= compute_tiered_kelly_scale(net_edge)
                kelly_fraction = net_edge / (1 - buy_price) if buy_price < 1.0 else 0.0
                size = compute_position_size(
                    bankroll=bankroll, kelly_fraction=kelly_fraction, kelly_mult=kelly_adj,
                    confidence_mult=1.0, max_single_pct=self.max_single_pct,
                    min_trade_size=ctx.settings.min_trade_size)
                if size <= 0:
                    log.debug("snipe_rejected_size_zero", market=m["polymarket_id"])
                    continue

                open_trades = await ctx.db.fetch("SELECT * FROM trades WHERE status = 'open'")
                portfolio = PortfolioState(
                    bankroll=bankroll, total_deployed=float(state_row["total_deployed"]),
                    daily_pnl=float(state_row["daily_pnl"]),
                    open_count=len(open_trades), category_deployed={},
                    circuit_breaker_until=state_row.get("circuit_breaker_until"))
                proposal = TradeProposal(size_usd=size, category=m.get("category", "unknown"),
                                          book_depth=m.get("book_depth", 1000.0))
                risk_result = ctx.risk_manager.check(portfolio, proposal, max_single_pct=self.max_single_pct)
                if not risk_result.allowed:
                    log.info("snipe_rejected_risk", market=m["polymarket_id"],
                             reason=risk_result.reason)
                    continue

                # Upsert market record
                market_id = await ctx.db.fetchval(
                    """INSERT INTO markets (polymarket_id, question, category, resolution_time,
                           current_price, volume_24h, book_depth)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       ON CONFLICT (polymarket_id) DO UPDATE SET
                           current_price=$5, volume_24h=$6, book_depth=$7, last_updated=NOW()
                       RETURNING id""",
                    m["polymarket_id"], m["question"], m.get("category", "unknown"),
                    m["resolution_time"], m["yes_price"],
                    m.get("volume_24h"), m.get("book_depth"),
                )

                # Create analysis record for the snipe
                # Store target probability (1.0 for YES, 0.0 for NO) — snipes
                # assume the outcome will resolve as expected.
                snipe_target_prob = 1.0 if side == "YES" else 0.0
                analysis_id = await ctx.db.fetchval(
                    """INSERT INTO analyses (market_id, model_estimates, ensemble_probability,
                       ensemble_stdev, quant_signals, edge)
                       VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                    market_id, json.dumps([]), snipe_target_prob, 0.0, json.dumps({}), net_edge,
                )

                token_id = m.get("yes_token_id", "") if side == "YES" else m.get("no_token_id", "")
                result = await ctx.executor.place_order(
                    token_id=token_id, side=side, size_usd=size,
                    price=buy_price, market_id=market_id,
                    analysis_id=analysis_id, strategy=self.name,
                    post_only=self._use_maker,
                )
                if not result:
                    continue

            log.info("snipe_trade", market=m["polymarket_id"], side=side, price=buy_price,
                     edge=net_edge, size=size, tier=tier)
            await ctx.email_notifier.send(
                f"[POLYBOT] Trade executed: {m['question'][:60]}",
                format_trade_email(event="executed", market=m["question"], side=side,
                                   size=size, price=buy_price, edge=net_edge))

        log.info("snipe_cycle_complete", markets_scanned=len(raw_markets),
                 candidates=snipe_candidates)
