from __future__ import annotations

from src.core.queue import PriorityQueues
from src.core.types import Packet


class StrictPriorityScheduler:
    """严格优先级调度器：总是选择最高优先级队列队首包。"""

    def __init__(self, queues: PriorityQueues) -> None:
        self.queues = queues

    def select_packet(self) -> Packet | None:
        return self.queues.dequeue()
