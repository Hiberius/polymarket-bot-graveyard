import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TradingContext:
    db: Any
    scanner: Any
    risk_manager: Any
    portfolio_lock: asyncio.Lock
    executor: Any
    email_notifier: Any
    settings: Any
    clob: Any = None


class Strategy(ABC):
    name: str
    interval_seconds: float
    kelly_multiplier: float
    max_single_pct: float

    @abstractmethod
    async def run_once(self, ctx: TradingContext) -> None: ...
