"""Academic calibration correction for prediction market prices.

Based on: "Domain-Specific Calibration Dynamics in Prediction Markets"
(arxiv.org/html/2602.19520v1)

Key finding: Political markets on Polymarket have a calibration slope of ~1.31,
meaning prices are systematically compressed toward 0.50. A 70-cent contract
actually implies ~83% true probability.

The correction formula applies a logit-space slope adjustment:
  logit(p_true) = slope * logit(p_market)
  p_true = sigmoid(slope * logit(p_market))

where logit(p) = log(p / (1-p)) and sigmoid(x) = 1 / (1 + exp(-x))
"""

import math

# Calibration slopes by domain (from academic research)
DOMAIN_SLOPES = {
    "politics": 1.31,
    "geopolitics": 1.31,
    "world": 1.20,
    "crypto": 1.05,
    "sports": 1.05,
    "finance": 1.10,
    "default": 1.10,
}

POLITICAL_TAGS = {"politics", "geopolitics", "global-elections", "world",
                  "trump-presidency", "foreign-policy"}


def is_political_market(tags: list[str]) -> bool:
    """Check if a market's tags indicate it's political/geopolitical."""
    return bool(POLITICAL_TAGS & set(tags))


def calibration_adjusted_prob(market_price: float, slope: float = 1.31) -> float:
    """Apply calibration correction to a market price.

    Uses logit-space linear correction: logit(p_true) = slope * logit(p_market).
    This stretches prices away from 0.50 — favorites get boosted, underdogs get
    compressed — matching the empirically observed bias in prediction markets.
    """
    p = max(0.001, min(0.999, market_price))
    logit_p = math.log(p / (1 - p))
    corrected_logit = slope * logit_p
    corrected = 1.0 / (1.0 + math.exp(-corrected_logit))
    return max(0.01, min(0.99, corrected))


def get_domain_slope(tags: list[str]) -> float:
    """Look up the calibration slope for a market based on its tags."""
    for tag in tags:
        if tag in DOMAIN_SLOPES:
            return DOMAIN_SLOPES[tag]
    return DOMAIN_SLOPES["default"]
