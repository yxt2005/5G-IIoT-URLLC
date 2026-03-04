from __future__ import annotations

import csv
from pathlib import Path

from src.core.simulator import Simulator


class _AlwaysSuccess16QAMChannel:
    def is_success(self, packet, t_ms, rng):
        _ = packet, t_ms, rng
        return {"success": True, "bler": 0.0, "snr_db": 30.0, "mcs": "16QAM", "is_los": True}


def _run_and_get_output_dir(simulator: Simulator, tmp_path: Path):
    metrics = simulator.run()
    output_dir = next(tmp_path.iterdir())
    return metrics, output_dir


def test_bits_per_slot_affects_completion(tmp_path: Path) -> None:
    config = {
        "simulation": {"duration_slots": 20, "slot_time_ms": 1, "random_seed": 1},
        "traffic": {
            "ue": {"count": 1},
            "flows": [
                {
                    "id": "SRP",
                    "type": "SRP",
                    "arrival": {"model": "periodic", "period_ms": 1000},
                    "packet_size_bytes": 200,
                    "deadline_ms": 20,
                    "priority": 1,
                }
            ],
        },
        "link": {
            "model": "stub_bler",
            "bler_by_flow": {"SRP": 0.0},
            "resource": {"bandwidth_fraction": 0.01},
            "scenario": {"bandwidth_mhz": 20},
            "mcs_efficiency_bpshz": {"QPSK": 1.0, "16QAM": 3.0},
        },
        "retransmission": {"enabled": True, "max_tx": 20, "strategy": "immediate"},
    }

    simulator = Simulator(config=config, outputs_root=tmp_path)
    simulator.channel = _AlwaysSuccess16QAMChannel()
    eta = simulator._mcs_efficiency_bpshz()["16QAM"]
    assert simulator._bits_for_allocated_bandwidth(0.2, eta) == 600

    metrics, output_dir = _run_and_get_output_dir(simulator, tmp_path)
    assert metrics.total_delivered == 1

    with (output_dir / "packet_records.csv").open("r", encoding="utf-8", newline="") as f:
        packet_rows = list(csv.DictReader(f))
    with (output_dir / "attempts.csv").open("r", encoding="utf-8", newline="") as f:
        attempt_rows = list(csv.DictReader(f))

    assert len(packet_rows) == 1
    assert packet_rows[0]["outcome"] == "delivered"
    assert packet_rows[0]["finish_time_ms"] == "3.0"
    assert len(attempt_rows) == 3
    assert [int(row["remaining_bits_after"]) for row in attempt_rows] == [1000, 400, 0]


def test_bandwidth_fraction_monotonicity(tmp_path: Path) -> None:
    base = {
        "simulation": {"duration_slots": 200, "slot_time_ms": 1, "random_seed": 2},
        "traffic": {
            "ue": {"count": 1},
            "flows": [
                {
                    "id": "F1",
                    "type": "F1",
                    "arrival": {"model": "periodic", "period_ms": 1},
                    "packet_size_bytes": 200,
                    "deadline_ms": 1000,
                    "priority": 1,
                }
            ],
        },
        "link": {
            "model": "stub_bler",
            "bler_by_flow": {"F1": 0.0},
            "scenario": {"bandwidth_mhz": 20},
            "mcs_efficiency_bpshz": {"QPSK": 1.0, "16QAM": 3.0},
        },
        "retransmission": {"enabled": True, "max_tx": 20, "strategy": "immediate"},
    }

    cfg_full = {**base, "link": {**base["link"], "resource": {"bandwidth_fraction": 1.0}}}
    cfg_small = {**base, "link": {**base["link"], "resource": {"bandwidth_fraction": 0.01}}}

    sim_full = Simulator(config=cfg_full, outputs_root=tmp_path / "full")
    sim_small = Simulator(config=cfg_small, outputs_root=tmp_path / "small")
    sim_full.channel = _AlwaysSuccess16QAMChannel()
    sim_small.channel = _AlwaysSuccess16QAMChannel()

    metrics_full, _ = _run_and_get_output_dir(sim_full, tmp_path / "full")
    metrics_small, _ = _run_and_get_output_dir(sim_small, tmp_path / "small")

    assert metrics_full.throughput_bps > metrics_small.throughput_bps
    assert metrics_small.avg_sojourn_ms >= metrics_full.avg_sojourn_ms


def test_hard_deadline_drop_total_time(tmp_path: Path) -> None:
    config = {
        "simulation": {"duration_slots": 10, "slot_time_ms": 1, "random_seed": 3},
        "traffic": {
            "ue": {"count": 1},
            "flows": [
                {
                    "id": "F1",
                    "type": "F1",
                    "arrival": {"model": "periodic", "period_ms": 1000},
                    "packet_size_bytes": 200,
                    "deadline_ms": 1,
                    "priority": 1,
                }
            ],
        },
        "link": {
            "model": "stub_bler",
            "bler_by_flow": {"F1": 0.0},
            "resource": {"bandwidth_fraction": 0.01},
            "scenario": {"bandwidth_mhz": 20},
            "mcs_efficiency_bpshz": {"QPSK": 1.0, "16QAM": 3.0},
        },
        "retransmission": {"enabled": True, "max_tx": 4, "strategy": "immediate"},
    }

    simulator = Simulator(config=config, outputs_root=tmp_path)
    simulator.channel = _AlwaysSuccess16QAMChannel()
    metrics, output_dir = _run_and_get_output_dir(simulator, tmp_path)

    assert metrics.total_dropped_deadline > 0
    assert metrics.total_delivered == 0

    with (output_dir / "packet_records.csv").open("r", encoding="utf-8", newline="") as f:
        packet_rows = list(csv.DictReader(f))
    with (output_dir / "attempts.csv").open("r", encoding="utf-8", newline="") as f:
        attempt_rows = list(csv.DictReader(f))

    assert len(packet_rows) == 1
    assert packet_rows[0]["outcome"] == "dropped_deadline"
    assert packet_rows[0]["finish_time_ms"] == "1.0"
    assert len(attempt_rows) == 1
