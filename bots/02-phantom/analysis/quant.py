from dataclasses import dataclass


@dataclass
class QuantSignals:
    line_movement: float
    volume_spike: float
    book_imbalance: float
    spread: float
    time_decay: float


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))


def compute_line_movement(price_history: list[float], ensemble_prob: float) -> float:
    if len(price_history) < 2:
        return 0.0
    price_change = price_history[-1] - price_history[0]
    direction_toward = ensemble_prob - price_history[-1]
    if abs(direction_toward) < 1e-9:
        return 0.0
    if direction_toward > 0:
        signal = price_change / max(abs(direction_toward), 0.01)
    else:
        signal = -price_change / max(abs(direction_toward), 0.01)
    return _clamp(signal)


def compute_volume_spike(current_volume: float, avg_volume: float) -> float:
    if avg_volume <= 0:
        return 0.0
    return _clamp((current_volume / avg_volume - 1.0) / 3.0)


def compute_book_imbalance(bid_depth: float, ask_depth: float) -> float:
    total = bid_depth + ask_depth
    if total <= 0:
        return 0.0
    return _clamp((bid_depth - ask_depth) / total)


def compute_spread_signal(bid: float, ask: float) -> float:
    if ask <= 0:
        return 0.0
    spread_pct = (ask - bid) / ask
    return _clamp(1.0 - (spread_pct / 0.05))


def compute_time_decay(hours_remaining: float) -> float:
    if hours_remaining <= 0:
        return -1.0
    return _clamp((hours_remaining - 24) / 48)


def compute_composite_score(signals: QuantSignals, weights: dict[str, float]) -> float:
    total = (signals.line_movement * weights["line_movement"] + signals.volume_spike * weights["volume_spike"]
        + signals.book_imbalance * weights["book_imbalance"] + signals.spread * weights["spread"]
        + signals.time_decay * weights["time_decay"])
    return _clamp(total)
