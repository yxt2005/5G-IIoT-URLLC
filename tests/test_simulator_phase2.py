from __future__ import annotations

import csv
from pathlib import Path

from src.core.simulator import Simulator


def test_simulator_single_periodic_flow_serves_all_packets(tmp_path: Path) -> None:
    config = {
        "simulation": {"duration_slots": 5, "slot_time_ms": 1, "random_seed": 42},
        "traffic": {
            "ue": {"count": 1},
            "flows": [
                {
                    "id": "F1",
                    "type": "HRP",
                    "arrival": {"model": "periodic", "period_ms": 1},
                    "packet_size_bytes": 64,
                    "deadline_ms": 10,
                    "priority": 1,
                }
            ],
        },
    }

    metrics = Simulator(config=config, outputs_root=tmp_path).run()

    assert metrics.total_arrivals == 5
    assert metrics.total_delivered == 5
    assert metrics.queue_max_len <= 1
    output_dir = next(tmp_path.iterdir())
    assert (output_dir / "metrics.json").exists()
    assert (output_dir / "packet_records.csv").exists()


def test_simulator_drops_expired_packets_and_limits_queue_growth(tmp_path: Path) -> None:
    config = {
        "simulation": {"duration_slots": 10, "slot_time_ms": 1, "random_seed": 7},
        "traffic": {
            "ue": {"count": 1},
            "flows": [
                {
                    "id": "F1",
                    "type": "ETC",
                    "arrival": {"model": "periodic", "period_ms": 1},
                    "packet_size_bytes": 2000,
                    "deadline_ms": 1,
                    "priority": 1,
                }
            ],
        },
        "link": {
            "model": "stub_bler",
            "bler_by_flow": {"F1": 0.0},
            "resource": {"bandwidth_fraction": 0.0001},
            "scenario": {"bandwidth_mhz": 20},
            "mcs_efficiency_bpshz": {"QPSK": 1.0, "16QAM": 3.0},
        },
        "retransmission": {"enabled": True, "max_tx": 4, "strategy": "immediate"},
    }

    metrics = Simulator(config=config, outputs_root=tmp_path).run()

    assert metrics.total_arrivals == 10
    assert metrics.total_dropped_deadline > 0
    assert metrics.queue_max_len <= 1


def test_same_slot_can_serve_multiple_packets(tmp_path: Path) -> None:
    config = {
        "simulation": {"duration_slots": 1, "slot_time_ms": 1, "random_seed": 11},
        "traffic": {
            "ue": {"count": 1},
            "flows": [
                {
                    "id": "F1",
                    "type": "HRP",
                    "arrival": {"model": "periodic", "period_ms": 10},
                    "packet_size_bytes": 16,
                    "deadline_ms": 10,
                    "priority": 1,
                },
                {
                    "id": "F2",
                    "type": "HRP",
                    "arrival": {"model": "periodic", "period_ms": 10},
                    "packet_size_bytes": 16,
                    "deadline_ms": 10,
                    "priority": 2,
                },
            ],
        },
        "link": {
            "model": "stub_bler",
            "bler_by_flow": {"F1": 0.0, "F2": 0.0},
            "resource": {"bandwidth_fraction": 0.8},
            "scenario": {"bandwidth_mhz": 20},
            "mcs_efficiency_bpshz": {"QPSK": 1.0, "16QAM": 3.0},
        },
    }

    Simulator(config=config, outputs_root=tmp_path).run()
    output_dir = next(tmp_path.iterdir())
    with (output_dir / "attempts.csv").open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 2
    assert {row["slot_idx"] for row in rows} == {"0"}


def test_served_deadline_boundary_uses_strict_greater_than() -> None:
    assert Simulator._is_served_deadline_missed(sojourn_ms=1, deadline_ms=1) is False
    assert Simulator._is_served_deadline_missed(sojourn_ms=2, deadline_ms=1) is True
