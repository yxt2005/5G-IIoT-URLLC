from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.channel.inf_channel import InFChannelModel
from src.utils.config import load_yaml_config


@dataclass(slots=True)
class FlowPlotSpec:
    flow_id: str
    packet_size_bytes: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline BLER vs SNR sweep for fixed packet sizes")
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"), help="Path to YAML config")
    parser.add_argument("--snr-start-db", type=float, default=-5.0, help="Sweep start SNR in dB")
    parser.add_argument("--snr-stop-db", type=float, default=25.0, help="Sweep stop SNR in dB")
    parser.add_argument("--snr-step-db", type=float, default=0.5, help="Sweep step in dB")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("results/amc"),
        help="Directory for CSV and plot outputs",
    )
    return parser.parse_args()


def build_channel_model(config_path: Path) -> InFChannelModel:
    config = load_yaml_config(config_path)
    link_cfg = dict(config.get("link", {}))
    geometry_cfg = dict(link_cfg.get("geometry", {}))
    geometry_cfg.setdefault("mode", "fixed_distance")
    geometry_cfg.setdefault("distance_m", 30.0)
    geometry_cfg.setdefault("ue_count", 1)
    link_cfg["geometry"] = geometry_cfg
    return InFChannelModel(link_cfg)


def load_flows(config_path: Path) -> list[FlowPlotSpec]:
    config = load_yaml_config(config_path)
    traffic_cfg = config.get("traffic", {})
    flows_cfg = traffic_cfg.get("flows", [])
    if not isinstance(flows_cfg, list):
        raise ValueError("traffic.flows must be a list")

    flows: list[FlowPlotSpec] = []
    for flow in flows_cfg:
        if not isinstance(flow, dict):
            raise ValueError("each traffic flow must be a mapping")
        flow_id = flow.get("id")
        packet_size_value = flow.get("packet_size_bytes")
        if flow_id is None or packet_size_value is None:
            raise ValueError("each traffic flow must define id and packet_size_bytes")
        flows.append(FlowPlotSpec(flow_id=str(flow_id), packet_size_bytes=int(packet_size_value)))
    return flows


def frange(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 6))
        current += step
    return values


def save_csv(
    output_path: Path,
    snr_values: list[float],
    bler_qpsk: list[float],
    bler_16qam: list[float],
) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["snr_db", "bler_qpsk", "bler_16qam"])
        writer.writeheader()
        for snr_db, qpsk, qam16 in zip(snr_values, bler_qpsk, bler_16qam):
            writer.writerow({"snr_db": snr_db, "bler_qpsk": qpsk, "bler_16qam": qam16})


def save_plot(
    output_path: Path,
    flow_id: str,
    packet_size_bytes: int,
    snr_values: list[float],
    bler_qpsk: list[float],
    bler_16qam: list[float],
) -> None:
    plt.figure(figsize=(8, 5))
    plt.semilogy(snr_values, bler_qpsk, label="QPSK", linewidth=2)
    plt.semilogy(snr_values, bler_16qam, label="16QAM", linewidth=2)
    plt.xlabel("SNR (dB)")
    plt.ylabel("BLER")
    plt.title(f"BLER vs SNR for {flow_id} ({packet_size_bytes} bytes)")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


def main() -> None:
    args = parse_args()
    if args.snr_step_db <= 0:
        raise ValueError("--snr-step-db must be > 0")
    if args.snr_stop_db < args.snr_start_db:
        raise ValueError("--snr-stop-db must be >= --snr-start-db")

    model = build_channel_model(args.config)
    flows = load_flows(args.config)
    snr_values = frange(args.snr_start_db, args.snr_stop_db, args.snr_step_db)

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    for flow in flows:
        flow_id = flow.flow_id
        packet_size_bytes = flow.packet_size_bytes
        bler_qpsk = [
            model.compute_bler_for_snr_db_raw(packet_size_bytes=packet_size_bytes, snr_db=snr_db, mcs="QPSK")
            for snr_db in snr_values
        ]
        bler_16qam = [
            model.compute_bler_for_snr_db_raw(packet_size_bytes=packet_size_bytes, snr_db=snr_db, mcs="16QAM")
            for snr_db in snr_values
        ]

        csv_path = output_dir / f"bler_sweep_{flow_id}.csv"
        fig_path = output_dir / f"bler_vs_snr_{flow_id}.png"
        save_csv(csv_path, snr_values, bler_qpsk, bler_16qam)
        save_plot(fig_path, flow_id, packet_size_bytes, snr_values, bler_qpsk, bler_16qam)
        print(f"[{flow_id}] Saved CSV: {csv_path}")
        print(f"[{flow_id}] Saved plot: {fig_path}")


if __name__ == "__main__":
    main()
