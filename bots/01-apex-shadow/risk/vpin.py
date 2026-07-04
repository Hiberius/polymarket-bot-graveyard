"""VPIN — Volume-Synchronized Probability of Informed Trading.

Detects 'toxic' order flow (informed traders / smart money) by measuring
the imbalance between buy and sell volume in fixed-size buckets.

When VPIN exceeds threshold, the bot should:
1. Widen spreads (defensive) or
2. Switch to trend-following mode (ride the informed flow)
"""

import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VolumeBar:
    """One volume bucket."""
    buy_volume: float = 0.0
    sell_volume: float = 0.0


class VPINCalculator:
    """Calculates VPIN in real-time from order book snapshots.

    VPIN = Σ|V_buy - V_sell| / (n * V_bucket)

    High VPIN (> 0.7) = informed traders are active → danger for market makers.
    Low VPIN (< 0.3) = normal flow → safe to provide liquidity.
    """

    def __init__(self, bucket_size: float = 100.0, n_buckets: int = 50,
                 toxic_threshold: float = 0.7):
        self.bucket_size = bucket_size  # USDC per bucket
        self.n_buckets = n_buckets
        self.toxic_threshold = toxic_threshold

        self.buckets: deque = deque(maxlen=n_buckets)
        self.current_bucket = VolumeBar()
        self.current_bucket_volume: float = 0.0
        self.last_vpin: float = 0.0

    def update(self, trade_side: str, volume: float) -> None:
        """Process a trade event. Side is 'BUY' or 'SELL'."""
        remaining = volume

        while remaining > 0:
            space = self.bucket_size - self.current_bucket_volume
            fill = min(remaining, space)

            if trade_side == "BUY":
                self.current_bucket.buy_volume += fill
            else:
                self.current_bucket.sell_volume += fill

            self.current_bucket_volume += fill
            remaining -= fill

            if self.current_bucket_volume >= self.bucket_size:
                self.buckets.append(self.current_bucket)
                self.current_bucket = VolumeBar()
                self.current_bucket_volume = 0.0
                self.last_vpin = self._compute_vpin()

    def update_from_snapshot(self, bid_vol: float, ask_vol: float) -> None:
        """Approximate VPIN from order book imbalance (when we don't have trade data).

        Uses volume imbalance as a proxy for buy/sell classification.
        """
        total = bid_vol + ask_vol
        if total <= 0:
            return

        # Lee-Ready classification proxy: if bids > asks, net buying pressure
        buy_pct = bid_vol / total
        effective_volume = min(total, self.bucket_size)

        self.update("BUY", effective_volume * buy_pct)
        self.update("SELL", effective_volume * (1 - buy_pct))

    def _compute_vpin(self) -> float:
        """VPIN = Σ|V_buy - V_sell| / (n * V_bucket)"""
        if len(self.buckets) < 5:
            return 0.0

        total_imbalance = sum(
            abs(b.buy_volume - b.sell_volume) for b in self.buckets
        )
        return total_imbalance / (len(self.buckets) * self.bucket_size)

    @property
    def is_toxic(self) -> bool:
        """Returns True if flow is likely informed (smart money active)."""
        return self.last_vpin > self.toxic_threshold

    @property
    def vpin(self) -> float:
        return self.last_vpin

    def get_regime(self) -> str:
        """Determine market regime from VPIN."""
        if self.last_vpin > self.toxic_threshold:
            return "TOXIC"  # smart money active, widen spreads or trend-follow
        elif self.last_vpin > 0.4:
            return "CAUTIOUS"  # elevated, moderate spread widening
        else:
            return "NORMAL"  # safe to provide liquidity

    def get_smart_money_direction(self) -> str:
        """Determine which direction smart money is pushing.

        Returns 'BUY' if buy volume dominates, 'SELL' if sell dominates, 'NEUTRAL' otherwise.
        """
        if len(self.buckets) < 3:
            return "NEUTRAL"

        # Look at last 5 buckets
        recent = list(self.buckets)[-5:]
        total_buy = sum(b.buy_volume for b in recent)
        total_sell = sum(b.sell_volume for b in recent)
        total = total_buy + total_sell

        if total <= 0:
            return "NEUTRAL"

        buy_pct = total_buy / total
        if buy_pct > 0.65:
            return "BUY"
        elif buy_pct < 0.35:
            return "SELL"
        return "NEUTRAL"
