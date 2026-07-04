"""Momentum Sniper — detects rapid price movements and follows the trend.

Maintains a rolling window of midpoint prices per token. When the price moves
more than the configured threshold within the lookback window, generates a
FOK signal in the direction of the move.
"""

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Optional

from src.market_data.book_snapshot import Signal
from src.market_data.ws_client import WsPriceUpdate

logger = logging.getLogger(__name__)


@dataclass
class PricePoint:
    timestamp: float
    midpoint: float


class MomentumSniper:
    """Detects price momentum and generates entry signals."""

    def __init__(self, config):
        self.config = config
        self.threshold_pct = getattr(config, "momentum_threshold_pct", 0.02)
        self.window_seconds = getattr(config, "momentum_window_seconds", 30)
        self.cooldown_seconds = getattr(config, "momentum_cooldown_seconds", 120)
        self.sniper_size = getattr(config, "sniper_size", 5.0)

        # Per-token rolling price windows (keep 120s of data, check last 30s)
        self._prices: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._last_signal_time: Dict[str, float] = {}
        self._signals_generated: int = 0
        self._boot_time: float = time.time()
        self._warmup_seconds: float = 60.0  # ignore first 60s of data

    def on_price_update(self, update: WsPriceUpdate) -> Optional[Signal]:
        """Process a price update. Returns a momentum Signal if threshold exceeded."""
        now = update.timestamp or time.time()
        token_id = update.token_id

        # Warmup: ignore signals during first 60s to avoid false positives
        # from initial price data flooding in
        if now - self._boot_time < self._warmup_seconds:
            # Still record prices but don't generate signals
            self._prices[token_id].append(PricePoint(
                timestamp=now, midpoint=update.midpoint,
            ))
            return None

        # Record price
        self._prices[token_id].append(PricePoint(
            timestamp=now,
            midpoint=update.midpoint,
        ))

        # Prune entries older than 2x window
        window = self._prices[token_id]
        cutoff = now - (self.window_seconds * 2)
        while window and window[0].timestamp < cutoff:
            window.popleft()

        # Need at least 2 data points
        if len(window) < 2:
            return None

        # Find price at `window_seconds` ago
        target_time = now - self.window_seconds
        ref_price = None
        for pp in window:
            if pp.timestamp <= target_time:
                ref_price = pp.midpoint
            else:
                break

        # If we don't have a point far enough back, use oldest
        if ref_price is None:
            oldest = window[0]
            # Only use if it's at least half the window ago
            if now - oldest.timestamp < self.window_seconds * 0.5:
                return None
            ref_price = oldest.midpoint

        if ref_price <= 0:
            return None

        # Compute move
        current = update.midpoint
        move_pct = (current - ref_price) / ref_price

        if abs(move_pct) < self.threshold_pct:
            return None

        # Cooldown check
        last_signal = self._last_signal_time.get(token_id, 0)
        if now - last_signal < self.cooldown_seconds:
            return None

        # Generate signal
        side = "BUY" if move_pct > 0 else "SELL"
        self._last_signal_time[token_id] = now
        self._signals_generated += 1

        # Use the current ask for BUY, current bid for SELL
        price = update.best_ask if side == "BUY" else update.best_bid

        # Size in tokens
        size = self.sniper_size / price if price > 0 else self.sniper_size

        logger.info(
            "MOMENTUM: %s %.1f%% move on %s in %ds — %s @ %.3f",
            "+" if move_pct > 0 else "",
            move_pct * 100, token_id[:16],
            self.window_seconds, side, price,
        )

        return Signal(
            token_id=token_id,
            side=side,
            price=price,
            size=size,
            confidence=min(abs(move_pct) / self.threshold_pct * 0.5, 0.9),
            strategy_name="MomentumSniper",
            order_type="FOK",
        )

    def get_stats(self) -> dict:
        return {
            "signals_generated": self._signals_generated,
            "tokens_tracked": len(self._prices),
            "threshold_pct": self.threshold_pct,
            "window_seconds": self.window_seconds,
        }
