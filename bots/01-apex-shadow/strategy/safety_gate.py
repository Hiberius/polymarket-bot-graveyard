"""Safety Gate — unified pre-trade safety checks for all sniper strategies.

Every signal passes through this gate before execution. Checks:
1. VPIN toxicity threshold
2. Minimum USDC balance
3. Inventory guard (no SELL without tokens)
4. Daily trade limit
5. Per-trade size cap and notional floor
"""

import logging
import time
from typing import Dict, Tuple

from src.market_data.book_snapshot import Signal
from src.risk.vpin import VPINCalculator

logger = logging.getLogger(__name__)


class SafetyGate:
    def __init__(self, config, vpin_trackers: Dict[str, VPINCalculator],
                 position_manager, client):
        self.config = config
        self.vpin_trackers = vpin_trackers
        self.position_manager = position_manager
        self.client = client

        self.vpin_halt_threshold = getattr(config, "vpin_halt_threshold", 0.85)
        self.min_balance = getattr(config, "min_balance_usdc", 5.0)
        self.max_daily_trades = getattr(config, "max_daily_trades", 20)
        self.max_trade_size = getattr(config, "max_trade_size", 5.0)

        self._trades_today: int = 0
        self._day_start: float = time.time()
        self._cached_balance: float = 0.0
        self._balance_ts: float = 0.0

    def check(self, signal: Signal) -> Tuple[bool, str]:
        """Check if a signal is safe to execute.

        Returns (allowed, reason_if_blocked).
        """
        # Reset daily counter at midnight
        now = time.time()
        if now - self._day_start > 86400:
            self._trades_today = 0
            self._day_start = now

        # 1. VPIN check
        vpin = self.vpin_trackers.get(signal.token_id)
        if vpin and vpin.vpin > self.vpin_halt_threshold:
            return False, f"VPIN too high ({vpin.vpin:.2f} > {self.vpin_halt_threshold})"

        # 2. Balance guard (refresh every 30s)
        if now - self._balance_ts > 30:
            try:
                self._cached_balance = self.client.get_usdc_balance()
                self._balance_ts = now
            except Exception as e:
                logger.warning("Balance check failed: %s", e)

        # 2b. Balance guard — block BUYs when low, always allow SELLs
        if self._cached_balance < self.min_balance and signal.side.upper() == "BUY":
            return False, f"Balance too low for BUY (${self._cached_balance:.2f} < ${self.min_balance})"

        # 3. Inventory guard — no SELL without tokens
        if signal.side.upper() == "SELL":
            inv = self.position_manager.get_inventory_count(signal.token_id)
            if inv <= 0:
                return False, "SELL blocked: no inventory"

        # 4. Daily trade limit
        if self._trades_today >= self.max_daily_trades:
            return False, f"Daily trade limit reached ({self.max_daily_trades})"

        # 5. Bankroll-scaled size cap
        effective_max = self._bankroll_scaled_size()
        if signal.size > effective_max:
            signal.size = effective_max

        # 6. Notional floor (Polymarket minimum order ~$0.10)
        notional = signal.size * signal.price
        if notional < 0.50:
            return False, f"Notional too small (${notional:.2f} < $0.50)"

        return True, ""

    def _bankroll_scaled_size(self) -> float:
        """Scale max trade size based on current balance.

        < $40:  SURVIVAL mode — max $1/trade
        $40-$200: NORMAL — use configured max_trade_size
        > $200: SCALE — double the max to $10/trade
        """
        bal = self._cached_balance
        if bal < 40.0:
            return min(self.max_trade_size, 1.0)
        elif bal > 200.0:
            return min(self.max_trade_size * 2, 10.0)
        return self.max_trade_size

    def record_trade(self) -> None:
        """Call after a successful trade execution."""
        self._trades_today += 1

    def get_stats(self) -> dict:
        bal = self._cached_balance
        mode = "SURVIVAL" if bal < 40 else "SCALE" if bal > 200 else "NORMAL"
        return {
            "trades_today": self._trades_today,
            "max_daily_trades": self.max_daily_trades,
            "cached_balance": round(self._cached_balance, 2),
            "vpin_halt_threshold": self.vpin_halt_threshold,
            "bankroll_mode": mode,
            "effective_max_size": self._bankroll_scaled_size(),
        }
