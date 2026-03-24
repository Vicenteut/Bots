from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

try:
    from dotenv import load_dotenv as _dotenv_load
except ImportError:
    _dotenv_load = None

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
IMAGES_DIR = BASE_DIR / "images"
CUSTOM_IMAGES_DIR = IMAGES_DIR / "custom"
CUSTOM_IMAGES_METADATA = IMAGES_DIR / "custom_images.json"
COOKIES_PATH = BASE_DIR / "cookies.json"
BACKUPS_DIR = BASE_DIR / "backups"
LOGS_DIR = BASE_DIR / "logs"


def load_environment(env_path: Path | None = None) -> Path:
    target = env_path or ENV_PATH
    if _dotenv_load is not None and target.exists():
        _dotenv_load(target)
    return target


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def get_required_env(name: str, *, cast: Optional[Callable[[str], object]] = None):
    value = os.getenv(name)
    if value in (None, ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return cast(value) if cast else value


def get_optional_int(name: str, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return int(value)


def get_bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_optional_float(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    return float(value)

def get_list_env(name: str, *, separator: str = ",") -> list[str]:
    value = os.getenv(name, "")
    if not value:
        return []
    return [item.strip() for item in value.split(separator) if item.strip()]

load_environment()
