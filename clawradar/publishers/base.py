"""Shared publisher protocol types.

This package is reserved for channel-specific publishing adapters such as
WeChat Official Account, Feishu, webhook-based publishers, and future sinks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True)
class PublisherError:
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublishReceipt:
    channel: str
    target: str
    status: str
    external_id: Optional[str] = None
    external_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PublisherResult:
    ok: bool
    receipt: Optional[PublishReceipt] = None
    error: Optional[PublisherError] = None
