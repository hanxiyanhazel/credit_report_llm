from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_dir: Path
    data_root: Path
    qwen_api_base: str
    qwen_api_key: str
    qwen_model: str
    qwen_timeout_seconds: float

    @property
    def is_qwen_configured(self) -> bool:
        return bool(self.qwen_api_base and self.qwen_api_key and self.qwen_model)


def _read_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return max(1.0, float(raw))
    except ValueError:
        return default


def load_settings() -> Settings:
    app_dir = Path(__file__).resolve().parent
    data_root_raw = os.getenv("CREDIT_DEMO_2_DATA_ROOT", "").strip()
    data_root = Path(data_root_raw).expanduser() if data_root_raw else (app_dir / "data")

    return Settings(
        app_dir=app_dir,
        data_root=data_root.resolve(),
        qwen_api_base=os.getenv("QWEN_API_BASE", "").strip(),
        qwen_api_key=os.getenv("QWEN_API_KEY", "").strip(),
        qwen_model=os.getenv("QWEN_MODEL", "").strip(),
        qwen_timeout_seconds=_read_float("QWEN_TIMEOUT_SECONDS", 60.0),
    )


SETTINGS = load_settings()
