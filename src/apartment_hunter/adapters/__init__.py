"""Adapter registry for source-specific integrations."""

from __future__ import annotations

from collections.abc import Callable

from apartment_hunter.adapters.krisha.adapter import KrishaAdapter
from apartment_hunter.core.interfaces import SourceAdapter

AdapterFactory = Callable[..., SourceAdapter]


def get_default_adapters() -> dict[str, AdapterFactory]:
    """Return the built-in source adapter registry."""
    return {"krisha.kz": KrishaAdapter}
