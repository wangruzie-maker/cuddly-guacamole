"""Load local .env into process environment (no third-party dependency)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_LOADED = False


def load_dotenv(path: Path | None = None, *, override: bool = False) -> Path | None:
    """Parse KEY=VALUE lines from .env into os.environ.

    By default does not overwrite variables already present in the environment.
    """
    global _LOADED
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return None
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        if override or key not in os.environ or not str(os.environ.get(key) or "").strip():
            os.environ[key] = value
    _LOADED = True
    return env_path


def upsert_env_values(updates: dict[str, str], path: Path | None = None) -> Path:
    """Create or update KEY=VALUE entries in .env and refresh os.environ."""
    env_path = path or (ROOT / ".env")
    lines: list[str] = []
    if env_path.is_file():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    remaining = {str(k): str(v) for k, v in updates.items() if k}
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")
        for key, value in remaining.items():
            out.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    for key, value in updates.items():
        if key:
            os.environ[key] = str(value)
    return env_path


def mask_secret(value: str, *, keep_head: int = 6, keep_tail: int = 4) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= keep_head + keep_tail:
        return "*" * len(text)
    return f"{text[:keep_head]}…{text[-keep_tail:]}"
