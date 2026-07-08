"""Whisper ASR defaults (env WHISPER_MODEL overrides)."""

from __future__ import annotations

import os

VALID_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")

DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small").strip().lower() or "small"


def resolve_whisper_model(name: str | None) -> str:
    model = (name or DEFAULT_WHISPER_MODEL).strip().lower()
    if model in VALID_WHISPER_MODELS:
        return model
    return DEFAULT_WHISPER_MODEL if DEFAULT_WHISPER_MODEL in VALID_WHISPER_MODELS else "small"
