from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.core.simulator import Simulator
from src.utils.config import load_yaml_config


def parse_args() -> argparse.Namespace:
    # CLI 仅保留最小参数：配置文件路径
    parser = argparse.ArgumentParser(description="Run URLLC simulation experiment")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to YAML configuration file",
    )
    return parser.parse_args()


def main() -> None:
    # 初始化基础日志格式，便于实验运行时追踪
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    args = parse_args()
    # 加载配置并构建仿真器
    config = load_yaml_config(args.config)
    simulator = Simulator(config=config, outputs_root=Path("outputs"))
    # 执行仿真（当前阶段为基础骨架）
    simulator.run()


if __name__ == "__main__":
    main()
