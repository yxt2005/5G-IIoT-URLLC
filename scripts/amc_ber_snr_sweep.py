from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.channel.inf_channel import InFChannelModel
from src.utils.config import load_yaml_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline BER vs SNR sweep for AMC analysis")
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


def frange(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 6))
        current += step
    return values


def find_intersection(
    snr_values: list[float],
    ber_qpsk: list[float],
    ber_16qam: list[float],
) -> tuple[float, float] | None:
    meaningful_floor = 1e-15
    diffs = [q - q16 for q, q16 in zip(ber_qpsk, ber_16qam)]
    for idx in range(1, len(diffs)):
        prev_diff = diffs[idx - 1]
        cur_diff = diffs[idx]
        prev_min_ber = min(ber_qpsk[idx - 1], ber_16qam[idx - 1])
        cur_min_ber = min(ber_qpsk[idx], ber_16qam[idx])
        if prev_min_ber <= meaningful_floor and cur_min_ber <= meaningful_floor:
            continue
        if prev_diff * cur_diff < 0:
            x0 = snr_values[idx - 1]
            x1 = snr_values[idx]
            y0 = prev_diff
            y1 = cur_diff
            if x1 == x0 or y1 == y0:
                snr_cross = x0
            else:
                snr_cross = x0 - y0 * (x1 - x0) / (y1 - y0)
            ber_cross = ber_qpsk[idx - 1] + (ber_qpsk[idx] - ber_qpsk[idx - 1]) * (
                (snr_cross - x0) / max(1e-12, (x1 - x0))
            )
            return snr_cross, ber_cross
    return None


def save_csv(output_path: Path, snr_values: list[float], ber_qpsk: list[float], ber_16qam: list[float]) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["snr_db", "ber_qpsk", "ber_16qam"])
        writer.writeheader()
        for snr_db, qpsk, qam16 in zip(snr_values, ber_qpsk, ber_16qam):
            writer.writerow({"snr_db": snr_db, "ber_qpsk": qpsk, "ber_16qam": qam16})


def save_plot(
    output_path: Path,
    snr_values: list[float],
    ber_qpsk: list[float],
    ber_16qam: list[float],
    intersection: tuple[float, float] | None,
) -> None:
    plt.figure(figsize=(8, 5))
    plt.semilogy(snr_values, ber_qpsk, label="QPSK", linewidth=2)
    plt.semilogy(snr_values, ber_16qam, label="16QAM", linewidth=2)
    plt.xlabel("SNR (dB)")
    plt.ylabel("BER")
    plt.title("BER vs SNR for AMC Candidates")
    plt.grid(True, which="both", linestyle="--", alpha=0.5)
    plt.legend()

    if intersection is not None:
        snr_cross, ber_cross = intersection
        plt.scatter([snr_cross], [ber_cross], color="red", zorder=3)
        plt.annotate(
            f"Intersection: {snr_cross:.2f} dB",
            xy=(snr_cross, ber_cross),
            xytext=(snr_cross + 1.0, min(0.5, ber_cross * 2.0)),
            arrowprops={"arrowstyle": "->"},
        )
    else:
        plt.text(
            0.03,
            0.08,
            "No meaningful BER intersection in sweep range",
            transform=plt.gca().transAxes,
            bbox={"facecolor": "white", "alpha": 0.8, "edgecolor": "gray"},
        )

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
    snr_values = frange(args.snr_start_db, args.snr_stop_db, args.snr_step_db)
    ber_qpsk = [model.compute_ber_for_snr_db_raw(snr_db=snr_db, mcs="QPSK") for snr_db in snr_values]
    ber_16qam = [model.compute_ber_for_snr_db_raw(snr_db=snr_db, mcs="16QAM") for snr_db in snr_values]

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "ber_sweep.csv"
    fig_path = output_dir / "ber_vs_snr.png"

    save_csv(csv_path, snr_values, ber_qpsk, ber_16qam)
    intersection = find_intersection(snr_values, ber_qpsk, ber_16qam)
    save_plot(fig_path, snr_values, ber_qpsk, ber_16qam, intersection)

    if intersection is None:
        print(f"Saved CSV: {csv_path}")
        print(f"Saved plot: {fig_path}")
        print("Intersection: none within sweep range")
    else:
        snr_cross, ber_cross = intersection
        print(f"Saved CSV: {csv_path}")
        print(f"Saved plot: {fig_path}")
        print(f"Intersection SNR: {snr_cross:.3f} dB, BER: {ber_cross:.6e}")


if __name__ == "__main__":
    main()
