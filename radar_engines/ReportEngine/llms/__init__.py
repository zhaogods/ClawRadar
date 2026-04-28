"""
Report Engine LLM子模块。

目前主要暴露 OpenAI 兼容的 `LLMClient` 封装。
"""

from .base import LLMClient, is_retryable_stream_error

__all__ = ["LLMClient", "is_retryable_stream_error"]
