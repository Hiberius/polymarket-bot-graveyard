"""Conditional Value-at-Risk (CVaR / Expected Shortfall) monitoring."""

import logging
from typing import List

import numpy as np

logger = logging.getLogger(__name__)


def calculate_var(returns: List[float], confidence: float = 0.99) -> float:
    """Historical Value-at-Risk at given confidence level.

    Returns the loss threshold such that losses exceed this value
    only (1 - confidence)% of the time.
    """
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    return float(np.percentile(arr, (1 - confidence) * 100))


def calculate_cvar(returns: List[float], confidence: float = 0.99) -> float:
    """Conditional VaR — expected loss given that loss exceeds VaR.

    This captures tail risk better than VaR alone.
    """
    if len(returns) < 2:
        return 0.0
    arr = np.array(returns)
    var = calculate_var(returns, confidence)
    tail = arr[arr <= var]
    if len(tail) == 0:
        return var
    return float(np.mean(tail))


class CVaRMonitor:
    """Monitors portfolio CVaR and triggers liquidation if threshold breached."""

    def __init__(self, confidence: float = 0.99, liquidation_threshold: float = 500.0):
        self.confidence = confidence
        self.liquidation_threshold = liquidation_threshold
        self.returns_history: List[float] = []

    def add_return(self, ret: float) -> None:
        self.returns_history.append(ret)
        # Keep last 1000 observations
        if len(self.returns_history) > 1000:
            logger.debug("Truncating returns_history from %d to 1000 entries",
                         len(self.returns_history))
            self.returns_history = self.returns_history[-1000:]

    def current_cvar(self) -> float:
        return calculate_cvar(self.returns_history, self.confidence)

    def current_var(self) -> float:
        return calculate_var(self.returns_history, self.confidence)

    def should_liquidate(self) -> bool:
        """Returns True if CVaR loss exceeds threshold. CVaR is negative for losses."""
        if len(self.returns_history) < 10:
            return False
        cvar = self.current_cvar()
        # CVaR is negative for losses; compare magnitude against threshold
        if cvar < -self.liquidation_threshold:
            logger.critical(
                "CVaR BREACH: |CVaR|=%.2f > threshold=%.2f — LIQUIDATION TRIGGERED",
                cvar,
                self.liquidation_threshold,
            )
            return True
        return False
