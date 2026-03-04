from __future__ import annotations

import random

from src.channel.base import ChannelEvalResult
from src.core.types import Packet


class StubBlerChannelModel:
    """简化链路模型：按 flow 固定 BLER 做伯努利判决。"""

    def __init__(self, bler_by_flow: dict[str, float] | None = None, default_bler: float = 0.0) -> None:
        self._bler_by_flow = bler_by_flow or {}
        self._default_bler = float(default_bler)

    def bler(self, packet: Packet, t_ms: int) -> float:
        _ = t_ms
        return float(
            self._bler_by_flow.get(packet.flow_type, self._bler_by_flow.get(packet.flow_id, self._default_bler))
        )

    def is_success(self, packet: Packet, t_ms: int, rng: random.Random) -> ChannelEvalResult:
        bler_value = self.bler(packet, t_ms)
        success = rng.random() >= bler_value
        return {
            "success": success,
            "bler": bler_value,
            "snr_db": 0.0,
            "mcs": "QPSK",
            "is_los": False,
        }
