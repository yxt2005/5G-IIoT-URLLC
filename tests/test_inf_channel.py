from __future__ import annotations

import random
from statistics import mean

from src.channel import InFChannelModel
from src.core.types import Packet


def _packet(size_bytes: int = 32) -> Packet:
    return Packet(
        packet_id="P-000001",
        flow_id="F1",
        flow_type="F1",
        arrival_time_ms=0,
        packet_size_bytes=size_bytes,
        deadline_ms=10,
        priority=1,
    )


def _link_cfg(distance_m: float, tx_power_dbm: float = 23.0, mcs_mode: str = "AMC") -> dict:
    scenario = {
        "name": "InF-SL",
        "fc_ghz": 3.5,
        "bandwidth_mhz": 20,
        "tx_power_dbm": tx_power_dbm,
        "noise_figure_db": 7,
        "shadow_sigma_los_db": 4.0,
        "shadow_sigma_nlos_db": 7.0,
        "rician_k_db": 6.0,
        "tu_ms": 1,
    }
    return {
        "model": "inf_channel",
        "scenario": scenario,
        "geometry": {"mode": "fixed_distance", "distance_m": distance_m},
        "phy": {"mcs_mode": mcs_mode, "target_bler": 1e-2, "mcs_list": ["QPSK", "16QAM"]},
    }


def test_inf_channel_reproducibility_with_fixed_seed() -> None:
    model = InFChannelModel(_link_cfg(distance_m=30.0))
    pkt = _packet()

    def seq(seed: int) -> list[tuple[float, str, bool, bool]]:
        rng = random.Random(seed)
        local_model = InFChannelModel(_link_cfg(distance_m=30.0))
        out: list[tuple[float, str, bool, bool]] = []
        for t in range(30):
            r = local_model.is_success(pkt, t_ms=t, rng=rng)
            out.append((round(float(r["snr_db"]), 6), str(r["mcs"]), bool(r["is_los"]), bool(r["success"])))
        return out

    assert seq(123) == seq(123)


def test_inf_channel_mean_snr_decreases_with_distance() -> None:
    pkt = _packet()
    near_model = InFChannelModel(_link_cfg(distance_m=10.0))
    far_model = InFChannelModel(_link_cfg(distance_m=50.0))
    near_rng = random.Random(1)
    far_rng = random.Random(1)

    near_snr = [float(near_model.is_success(pkt, t, near_rng)["snr_db"]) for t in range(200)]
    far_snr = [float(far_model.is_success(pkt, t, far_rng)["snr_db"]) for t in range(200)]

    assert mean(near_snr) > mean(far_snr) + 5.0


def test_amc_selection_is_reasonable_between_good_and_bad_channels() -> None:
    pkt = _packet(size_bytes=32)
    good_model = InFChannelModel(_link_cfg(distance_m=3.0, tx_power_dbm=30.0, mcs_mode="AMC"))
    bad_model = InFChannelModel(_link_cfg(distance_m=150.0, tx_power_dbm=5.0, mcs_mode="AMC"))
    good_rng = random.Random(7)
    bad_rng = random.Random(7)

    good_counts = {"QPSK": 0, "16QAM": 0}
    bad_counts = {"QPSK": 0, "16QAM": 0}
    for t in range(200):
        good_counts[str(good_model.is_success(pkt, t, good_rng)["mcs"])] += 1
        bad_counts[str(bad_model.is_success(pkt, t, bad_rng)["mcs"])] += 1

    assert good_counts["16QAM"] > good_counts["QPSK"]
    assert bad_counts["QPSK"] > bad_counts["16QAM"]


def test_fixed_qpsk_mode_always_selects_qpsk() -> None:
    pkt = _packet(size_bytes=32)
    model = InFChannelModel(_link_cfg(distance_m=30.0, mcs_mode="QPSK"))
    rng = random.Random(5)

    for t in range(20):
        assert model.is_success(pkt, t, rng)["mcs"] == "QPSK"


def test_fixed_16qam_mode_always_selects_16qam() -> None:
    pkt = _packet(size_bytes=32)
    model = InFChannelModel(_link_cfg(distance_m=30.0, mcs_mode="16QAM"))
    rng = random.Random(5)

    for t in range(20):
        assert model.is_success(pkt, t, rng)["mcs"] == "16QAM"


def test_fixed_mode_requires_mcs_in_list() -> None:
    try:
        InFChannelModel(
            {
                "scenario": {"name": "InF-SL"},
                "geometry": {"mode": "fixed_distance", "distance_m": 30.0},
                "phy": {"mcs_mode": "16QAM", "mcs_list": ["QPSK"]},
            }
        )
    except ValueError as exc:
        assert "mcs_mode=16QAM" in str(exc)
    else:
        raise AssertionError("Expected ValueError for fixed MCS not present in mcs_list")


def test_bler_boundary_changes_with_snr() -> None:
    model = InFChannelModel(_link_cfg(distance_m=30.0))
    high_bler = model.compute_bler_for_snr_db(packet_size_bytes=64, snr_db=30.0, mcs="QPSK")
    low_bler = model.compute_bler_for_snr_db(packet_size_bytes=64, snr_db=-5.0, mcs="QPSK")

    assert high_bler < 1e-6
    assert low_bler > 0.1


def test_default_bs_height_in_inf_sl() -> None:
    model = InFChannelModel(
        {
            "scenario": {"name": "InF-SL"},
            "geometry": {"mode": "fixed_distance", "distance_m": 30.0},
        }
    )

    assert model.bs_height_m == 1.5
    assert model.ut_height_m == 1.5


def test_default_bs_height_in_inf_dh() -> None:
    model = InFChannelModel(
        {
            "scenario": {"name": "InF-DH"},
            "geometry": {"mode": "fixed_distance", "distance_m": 30.0},
        }
    )

    assert model.bs_height_m == 8.0
    assert model.ut_height_m == 1.5


def test_yaml_override_heights() -> None:
    model = InFChannelModel(
        {
            "scenario": {"name": "InF-SL", "bs_height_m": 2.0, "ut_height_m": 1.0},
            "geometry": {"mode": "fixed_distance", "distance_m": 30.0},
        }
    )

    assert model.bs_height_m == 2.0
    assert model.ut_height_m == 1.0
