"""trace-span: lightweight span/timing context manager for agent steps."""

from .core import Span, SpanRecorder, SpanError

__all__ = ["Span", "SpanRecorder", "SpanError"]
