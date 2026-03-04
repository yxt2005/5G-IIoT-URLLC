from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    # 统一转为 Path，兼容字符串路径与 Path 对象
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        # 空文件时返回空字典，避免 None 影响后续逻辑
        data = yaml.safe_load(f) or {}

    # 约束配置根节点必须为映射类型（YAML 字典）
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")
    return data
