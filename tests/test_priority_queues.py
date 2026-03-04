from __future__ import annotations

from src.core.queue import PriorityQueues
from src.core.types import Packet


def _packet(packet_id: str, priority: int, arrival: int) -> Packet:
    return Packet(
        packet_id=packet_id,
        flow_id="F",
        flow_type="TEST",
        arrival_time_ms=arrival,
        packet_size_bytes=64,
        deadline_ms=10,
        priority=priority,
    )


def test_priority_queues_fifo_within_same_priority() -> None:
    queues = PriorityQueues()
    packets = [_packet("p1", 1, 0), _packet("p2", 1, 1), _packet("p3", 1, 2)]
    for pkt in packets:
        queues.enqueue(pkt)

    assert queues.dequeue() is packets[0]
    assert queues.dequeue() is packets[1]
    assert queues.dequeue() is packets[2]
    assert queues.dequeue() is None


def test_priority_queues_selects_higher_priority_first() -> None:
    queues = PriorityQueues()
    low = _packet("low", 2, 0)
    high = _packet("high", 1, 1)

    queues.enqueue(low)
    queues.enqueue(high)

    assert queues.dequeue() is high
    assert queues.dequeue() is low


def test_drop_boundary_waiting_equal_deadline_is_dropped() -> None:
    queues = PriorityQueues()
    pkt = Packet(
        packet_id="p-boundary",
        flow_id="F",
        flow_type="TEST",
        arrival_time_ms=0,
        packet_size_bytes=64,
        deadline_ms=1,
        priority=1,
    )
    queues.enqueue(pkt)

    dropped = queues.drop_expired(t_ms=1)

    assert dropped == [pkt]
    assert len(queues) == 0
