"""CalibrationGate — the line between shadow and live.

A category may only trade real money once it GRADUATES, proven by forward,
out-of-sample resolutions (never a backtest). Graduation requires ALL of:

  * Brier score < threshold            → predictions are well-calibrated
  * n_observations >= minimum          → enough sample to trust it
  * mean realized edge > threshold     → the edge actually paid out forward
  * reliability monotone               → higher predicted ⇒ higher actual

Brier = mean((p - outcome)^2). 0.25 = a coin-flip predictor; lower is better.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import structlog

log = structlog.get_logger()

N_RELIABILITY_BINS = 10


@dataclass(frozen=True)
class CalibrationVerdict:
    category: str
    n_observations: int
    brier_score: float | None
    reliability_bins: list[dict[str, Any]]
    edge_realized_mean: float | None
    monotone: bool
    graduated: bool


def _brier(preds: Sequence[float], outcomes: Sequence[int]) -> float:
    return sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds)


def _reliability(
    preds: Sequence[float], outcomes: Sequence[int]
) -> tuple[list[dict[str, Any]], bool]:
    """Bin predictions; return (bins, trend_ok).

    trend_ok captures "higher predicted ⇒ higher actual win-rate" via the
    slope of actual~predicted across populated bins. A strict monotone check
    is too fragile (sampling noise breaks it even on perfectly calibrated
    data); a positive slope (>0.5, ideal=1.0 for perfect calibration) is the
    robust signal. Requires >=3 populated bins so there is spread to judge.
    """
    bins: list[dict[str, Any]] = []
    for i in range(N_RELIABILITY_BINS):
        lo, hi = i / N_RELIABILITY_BINS, (i + 1) / N_RELIABILITY_BINS
        idx = [j for j, p in enumerate(preds)
               if (lo <= p < hi) or (i == N_RELIABILITY_BINS - 1 and p == 1.0)]
        if not idx:
            continue
        predicted = sum(preds[j] for j in idx) / len(idx)
        actual = sum(outcomes[j] for j in idx) / len(idx)
        bins.append({
            "bin": round((lo + hi) / 2, 3),
            "predicted": round(predicted, 4),
            "actual": round(actual, 4),
            "n": len(idx),
        })
    trend_ok = _positive_slope(bins) if len(bins) >= 3 else False
    return bins, trend_ok


def _positive_slope(bins: list[dict[str, Any]], *, min_slope: float = 0.5) -> bool:
    """OLS slope of actual~predicted across bins; True if clearly positive."""
    xs = [b["predicted"] for b in bins]
    ys = [b["actual"] for b in bins]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    if var == 0:
        return False
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    slope = cov / var
    return slope >= min_slope


def evaluate_category(
    category: str,
    rows: Sequence[dict[str, Any]],
    *,
    brier_max: float,
    min_obs: int,
    min_edge_realized: float,
) -> CalibrationVerdict:
    """Compute the calibration verdict for one category.

    rows: dicts with keys predicted_prob, resolved_outcome, edge_pp_realized.
    Only rows with a non-null resolved_outcome count.
    """
    resolved = [r for r in rows if r.get("resolved_outcome") is not None]
    n = len(resolved)
    if n == 0:
        return CalibrationVerdict(category, 0, None, [], None, False, False)

    # Brier + reliability use EVERY resolved prediction — that measures whether
    # our external_fair is calibrated across the whole probability range.
    preds = [float(r["predicted_prob"]) for r in resolved]
    outcomes = [int(r["resolved_outcome"]) for r in resolved]
    brier = _brier(preds, outcomes)
    bins, monotone = _reliability(preds, outcomes)

    # Realized edge uses ONLY the would-trade rows (debug fix 2026-06-01):
    # we never buy the negative-edge side, so averaging it in would understate
    # the edge and keep the gate shut forever. `would_trade` defaults to True
    # when absent (unit tests / pre-flag rows).
    realized = [float(r["edge_pp_realized"]) for r in resolved
                if r.get("would_trade", True) and r.get("edge_pp_realized") is not None]
    edge_mean = (sum(realized) / len(realized)) if realized else None

    graduated = (
        n >= min_obs
        and brier < brier_max
        and monotone
        and edge_mean is not None
        and edge_mean > min_edge_realized
    )
    return CalibrationVerdict(
        category=category,
        n_observations=n,
        brier_score=round(brier, 4),
        reliability_bins=bins,
        edge_realized_mean=round(edge_mean, 3) if edge_mean is not None else None,
        monotone=monotone,
        graduated=graduated,
    )


async def recompute_all(db: Any, settings: Any) -> dict[str, CalibrationVerdict]:
    """Recompute calibration for every category from shadow_resolutions and
    persist to category_calibration. Returns the verdicts."""
    brier_max = float(getattr(settings, "oracle_cal_brier_max", 0.22))
    min_obs = int(getattr(settings, "oracle_cal_min_obs", 50))
    min_edge = float(getattr(settings, "oracle_cal_min_edge_realized", 0.0))

    # Dedup fix (red-team 2026-06-11): shadow_resolutions stores BOTH sides of
    # a game (YES home + YES away), perfectly anti-correlated. Counting both
    # doubles n and pins the base rate at 0.5. One statistical unit per GAME:
    # keep the favourite side (highest predicted_prob per game_key).
    rows = await db.fetch(
        """
        SELECT DISTINCT ON (game_key)
               category, predicted_prob, resolved_outcome,
               edge_pp_realized, would_trade
        FROM (
            SELECT sr.category, sr.predicted_prob, sr.resolved_outcome,
                   sr.edge_pp_realized, od.would_trade_bool AS would_trade,
                   split_part(sr.entity_key, ':', 1) || ':' ||
                   split_part(sr.entity_key, ':', 2) AS game_key
            FROM shadow_resolutions sr
            JOIN oracle_divergences od ON od.id = sr.divergence_id
            WHERE sr.resolved_outcome IS NOT NULL
              AND sr.entity_key IS NOT NULL
        ) t
        ORDER BY game_key, predicted_prob DESC
        """
    )
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(dict(r))

    verdicts: dict[str, CalibrationVerdict] = {}
    for category in ("sports", "macro", "politics", "weather"):
        v = evaluate_category(
            category, by_cat.get(category, []),
            brier_max=brier_max, min_obs=min_obs, min_edge_realized=min_edge,
        )
        verdicts[category] = v
        import json
        await db.execute(
            """
            UPDATE category_calibration SET
              n_observations = $2, brier_score = $3, reliability_bins = $4::jsonb,
              edge_realized_mean = $5, monotone = $6,
              graduated = $7,
              graduated_at = CASE WHEN $7 AND NOT category_calibration.graduated
                                  THEN NOW() ELSE category_calibration.graduated_at END,
              last_evaluated_at = NOW()
            WHERE category = $1
            """,
            category, v.n_observations, v.brier_score,
            json.dumps(v.reliability_bins), v.edge_realized_mean,
            v.monotone, v.graduated,
        )
        if v.graduated:
            log.warning("category_graduated", category=category,
                        brier=v.brier_score, n=v.n_observations,
                        edge=v.edge_realized_mean)
    return verdicts
