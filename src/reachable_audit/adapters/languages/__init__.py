"""Source-language adapter registry and extension detection."""

from .registry import LANGUAGE_ADAPTERS, detect_language

__all__ = ["LANGUAGE_ADAPTERS", "detect_language"]