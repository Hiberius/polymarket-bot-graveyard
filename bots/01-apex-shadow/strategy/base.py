"""Abstract base class for all trading strategies."""

from abc import ABC, abstractmethod
from typing import List

from src.market_data.book_snapshot import BookSnapshot, Signal


class Strategy(ABC):
    """Base strategy interface. All strategies must implement on_update()."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    async def on_update(self, market_data: BookSnapshot) -> List[Signal]:
        """Process new market data and return trading signals.

        Args:
            market_data: Latest order book snapshot from ZMQ

        Returns:
            List of Signal objects to be executed (can be empty)
        """
        ...
