from __future__ import annotations

from src.core.types import FlowSpec
from src.traffic import TrafficGenerator


def test_periodic_arrivals_are_generated_at_expected_slots() -> None:
    flow = FlowSpec(
        id="F1",
        type="HRP",
        arrival_model="periodic",
        period_ms=5,
        lambda_per_s=None,
        packet_size_bytes=64,
        deadline_ms=10,
        priority=1,
    )
    gen = TrafficGenerator(flow_specs=[flow], random_seed=123)

    arrival_counts = {t: len(gen.pop_arrivals(t)) for t in range(21)}
    expected_times = {0, 5, 10, 15, 20}

    for t in range(21):
        expected = 1 if t in expected_times else 0
        assert arrival_counts[t] == expected


def test_poisson_arrivals_are_reproducible_with_fixed_seed() -> None:
    flow = FlowSpec(
        id="ETC",
        type="ETC",
        arrival_model="poisson",
        period_ms=None,
        lambda_per_s=200.0,
        packet_size_bytes=512,
        deadline_ms=100,
        priority=3,
    )

    def collect_first_n_arrival_times(n: int) -> list[int]:
        gen = TrafficGenerator(flow_specs=[flow], random_seed=42)
        times: list[int] = []
        t = 0
        while len(times) < n and t < 100_000:
            arrivals = gen.pop_arrivals(t)
            times.extend(packet.arrival_time_ms for packet in arrivals)
            t += 1
        assert len(times) >= n
        return times[:n]

    seq1 = collect_first_n_arrival_times(10)
    seq2 = collect_first_n_arrival_times(10)
    assert seq1 == seq2


def test_same_time_arrivals_are_sorted_by_priority() -> None:
    high_priority = FlowSpec(
        id="HP",
        type="HRP",
        arrival_model="periodic",
        period_ms=10,
        lambda_per_s=None,
        packet_size_bytes=64,
        deadline_ms=5,
        priority=1,
    )
    low_priority = FlowSpec(
        id="LP",
        type="SRP",
        arrival_model="periodic",
        period_ms=10,
        lambda_per_s=None,
        packet_size_bytes=256,
        deadline_ms=20,
        priority=2,
    )

    gen = TrafficGenerator(flow_specs=[low_priority, high_priority], random_seed=7)
    arrivals = gen.pop_arrivals(0)

    assert [packet.flow_id for packet in arrivals] == ["HP", "LP"]
    assert [packet.priority for packet in arrivals] == [1, 2]


def test_poisson_high_rate_interarrival_is_at_least_one_ms_and_no_hang() -> None:
    flow = FlowSpec(
        id="FAST",
        type="ETC",
        arrival_model="poisson",
        period_ms=None,
        lambda_per_s=10_000.0,
        packet_size_bytes=128,
        deadline_ms=50,
        priority=3,
    )
    gen = TrafficGenerator(flow_specs=[flow], random_seed=1)

    last_arrival_time: int | None = None
    total_packets = 0

    # 覆盖多个时刻，验证不会在某个 t_ms 卡住无限生成
    for t in range(101):
        arrivals = gen.pop_arrivals(t)
        total_packets += len(arrivals)

        for packet in arrivals:
            assert packet.arrival_time_ms == t
            if last_arrival_time is not None:
                assert packet.arrival_time_ms - last_arrival_time >= 1
            last_arrival_time = packet.arrival_time_ms

    # 高到达率下通常会有到达；同时至少说明循环执行结束
    assert total_packets > 0
