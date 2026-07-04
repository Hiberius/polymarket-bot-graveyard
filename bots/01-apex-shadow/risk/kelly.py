"""Kelly Criterion position sizing — fractional Kelly adapted for prediction markets."""

import logging

logger = logging.getLogger(__name__)


def kelly_fraction(mu: float, r: float, sigma_sq: float) -> float:
    """Full Kelly fraction: f* = (μ - r) / σ²

    Args:
        mu: Expected return of the bet
        r: Risk-free rate (typically 0 for short-term prediction markets)
        sigma_sq: Variance of returns (σ²)

    Returns:
        Optimal fraction of bankroll to wager (can be negative = don't bet)
    """
    import math
    if sigma_sq <= 0 or not math.isfinite(sigma_sq) or not math.isfinite(mu):
        return 0.0
    return (mu - r) / sigma_sq


def fractional_kelly(mu: float, r: float, sigma_sq: float, fraction: float = 0.25) -> float:
    """Conservative fractional Kelly — reduces risk of ruin in fat-tailed markets.

    Args:
        fraction: Multiplier (0.25 = quarter Kelly, recommended for prediction markets)
    """
    f = kelly_fraction(mu, r, sigma_sq)
    result = fraction * f
    return max(result, 0.0)  # never go negative (no shorting beyond limits)


def optimal_position_size(
    bankroll: float,
    mu: float,
    r: float,
    sigma_sq: float,
    fraction: float = 0.25,
    max_size: float = float("inf"),
) -> float:
    """Calculate optimal position size in USDC.

    Args:
        bankroll: Available capital in USDC
        max_size: Hard cap on position size

    Returns:
        Position size in USDC, clamped to [0, max_size]
    """
    f = fractional_kelly(mu, r, sigma_sq, fraction)
    size = bankroll * f
    return min(max(size, 0.0), max_size)
