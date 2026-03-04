from __future__ import annotations

import math
import random
from dataclasses import dataclass

from src.core.types import FlowSpec, Packet


@dataclass(slots=True)
class _FlowState:
    spec: FlowSpec
    ue_id: int
    rng: random.Random
    next_arrival_ms: int
    seq: int = 0


class TrafficGenerator:
    """Generate per-flow, per-UE packet arrivals and expose slot-based pop interface."""

    def __init__(
        self,
        flow_specs: list[FlowSpec],
        random_seed: int,
        ue_count: int = 1,
        seed_mode: str = "per_ue_offset",
    ) -> None:
        if ue_count < 1:
            raise ValueError("traffic.ue.count must be >= 1")

        self._states: list[_FlowState] = []
        self._seed_mode = seed_mode
        for ue_id in range(ue_count):
            for spec in flow_specs:
                state_rng = random.Random(self._state_seed(random_seed, ue_id, spec.id))
                next_arrival = self._initial_arrival_ms(spec, state_rng)
                self._states.append(
                    _FlowState(
                        spec=spec,
                        ue_id=ue_id,
                        rng=state_rng,
                        next_arrival_ms=next_arrival,
                    )
                )

    def pop_arrivals(self, t_ms: int) -> list[Packet]:
        arrivals: list[Packet] = []

        for state in self._states:
            while state.next_arrival_ms == t_ms:
                packet = Packet(
                    packet_id=f"{state.spec.id}-ue{state.ue_id:02d}-{state.seq:06d}",
                    ue_id=state.ue_id,
                    flow_id=state.spec.id,
                    flow_type=state.spec.type,
                    arrival_time_ms=t_ms,
                    packet_size_bytes=state.spec.packet_size_bytes,
                    deadline_ms=state.spec.deadline_ms,
                    priority=state.spec.priority,
                )
                arrivals.append(packet)
                state.seq += 1
                state.next_arrival_ms = self._next_arrival_ms(state)

        arrivals.sort(key=lambda p: (p.arrival_time_ms, p.priority, p.ue_id, p.packet_id))
        return arrivals

    def _state_seed(self, base_seed: int, ue_id: int, flow_id: str) -> int:
        if self._seed_mode == "per_ue_offset":
            return base_seed + ue_id * 1009 + sum(ord(ch) for ch in flow_id)
        if self._seed_mode == "hash":
            return abs(hash((base_seed, ue_id, flow_id))) % (2**31)
        raise ValueError(f"Unsupported traffic.ue.seed_mode: {self._seed_mode}")

    def _initial_arrival_ms(self, spec: FlowSpec, rng: random.Random) -> int:
        if spec.arrival_model == "periodic":
            return 0
        if spec.arrival_model == "poisson":
            return self._sample_poisson_interarrival_ms(spec, rng)
        raise ValueError(f"Unsupported arrival model: {spec.arrival_model}")

    def _next_arrival_ms(self, state: _FlowState) -> int:
        spec = state.spec
        if spec.arrival_model == "periodic":
            if spec.period_ms is None:
                raise ValueError(f"period_ms is required for periodic flow: {spec.id}")
            return state.next_arrival_ms + spec.period_ms

        if spec.arrival_model == "poisson":
            return state.next_arrival_ms + self._sample_poisson_interarrival_ms(spec, state.rng)

        raise ValueError(f"Unsupported arrival model: {spec.arrival_model}")

    def _sample_poisson_interarrival_ms(self, spec: FlowSpec, rng: random.Random) -> int:
        if spec.lambda_per_s is None or spec.lambda_per_s <= 0:
            raise ValueError(f"lambda_per_s must be > 0 for poisson flow: {spec.id}")

        lambda_per_ms = spec.lambda_per_s / 1000.0
        dt = rng.expovariate(lambda_per_ms)
        return max(1, math.ceil(dt))
