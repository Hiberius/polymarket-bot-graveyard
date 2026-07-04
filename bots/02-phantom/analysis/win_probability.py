"""Win probability model for NBA, MLB, NHL, NCAAB, and soccer games.

Pure functions mapping score lead + game clock position to win probability.
Uses empirical scaling coefficients derived from historical sports data.
Conservative by design — better to miss trades than overestimate certainty.
"""

from __future__ import annotations

# Default total periods per sport, exported for use by strategies.
TOTAL_PERIODS: dict[str, int] = {
    "nba": 4,
    "mlb": 9,
    "nhl": 3,
    "ncaab": 2,
    "soccer": 2,
    "ucl": 2,
    "epl": 2,
    "laliga": 2,
    "bundesliga": 2,
    "mls": 2,
}


def compute_win_probability(
    sport: str,
    lead: int,
    period: int,
    total_periods: int,
    completed: bool = False,
) -> float | None:
    """Return win probability (0.0–1.0) for the team holding *lead*.

    Args:
        sport: One of "nba", "mlb", "nhl" (case-insensitive).
        lead: Score difference for the team of interest.  Positive = leading,
              negative = trailing, zero = tied.
        period: Current period / inning (1-based).
        total_periods: Total periods / innings in regulation.
        completed: If True the game is final; returns a deterministic result.

    Returns:
        Win probability as a float in [0.0, 1.0], or None for unknown sports.
    """
    sport_key = sport.lower()

    if sport_key not in _SPORT_MODELS:
        return None

    if completed:
        if lead > 0:
            return 1.0
        elif lead < 0:
            return 0.0
        else:
            return 0.5

    game_progress = min(period / total_periods, 1.0)

    return _SPORT_MODELS[sport_key](lead, game_progress)


def _nba_win_prob(lead: int, game_progress: float) -> float:
    """NBA model: each point worth 1 % at Q1 -> 3.5 % at Q4.

    Formula: 0.5 + sign * abs_lead * (0.01 + 0.025 * game_progress)
    Clamped to [0.01, 0.99].
    """
    sign = 1 if lead >= 0 else -1
    abs_lead = abs(lead)
    per_point = 0.01 + 0.025 * game_progress
    prob = 0.5 + sign * abs_lead * per_point
    return max(0.01, min(0.99, prob))


def _mlb_win_prob(lead: int, game_progress: float) -> float:
    """MLB model: strongly late-weighted — early innings have little value.

    Formula: 0.5 + sign * abs_lead * (-0.03 + 0.35 * game_progress)
    Clamped to [0.01, 0.99].

    Calibrated so that a 1-run lead in the 9th is ~0.82 win probability
    while a 3-run lead in the 3rd is ~0.76 — reflecting baseball's high
    variance in early innings.
    """
    sign = 1 if lead >= 0 else -1
    abs_lead = abs(lead)
    per_run = -0.03 + 0.35 * game_progress
    prob = 0.5 + sign * abs_lead * per_run
    return max(0.01, min(0.99, prob))


def _nhl_win_prob(lead: int, game_progress: float) -> float:
    """NHL model: each goal worth 10 % at period 1 -> 27 % at period 3.

    Formula: 0.5 + sign * abs_lead * (0.10 + 0.17 * game_progress)
    Clamped to [0.01, 0.99].

    Calibrated so that a 1-goal lead in the 3rd period is ~0.77 win
    probability — hockey goals are decisive but comebacks still happen.
    """
    sign = 1 if lead >= 0 else -1
    abs_lead = abs(lead)
    per_goal = 0.10 + 0.17 * game_progress
    prob = 0.5 + sign * abs_lead * per_goal
    return max(0.01, min(0.99, prob))


def _ncaab_win_prob(lead: int, game_progress: float) -> float:
    """NCAAB: similar to NBA but 2 halves, higher variance."""
    sign = 1 if lead >= 0 else -1
    abs_lead = abs(lead)
    per_point = 0.008 + 0.022 * game_progress
    prob = 0.5 + sign * abs_lead * per_point
    return max(0.01, min(0.99, prob))


def _soccer_win_prob(lead: int, game_progress: float) -> float:
    """Soccer: goals are rare and decisive. Each goal worth 15-30%."""
    sign = 1 if lead >= 0 else -1
    abs_lead = abs(lead)
    per_goal = 0.15 + 0.15 * game_progress
    prob = 0.5 + sign * abs_lead * per_goal
    return max(0.01, min(0.99, prob))


_SPORT_MODELS = {
    "nba": _nba_win_prob,
    "mlb": _mlb_win_prob,
    "nhl": _nhl_win_prob,
    "ncaab": _ncaab_win_prob,
    "soccer": _soccer_win_prob,
    "ucl": _soccer_win_prob,
    "epl": _soccer_win_prob,
    "laliga": _soccer_win_prob,
    "bundesliga": _soccer_win_prob,
    "mls": _soccer_win_prob,
}
