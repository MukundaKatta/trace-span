"""Tests for trace-span."""

import sys
import os
import json
import time
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import pytest
from trace_span import Span, SpanRecorder, SpanError


# ---------------------------------------------------------------------------
# Span basics
# ---------------------------------------------------------------------------

def test_span_open():
    s = Span(name="test", started_at=time.time())
    assert s.is_open is True
    assert s.duration_ms is None
    assert s.ok is False

def test_span_duration_ms():
    t0 = time.time()
    s = Span(name="test", started_at=t0, ended_at=t0 + 0.5)
    assert s.duration_ms == pytest.approx(500.0, abs=1.0)

def test_span_ok_true():
    t0 = time.time()
    s = Span(name="test", started_at=t0, ended_at=t0 + 0.1)
    assert s.ok is True

def test_span_ok_false_with_error():
    t0 = time.time()
    s = Span(name="test", started_at=t0, ended_at=t0 + 0.1, error="oops")
    assert s.ok is False

def test_span_set():
    s = Span(name="test", started_at=time.time())
    s.set("tokens", 100)
    assert s.attrs["tokens"] == 100

def test_span_set_returns_self():
    s = Span(name="test", started_at=time.time())
    assert s.set("k", "v") is s

def test_span_to_dict():
    t0 = time.time()
    s = Span(name="llm_call", started_at=t0, ended_at=t0 + 0.2, tags={"model": "claude"})
    d = s.to_dict()
    assert d["name"] == "llm_call"
    assert d["tags"] == {"model": "claude"}
    assert d["duration_ms"] == pytest.approx(200.0, abs=1.0)
    assert d["ok"] is True

def test_span_repr():
    t0 = time.time()
    s = Span(name="test", started_at=t0, ended_at=t0 + 0.1)
    r = repr(s)
    assert "test" in r
    assert "ms" in r


# ---------------------------------------------------------------------------
# SpanRecorder context manager
# ---------------------------------------------------------------------------

def test_context_manager_records():
    rec = SpanRecorder()
    with rec.span("llm_call"):
        pass
    assert rec.count() == 1

def test_context_manager_yields_span():
    rec = SpanRecorder()
    with rec.span("test") as s:
        assert isinstance(s, Span)
        assert s.name == "test"

def test_context_manager_sets_attrs():
    rec = SpanRecorder()
    with rec.span("test") as s:
        s.set("x", 42)
    assert rec.spans()[0].attrs["x"] == 42

def test_context_manager_tags():
    rec = SpanRecorder()
    with rec.span("llm", tags={"model": "claude"}):
        pass
    assert rec.spans()[0].tags["model"] == "claude"

def test_context_manager_duration_positive():
    rec = SpanRecorder()
    with rec.span("sleep"):
        time.sleep(0.01)
    assert rec.spans()[0].duration_ms > 0

def test_context_manager_not_open_after():
    rec = SpanRecorder()
    with rec.span("test") as s:
        pass
    assert s.is_open is False

def test_context_manager_exception_records_error():
    rec = SpanRecorder()
    try:
        with rec.span("failing"):
            raise ValueError("something broke")
    except ValueError:
        pass
    s = rec.spans()[0]
    assert s.error == "something broke"
    assert s.ok is False

def test_context_manager_does_not_suppress():
    rec = SpanRecorder()
    with pytest.raises(RuntimeError):
        with rec.span("test"):
            raise RuntimeError("not suppressed")


# ---------------------------------------------------------------------------
# SpanRecorder — manual start/finish
# ---------------------------------------------------------------------------

def test_manual_start_finish():
    rec = SpanRecorder()
    s = rec.start("manual")
    assert s.is_open is True
    rec.finish(s)
    assert s.is_open is False
    assert rec.count() == 1

def test_manual_finish_with_error():
    rec = SpanRecorder()
    s = rec.start("failing")
    rec.finish(s, error="timed out")
    assert rec.spans()[0].error == "timed out"

def test_manual_finish_twice_raises():
    rec = SpanRecorder()
    s = rec.start("test")
    rec.finish(s)
    with pytest.raises(SpanError):
        rec.finish(s)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def test_spans_returns_list():
    rec = SpanRecorder()
    with rec.span("a"):
        pass
    with rec.span("b"):
        pass
    assert len(rec.spans()) == 2

def test_by_name():
    rec = SpanRecorder()
    with rec.span("search"):
        pass
    with rec.span("llm"):
        pass
    with rec.span("search"):
        pass
    found = rec.by_name("search")
    assert len(found) == 2

def test_errors_query():
    rec = SpanRecorder()
    try:
        with rec.span("ok"):
            pass
        with rec.span("bad"):
            raise ValueError("oops")
    except ValueError:
        pass
    assert len(rec.errors()) == 1
    assert rec.errors()[0].name == "bad"

def test_total_duration_ms():
    rec = SpanRecorder()
    s1 = rec.start("a")
    s1.ended_at = s1.started_at + 0.1
    rec.finish.__func__  # just check it exists
    # Manual: inject a finished span
    s1.ended_at = s1.started_at + 0.1
    rec._record(s1)
    assert rec.total_duration_ms() == pytest.approx(100.0, abs=5.0)

def test_count():
    rec = SpanRecorder()
    assert rec.count() == 0
    with rec.span("a"):
        pass
    assert rec.count() == 1

def test_clear():
    rec = SpanRecorder()
    with rec.span("a"):
        pass
    rec.clear()
    assert rec.count() == 0


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def test_save_load_roundtrip():
    rec = SpanRecorder()
    with rec.span("llm_call", tags={"model": "claude"}) as s:
        s.set("tokens", 50)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        rec.save(path)
        loaded = SpanRecorder.load(path)
        assert loaded.count() == 1
        assert loaded.spans()[0].name == "llm_call"
        assert loaded.spans()[0].tags == {"model": "claude"}
        assert loaded.spans()[0].attrs == {"tokens": 50}
    finally:
        Path(path).unlink(missing_ok=True)

def test_jsonl_live_logging():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        path = f.name
    try:
        rec = SpanRecorder(path)
        with rec.span("step1"):
            pass
        with rec.span("step2"):
            pass
        lines = Path(path).read_text().strip().splitlines()
        assert len(lines) == 2
        names = [json.loads(l)["name"] for l in lines]
        assert names == ["step1", "step2"]
    finally:
        Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------

def test_recorder_repr():
    rec = SpanRecorder()
    r = repr(rec)
    assert "SpanRecorder" in r
