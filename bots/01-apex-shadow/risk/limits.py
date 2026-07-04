"""Hard limits — enforce maximum position, exposure, daily loss, and drawdown."""

import logging

logger = logging.getLogger(__name__)


class LimitsChecker:
    def __init__(self, config):
        self.max_position_per_market = config.max_position_per_market
        self.max_total_exposure = config.max_total_exposure
        self.max_daily_loss = config.max_daily_loss
        self.max_drawdown_pct = config.max_drawdown_pct

    def check_position_limit(self, current_size_usdc: float, new_size_usdc: float) -> bool:
        total = current_size_usdc + new_size_usdc
        if total > self.max_position_per_market:
            logger.warning("Position limit exceeded: %.2f > %.2f",
                           total, self.max_position_per_market)
            return False
        return True

    def check_total_exposure(self, current_exposure: float, new_exposure: float) -> bool:
        total = current_exposure + new_exposure
        if total > self.max_total_exposure:
            logger.warning("Total exposure limit exceeded: %.2f > %.2f",
                           total, self.max_total_exposure)
            return False
        return True

    def check_daily_loss(self, current_daily_pnl: float) -> bool:
        if current_daily_pnl < -self.max_daily_loss:
            logger.warning("Daily loss limit exceeded: %.2f < -%.2f",
                           current_daily_pnl, self.max_daily_loss)
            return False
        return True

    def check_drawdown(self, peak_pnl: float, current_pnl: float) -> bool:
        if peak_pnl <= 0:
            return True
        drawdown = (peak_pnl - current_pnl) / peak_pnl
        if drawdown > self.max_drawdown_pct:
            logger.warning("Drawdown limit exceeded: %.2f%% > %.2f%%",
                           drawdown * 100, self.max_drawdown_pct * 100)
            return False
        return True

    def can_trade(self, token_id: str, size_usdc: float, position_manager) -> bool:
        """Run all limit checks. Returns True if trade is allowed.

        Checks performed:
        1. Position limit — new trade must not push per-market exposure above max.
        2. Total exposure — aggregate portfolio exposure must stay within bounds.
        3. Daily loss — rejects trades if daily PnL already exceeds max daily loss.
        4. Drawdown — rejects trades if drawdown from peak PnL exceeds threshold.

        Returns True only if ALL four checks pass; False otherwise.
        """
        pos = position_manager.positions.get(token_id)
        current_pos_size = (pos.size * pos.avg_price) if pos else 0.0

        checks = [
            self.check_position_limit(current_pos_size, size_usdc),
            self.check_total_exposure(position_manager.net_exposure(), size_usdc),
            self.check_daily_loss(position_manager.daily_pnl),
            self.check_drawdown(position_manager.peak_pnl, position_manager.total_pnl()),
        ]
        return all(checks)
