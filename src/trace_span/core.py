"""Lightweight span/timing context manager for agent steps.

No external dependencies. Works with any agent framework.
"""

from __future__ import annotations

import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class SpanError(Exception):
    """Raised on invalid span operations."""


@dataclass
class Span:
    """A single timed span.

    Attributes:
        name: span name (e.g. "llm_call", "web_search").
        started_at: Unix timestamp when the span started.
        ended_at: Unix timestamp when the span ended (None if still open).
        tags: key-value metadata attached at start.
        attrs: key-value attributes set during the span.
        error: error message if the span ended with an exception.
        ok: True if the span completed without error.
    """

    name: str
    started_at: float
    ended_at: float | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    attrs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        """Duration in milliseconds, or None if still open."""
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at) * 1000

    @property
    def ok(self) -> bool:
        """True if the span ended without error."""
        return self.ended_at is not None and self.error is None

    @property
    def is_open(self) -> bool:
        """True if the span has not yet ended."""
        return self.ended_at is None

    def set(self, key: str, value: Any) -> "Span":
        """Set an attribute on the span. Returns self for chaining."""
        self.attrs[key] = value
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "name": self.name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "tags": dict(self.tags),
            "attrs": dict(self.attrs),
            "error": self.error,
            "ok": self.ok,
        }

    def __repr__(self) -> str:
        dur = f"{self.duration_ms:.1f}ms" if self.duration_ms is not None else "open"
        return f"Span(name={self.name!r}, duration={dur}, ok={self.ok})"


class _SpanContext:
    """Context manager returned by SpanRecorder.span()."""

    def __init__(self, span: Span, recorder: "SpanRecorder") -> None:
        self._span = span
        self._recorder = recorder

    def __enter__(self) -> Span:
        return self._span

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._span.ended_at = time.time()
        if exc_val is not None:
            self._span.error = str(exc_val)
        self._recorder._record(self._span)
        return None  # never suppress exceptions


class SpanRecorder:
    """Collect spans from an agent run.

    Example::

        recorder = SpanRecorder()

        with recorder.span("llm_call", tags={"model": "claude-3"}) as span:
            response = client.messages.create(...)
            span.set("tokens_out", 150)

        with recorder.span("web_search") as span:
            result = search(query)

        print(recorder.total_duration_ms())
        recorder.save("run.jsonl")

    Args:
        path: optional JSONL file path; completed spans are appended there.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._spans: list[Span] = []
        self._path: Path | None = Path(path) if path else None

    # ------------------------------------------------------------------
    # Context manager factory
    # ------------------------------------------------------------------

    def span(
        self,
        name: str,
        *,
        tags: dict[str, Any] | None = None,
    ) -> _SpanContext:
        """Start a new span as a context manager.

        Args:
            name: span name.
            tags: optional key-value metadata.

        Returns:
            Context manager; yields the Span object.

        Example::

            with recorder.span("tool_call", tags={"tool": "search"}) as s:
                result = search(q)
                s.set("result_count", len(result))
        """
        s = Span(
            name=name,
            started_at=time.time(),
            tags=dict(tags) if tags else {},
        )
        return _SpanContext(s, self)

    # ------------------------------------------------------------------
    # Manual span (for async or callback-style code)
    # ------------------------------------------------------------------

    def start(self, name: str, *, tags: dict[str, Any] | None = None) -> Span:
        """Start a span without a context manager. Call finish() to end it."""
        return Span(
            name=name,
            started_at=time.time(),
            tags=dict(tags) if tags else {},
        )

    def finish(self, span: Span, *, error: str | None = None) -> None:
        """End a manually started span and record it."""
        if not span.is_open:
            raise SpanError(f"span {span.name!r} is already finished")
        span.ended_at = time.time()
        span.error = error
        self._record(span)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def spans(self) -> list[Span]:
        """Return all completed spans in order."""
        return list(self._spans)

    def by_name(self, name: str) -> list[Span]:
        """Return all spans with the given name."""
        return [s for s in self._spans if s.name == name]

    def errors(self) -> list[Span]:
        """Return spans that ended with an error."""
        return [s for s in self._spans if s.error is not None]

    def total_duration_ms(self) -> float:
        """Sum of all span durations in milliseconds."""
        return sum(s.duration_ms or 0.0 for s in self._spans)

    def count(self) -> int:
        """Number of recorded spans."""
        return len(self._spans)

    def clear(self) -> None:
        """Remove all recorded spans."""
        self._spans.clear()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Save all spans to a JSONL file."""
        p = Path(path)
        with p.open("w", encoding="utf-8") as f:
            for s in self._spans:
                f.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> "SpanRecorder":
        """Load spans from a JSONL file."""
        recorder = cls()
        p = Path(path)
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            span = Span(
                name=d["name"],
                started_at=d["started_at"],
                ended_at=d.get("ended_at"),
                tags=d.get("tags", {}),
                attrs=d.get("attrs", {}),
                error=d.get("error"),
            )
            recorder._spans.append(span)
        return recorder

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record(self, span: Span) -> None:
        self._spans.append(span)
        if self._path:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(span.to_dict(), ensure_ascii=False) + "\n")

    def __repr__(self) -> str:
        return f"SpanRecorder(count={self.count()}, total={self.total_duration_ms():.1f}ms)"
