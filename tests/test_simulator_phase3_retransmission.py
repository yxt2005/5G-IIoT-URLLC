from __future__ import annotations

from pathlib import Path

from src.core.simulator import Simulator


def _base_config() -> dict:
    return {
        "simulation": {"duration_slots": 20, "slot_time_ms": 1, "random_seed": 42},
        "traffic": {
            "ue": {"count": 1},
            "flows": [
                {
                    "id": "F1",
                    "type": "F1",
                    "arrival": {"model": "periodic", "period_ms": 5},
                    "packet_size_bytes": 32,
                    "deadline_ms": 100,
                    "priority": 1,
                }
            ],
        },
        "link": {
            "model": "stub_bler",
            "bler_by_flow": {"F1": 0.0},
            "resource": {"bandwidth_fraction": 1.0},
            "scenario": {"bandwidth_mhz": 20},
            "mcs_efficiency_bpshz": {"QPSK": 1.0, "16QAM": 3.0},
        },
        "retransmission": {"enabled": True, "max_tx": 4, "strategy": "immediate"},
    }


def test_bler_one_drops_by_max_tx_without_infinite_loop(tmp_path: Path) -> None:
    config = _base_config()
    config["simulation"]["duration_slots"] = 12
    config["traffic"]["flows"][0]["arrival"]["period_ms"] = 100
    config["link"]["bler_by_flow"]["F1"] = 1.0
    config["retransmission"]["max_tx"] = 3

    metrics = Simulator(config=config, outputs_root=tmp_path).run()

    assert metrics.total_arrivals == 1
    assert metrics.total_tx_attempts == 3
    assert metrics.total_dropped_max_tx == 1
    assert metrics.total_delivered == 0


def test_bler_zero_delivers_all_with_single_tx(tmp_path: Path) -> None:
    config = _base_config()
    config["simulation"]["duration_slots"] = 10
    config["traffic"]["flows"][0]["arrival"]["period_ms"] = 1
    config["traffic"]["flows"][0]["deadline_ms"] = 10
    config["link"]["bler_by_flow"]["F1"] = 0.0
    config["retransmission"]["max_tx"] = 4

    metrics = Simulator(config=config, outputs_root=tmp_path).run()

    assert metrics.total_delivered == metrics.total_arrivals
    assert metrics.avg_tx_per_delivered == 1.0
    assert metrics.total_dropped_max_tx == 0


def test_fixed_seed_mid_bler_is_reproducible(tmp_path: Path) -> None:
    config = _base_config()
    config["simulation"]["duration_slots"] = 40
    config["traffic"]["flows"][0]["arrival"]["period_ms"] = 2
    config["link"]["bler_by_flow"]["F1"] = 0.5
    config["retransmission"]["max_tx"] = 4

    metrics1 = Simulator(config=config, outputs_root=tmp_path / "run1").run()
    metrics2 = Simulator(config=config, outputs_root=tmp_path / "run2").run()

    assert metrics1.total_delivered == metrics2.total_delivered
    assert metrics1.total_tx_attempts == metrics2.total_tx_attempts
