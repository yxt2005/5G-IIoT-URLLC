from __future__ import annotations

import argparse
from pathlib import Path

from src.core.simulator import Simulator
from src.utils.config import load_yaml_config


def _print_table(title: str, rows: list[dict[str, float | str]]) -> None:
    print(title)
    if not rows:
        print("  <empty>")
        return

    headers = list(rows[0].keys())
    widths = {header: max(len(header), max(len(str(row[header])) for row in rows)) for header in headers}
    print("  " + " | ".join(header.ljust(widths[header]) for header in headers))
    print("  " + "-+-".join("-" * widths[header] for header in headers))
    for row in rows:
        print("  " + " | ".join(str(row[header]).ljust(widths[header]) for header in headers))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run regression cases for URLLC simulator")
    parser.add_argument(
        "--configs-dir",
        type=Path,
        default=Path("configs/regression"),
        help="Directory containing regression YAML cases",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_paths = sorted(args.configs_dir.glob("*.yaml"))
    if not config_paths:
        raise SystemExit(f"No regression configs found in {args.configs_dir}")

    for config_path in config_paths:
        config = load_yaml_config(config_path)
        simulator = Simulator(config=config, outputs_root=Path("outputs") / "regression")
        metrics = simulator.run()

        print(f"\n== {config_path.stem} ==")
        _print_table(
            "Per-flow KPI",
            [
                {
                    "flow": flow_id,
                    "delivery_ratio": round(values["delivery_ratio"], 4),
                    "deadline_miss_ratio": round(values["deadline_miss_ratio"], 4),
                    "p99_sojourn_ms": round(values["p99_sojourn_ms"], 4),
                    "throughput_bps": round(values["throughput_bps"], 2),
                }
                for flow_id, values in metrics.per_flow_kpis.items()
            ],
        )
        _print_table(
            "Per-UE KPI",
            [
                {
                    "ue": ue_id,
                    "delivery_ratio": round(values["delivery_ratio"], 4),
                    "deadline_miss_ratio": round(values["deadline_miss_ratio"], 4),
                    "p99_sojourn_ms": round(values["p99_sojourn_ms"], 4),
                    "throughput_bps": round(values["throughput_bps"], 2),
                }
                for ue_id, values in metrics.per_ue_kpis.items()
            ],
        )


if __name__ == "__main__":
    main()
