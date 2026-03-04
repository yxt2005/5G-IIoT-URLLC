from __future__ import annotations

from collections import deque

from src.core.types import Packet


class PriorityQueues:
    """按 priority 分组的多 FIFO 队列（值越小优先级越高）。"""

    def __init__(self) -> None:
        self._queues: dict[int, deque[Packet]] = {}

    def enqueue(self, packet: Packet) -> None:
        if packet.priority not in self._queues:
            self._queues[packet.priority] = deque()
        self._queues[packet.priority].append(packet)

    def dequeue(self) -> Packet | None:
        for priority in sorted(self._queues):
            q = self._queues[priority]
            if q:
                return q.popleft()
        return None

    def __len__(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def size_by_priority(self) -> dict[int, int]:
        return {priority: len(self._queues[priority]) for priority in sorted(self._queues)}

    def drop_expired(self, t_ms: int) -> list[Packet]:
        """移除在当前时刻已超时的包，并返回被移除列表。"""
        dropped: list[Packet] = []
        for priority in sorted(self._queues):
            q = self._queues[priority]
            if not q:
                continue

            kept = deque()
            while q:
                pkt = q.popleft()
                if (t_ms - pkt.arrival_time_ms) >= pkt.deadline_ms:
                    dropped.append(pkt)
                else:
                    kept.append(pkt)
            self._queues[priority] = kept
        return dropped
