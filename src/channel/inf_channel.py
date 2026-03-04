from __future__ import annotations

import math
import random
from typing import Any

from src.channel.base import ChannelEvalResult
from src.core.types import Packet


class InFChannelModel:
    """Minimal 3GPP InF-style channel model with per-UE geometry support."""

    def __init__(self, link_config: dict[str, Any]) -> None:
        scenario_cfg = link_config.get("scenario", {})
        geometry_cfg = link_config.get("geometry", {})
        resource_cfg = link_config.get("resource", {})
        phy_cfg = link_config.get("phy", {})
        legacy_amc_cfg = link_config.get("amc", {})

        self.scenario_name = str(scenario_cfg.get("name", "InF-SL")).upper()
        self.fc_ghz = float(scenario_cfg.get("fc_ghz", 3.5))
        self.bandwidth_mhz = float(scenario_cfg.get("bandwidth_mhz", 20.0))
        self.bandwidth_fraction = float(resource_cfg.get("bandwidth_fraction", 0.8))
        if not (0.0 < self.bandwidth_fraction <= 1.0):
            raise ValueError("link.resource.bandwidth_fraction must be in (0, 1]")
        self.bandwidth_eff_mhz = self.bandwidth_mhz * self.bandwidth_fraction
        self.tx_power_dbm = float(scenario_cfg.get("tx_power_dbm", 23.0))
        self.noise_figure_db = float(scenario_cfg.get("noise_figure_db", 7.0))
        default_bs_h = 1.5 if self.scenario_name in {"INF-SL", "INF-DL"} else 8.0
        self.bs_height_m = float(scenario_cfg.get("bs_height_m", default_bs_h))
        self.ut_height_m = float(scenario_cfg.get("ut_height_m", 1.5))
        if self.bs_height_m <= 0 or self.ut_height_m <= 0:
            raise ValueError("bs_height_m and ut_height_m must be > 0")
        self.shadow_sigma_los_db = float(scenario_cfg.get("shadow_sigma_los_db", 4.3))
        self.shadow_sigma_nlos_db = float(scenario_cfg.get("shadow_sigma_nlos_db", self._default_nlos_sigma_db()))
        self.rician_k_db = float(scenario_cfg.get("rician_k_db", 6.0))
        self.tu_ms = max(1, int(scenario_cfg.get("tu_ms", 1)))

        self.geometry_mode = str(geometry_cfg.get("mode", "per_ue_fixed_distance"))
        self.ue_count = max(1, int(geometry_cfg.get("ue_count", 1)))
        self._geometry_rng = random.Random(int(geometry_cfg.get("distance_seed", 0)))
        self._distance_by_ue = self._build_distance_map(geometry_cfg)

        self.mcs_mode = str(phy_cfg.get("mcs_mode", "AMC")).upper()
        if self.mcs_mode not in {"QPSK", "16QAM", "AMC"}:
            raise ValueError("link.phy.mcs_mode must be one of ['QPSK', '16QAM', 'AMC']")
        self.target_bler = float(phy_cfg.get("target_bler", legacy_amc_cfg.get("target_bler", 1e-2)))
        self.mcs_list = [
            str(x).upper() for x in phy_cfg.get("mcs_list", legacy_amc_cfg.get("mcs_list", ["QPSK", "16QAM"]))
        ]
        if not self.mcs_list:
            self.mcs_list = ["QPSK"]
        if self.mcs_mode != "AMC" and self.mcs_mode not in self.mcs_list:
            raise ValueError(
                f"Configured mcs_mode={self.mcs_mode} is not present in link.phy.mcs_list={self.mcs_list}"
            )

        self._cached_states: dict[tuple[int, int], dict[str, float | bool]] = {}

    def bler(self, packet: Packet, t_ms: int) -> float:
        state = self._sample_block_state(packet=packet, t_ms=t_ms, rng=random.Random(0))
        mcs = self._select_mcs(packet, float(state["snr_db"]))[0]
        return self.compute_bler_for_snr_db(packet.packet_size_bytes, float(state["snr_db"]), mcs)

    def is_success(self, packet: Packet, t_ms: int, rng: random.Random) -> ChannelEvalResult:
        state = self._sample_block_state(packet=packet, t_ms=t_ms, rng=rng)
        snr_db = float(state["snr_db"])
        is_los = bool(state["is_los"])

        mcs, bler_value = self._select_mcs(packet, snr_db)
        success = rng.random() >= bler_value
        return {
            "success": success,
            "bler": bler_value,
            "snr_db": snr_db,
            "mcs": mcs,
            "is_los": is_los,
        }

    def spectral_efficiency(self, mcs: str, default_efficiency: dict[str, float]) -> float:
        if mcs not in default_efficiency:
            raise ValueError(f"Missing MCS efficiency for {mcs}")
        return default_efficiency[mcs]

    def compute_bler_for_snr_db(self, packet_size_bytes: int, snr_db: float, mcs: str) -> float:
        ber = self.compute_ber_for_snr_db(snr_db=snr_db, mcs=mcs)
        n_bits = max(1, int(packet_size_bytes) * 8)
        bler = 1.0 - (1.0 - ber) ** n_bits
        return min(max(bler, 1e-12), 1.0 - 1e-12)

    def compute_bler_for_snr_db_raw(self, packet_size_bytes: int, snr_db: float, mcs: str) -> float:
        ber = self.compute_ber_for_snr_db_raw(snr_db=snr_db, mcs=mcs)
        n_bits = max(1, int(packet_size_bytes) * 8)
        bler = 1.0 - (1.0 - ber) ** n_bits
        return min(max(bler, 1e-300), 1.0 - 1e-12)

    def compute_ber_for_snr_db_raw(self, snr_db: float, mcs: str) -> float:
        gamma = max(1e-300, 10 ** (snr_db / 10.0))
        mcs_u = mcs.upper()
        if mcs_u == "QPSK":
            ber = self._qfunc(math.sqrt(gamma))
        elif mcs_u == "16QAM":
            ber = 0.75 * self._qfunc(math.sqrt(0.2 * gamma))
        else:
            raise ValueError(f"Unsupported MCS: {mcs}")
        return max(ber, 1e-300)

    def compute_ber_for_snr_db(self, snr_db: float, mcs: str) -> float:
        ber = self.compute_ber_for_snr_db_raw(snr_db=snr_db, mcs=mcs)
        return min(max(ber, 1e-12), 0.5)

    def _select_mcs(self, packet: Packet, snr_db: float) -> tuple[str, float]:
        available = [m for m in self.mcs_list if m in {"QPSK", "16QAM"}]
        if not available:
            available = ["QPSK"]

        if self.mcs_mode != "AMC":
            mcs = self.mcs_mode
            return mcs, self.compute_bler_for_snr_db(packet.packet_size_bytes, snr_db, mcs)

        qpsk_bler = self.compute_bler_for_snr_db(packet.packet_size_bytes, snr_db, "QPSK")
        qam16_bler = self.compute_bler_for_snr_db(packet.packet_size_bytes, snr_db, "16QAM")

        if "16QAM" in available and qam16_bler <= self.target_bler:
            return "16QAM", qam16_bler
        if "QPSK" in available:
            return "QPSK", qpsk_bler
        return "16QAM", qam16_bler

    def _build_distance_map(self, geometry_cfg: dict[str, Any]) -> list[float]:
        if self.geometry_mode == "fixed_distance":
            distance = float(geometry_cfg.get("distance_m", 30.0))
            if distance <= 0:
                raise ValueError("geometry.distance_m must be > 0")
            return [distance] * self.ue_count

        if self.geometry_mode == "per_ue_fixed_distance":
            distances = [float(x) for x in geometry_cfg.get("distances_m", [])]
            default_distance = float(geometry_cfg.get("distance_m", 30.0))
            return self._normalize_distances(distances, default_distance)

        if self.geometry_mode == "per_ue_random_distance":
            d_min = float(geometry_cfg.get("distance_min_m", 10.0))
            d_max = float(geometry_cfg.get("distance_max_m", 60.0))
            if d_min <= 0 or d_max <= 0 or d_min > d_max:
                raise ValueError("geometry.distance_min_m and distance_max_m must define a positive interval")
            return [self._geometry_rng.uniform(d_min, d_max) for _ in range(self.ue_count)]

        raise ValueError(f"Unsupported geometry.mode: {self.geometry_mode}")

    def _normalize_distances(self, distances: list[float], default_distance: float) -> list[float]:
        normalized = [d for d in distances if d > 0]
        if not normalized:
            normalized = [default_distance]
        while len(normalized) < self.ue_count:
            normalized.append(normalized[-1])
        return normalized[: self.ue_count]

    def _distance_for_ue(self, ue_id: int) -> float:
        if 0 <= ue_id < len(self._distance_by_ue):
            return self._distance_by_ue[ue_id]
        return self._distance_by_ue[-1]

    def _sample_block_state(self, packet: Packet, t_ms: int, rng: random.Random) -> dict[str, float | bool]:
        block_idx = t_ms // self.tu_ms
        cache_key = (block_idx, packet.ue_id)
        if cache_key in self._cached_states:
            return self._cached_states[cache_key]

        d2d = self._distance_for_ue(packet.ue_id)
        d3d = math.sqrt(d2d * d2d + (self.bs_height_m - self.ut_height_m) ** 2)

        p_los = self._p_los(d2d)
        is_los = rng.random() < p_los

        pathloss_db = self._pathloss_db(d3d, is_los)
        sigma_db = self.shadow_sigma_los_db if is_los else self.shadow_sigma_nlos_db
        shadow_db = rng.gauss(0.0, sigma_db)
        total_pl_db = pathloss_db + shadow_db

        rx_power_dbm = self.tx_power_dbm - total_pl_db
        noise_power_dbm = self._noise_power_dbm()
        avg_snr_db = rx_power_dbm - noise_power_dbm
        avg_snr_linear = 10 ** (avg_snr_db / 10.0)

        g = self._sample_power_gain(is_los=is_los, rng=rng)
        inst_snr_linear = max(1e-12, avg_snr_linear * g)
        snr_db = 10.0 * math.log10(inst_snr_linear)

        state = {"is_los": is_los, "snr_db": snr_db}
        self._cached_states[cache_key] = state
        return state

    def _p_los(self, d2d_m: float) -> float:
        r, hc, d_clutter = self._scenario_clutter_params()
        if r <= 0 or r >= 1:
            return 0.0
        k_subsce = -d_clutter / math.log(1.0 - r)
        if self.scenario_name in {"INF-SH", "INF-DH"}:
            denom = max(1e-6, hc - self.ut_height_m)
            height_factor = max(0.1, (self.bs_height_m - self.ut_height_m) / denom)
            k_subsce *= height_factor
        p = math.exp(-d2d_m / max(1e-6, k_subsce))
        return min(max(p, 0.0), 1.0)

    def _pathloss_db(self, d3d_m: float, is_los: bool) -> float:
        fc = self.fc_ghz
        pl_los = 31.84 + 21.5 * math.log10(d3d_m) + 19.0 * math.log10(fc)
        if is_los:
            return pl_los

        if self.scenario_name == "INF-SL":
            pl_sl = 33.0 + 25.5 * math.log10(d3d_m) + 20.0 * math.log10(fc)
            return max(pl_sl, pl_los)
        if self.scenario_name == "INF-DL":
            pl_sl = 33.0 + 25.5 * math.log10(d3d_m) + 20.0 * math.log10(fc)
            pl_dl = 18.6 + 35.7 * math.log10(d3d_m) + 20.0 * math.log10(fc)
            return max(pl_dl, pl_los, pl_sl)
        if self.scenario_name == "INF-SH":
            pl_sh = 32.4 + 23.0 * math.log10(d3d_m) + 20.0 * math.log10(fc)
            return max(pl_sh, pl_los)
        if self.scenario_name == "INF-DH":
            pl_dh = 33.63 + 21.9 * math.log10(d3d_m) + 20.0 * math.log10(fc)
            return max(pl_dh, pl_los)
        raise ValueError(f"Unsupported InF scenario: {self.scenario_name}")

    def _noise_power_dbm(self) -> float:
        bandwidth_hz = self.bandwidth_eff_mhz * 1e6
        return -174.0 + 10.0 * math.log10(bandwidth_hz) + self.noise_figure_db

    def _sample_power_gain(self, is_los: bool, rng: random.Random) -> float:
        if not is_los:
            return self._sample_rayleigh_power_gain(rng)
        return self._sample_rician_power_gain(rng)

    @staticmethod
    def _sample_rayleigh_power_gain(rng: random.Random) -> float:
        x = rng.gauss(0.0, 1.0 / math.sqrt(2.0))
        y = rng.gauss(0.0, 1.0 / math.sqrt(2.0))
        return max(1e-12, x * x + y * y)

    def _sample_rician_power_gain(self, rng: random.Random) -> float:
        k_linear = 10 ** (self.rician_k_db / 10.0)
        phi = rng.uniform(0.0, 2.0 * math.pi)
        los_amp = math.sqrt(k_linear / (k_linear + 1.0))
        scat_amp = math.sqrt(1.0 / (k_linear + 1.0))
        gx = rng.gauss(0.0, 1.0 / math.sqrt(2.0))
        gy = rng.gauss(0.0, 1.0 / math.sqrt(2.0))
        hx = los_amp * math.cos(phi) + scat_amp * gx
        hy = los_amp * math.sin(phi) + scat_amp * gy
        return max(1e-12, hx * hx + hy * hy)

    def _scenario_clutter_params(self) -> tuple[float, float, float]:
        table = {
            "INF-SL": (0.2, 2.0, 10.0),
            "INF-DL": (0.6, 6.0, 2.0),
            "INF-SH": (0.2, 2.0, 10.0),
            "INF-DH": (0.6, 6.0, 2.0),
        }
        return table.get(self.scenario_name, table["INF-SL"])

    def _default_nlos_sigma_db(self) -> float:
        table = {
            "INF-SL": 5.7,
            "INF-DL": 7.2,
            "INF-SH": 5.9,
            "INF-DH": 4.0,
        }
        return table.get(self.scenario_name, 5.7)

    @staticmethod
    def _qfunc(x: float) -> float:
        return 0.5 * math.erfc(x / math.sqrt(2.0))
