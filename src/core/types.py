from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SimulationConfig:
    duration_slots: int
    slot_time_ms: int
    random_seed: int


@dataclass(slots=True)
class Packet:
    packet_id: str
    flow_id: str
    flow_type: str
    arrival_time_ms: int
    packet_size_bytes: int
    deadline_ms: int
    priority: int
    ue_id: int = 0
    remaining_bits: int = 0
    tx_count: int = 0
    last_tx_time_ms: int | None = None
    start_tx_time_ms: float | None = None
    finish_time_ms: float | None = None
    tx_duration_ms: float = 0.0
    is_delivered: bool = False
    drop_reason: str | None = None
    last_mcs: str = ""
    last_snr_db: float | None = None
    last_bler: float = 0.0
    last_is_success: bool = False
    last_is_los: bool = False
    last_allocated_bandwidth_mhz: float = 0.0
    last_bits_sent: int = 0
    outcome: str = ""


@dataclass(slots=True)
class AttemptRecord:
    packet_id: str
    ue_id: int
    flow_id: str
    attempt_idx: int
    slot_idx: int
    t_tx_start_ms: int
    allocated_bandwidth_mhz: float
    bits_sent: int
    remaining_bits_after: int
    is_success: bool
    mcs: str
    snr_db: float | None
    bler: float
    is_los: bool


@dataclass(slots=True)
class PacketRecord:
    packet_id: str
    ue_id: int = 0
    flow_id: str = ""
    flow_type: str = ""
    priority: int = 0
    size_bytes: int = 0
    arrival_time_ms: int = 0
    start_tx_time_ms: float | None = None
    finish_time_ms: float | None = None
    tx_duration_ms: float = 0.0
    deadline_ms: int = 0
    outcome: str = ""
    tx_count: int = 0
    is_deadline_missed: bool = False
    mcs: str = ""
    snr_db: float | None = None
    bler: float = 0.0


@dataclass(slots=True)
class FlowSpec:
    id: str
    type: str
    arrival_model: str
    period_ms: int | None
    lambda_per_s: float | None
    packet_size_bytes: int
    deadline_ms: int
    priority: int


@dataclass(slots=True)
class TrafficUEConfig:
    count: int = 1
    seed_mode: str = "per_ue_offset"


@dataclass(slots=True)
class TrafficConfig:
    flows: list[FlowSpec] = field(default_factory=list)
    ue: TrafficUEConfig = field(default_factory=TrafficUEConfig)


@dataclass(slots=True)
class ResourceConfig:
    granularity: str = "continuous"
    allocation_policy: str = "demand_based"
    bandwidth_fraction: float = 0.8
    min_share_enabled: bool = False
    min_share_per_priority_mhz: dict[int, float] = field(default_factory=dict)
    min_share_per_priority_fraction: dict[int, float] = field(default_factory=dict)


@dataclass(slots=True)
class RunMetrics:
    total_slots: int
    random_seed: int
    total_arrivals: int
    arrivals_by_flow: dict[str, int]
    arrivals_by_ue: dict[int, int] = field(default_factory=dict)
    total_served: int = 0
    total_delivered: int = 0
    total_deadline_missed: int = 0
    total_dropped_deadline: int = 0
    total_dropped_max_tx: int = 0
    total_tx_attempts: int = 0
    total_success_bits: int = 0
    delivered_rate: float = 0.0
    deadline_miss_ratio: float = 0.0
    avg_tx_per_delivered: float = 0.0
    total_failed: int = 0
    failure_rate_total: float = 0.0
    avg_waiting_ms: float = 0.0
    avg_sojourn_ms: float = 0.0
    p95_sojourn_ms: float = 0.0
    p99_sojourn_ms: float = 0.0
    throughput_bps: float = 0.0
    bandwidth_fraction: float = 0.0
    effective_bandwidth_mhz: float = 0.0
    bandwidth_utilization: float = 0.0
    queue_max_len: int = 0
    queue_size_by_priority_end: dict[int, int] = field(default_factory=dict)
    mean_snr_db: float = 0.0
    p05_snr_db: float = 0.0
    p50_snr_db: float = 0.0
    p95_snr_db: float = 0.0
    mcs_counts: dict[str, int] = field(default_factory=dict)
    los_rate: float = 0.0
    per_flow_kpis: dict[str, dict[str, float]] = field(default_factory=dict)
    per_ue_kpis: dict[str, dict[str, float]] = field(default_factory=dict)
    jain_fairness_throughput: float = 0.0


@dataclass(slots=True)
class SimulationContext:
    output_dir: Path
    config: dict[str, Any]
