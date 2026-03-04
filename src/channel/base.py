from __future__ import annotations

import random
from typing import Protocol, TypedDict

from src.core.types import Packet


class ChannelEvalResult(TypedDict):
    success: bool
    bler: float
    snr_db: float
    mcs: str
    is_los: bool


class ChannelModel(Protocol):
    def bler(self, packet: Packet, t_ms: int) -> float:
        ...

    def is_success(self, packet: Packet, t_ms: int, rng: random.Random) -> ChannelEvalResult:
        ...
