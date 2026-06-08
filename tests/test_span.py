"""Tests for trace-span.

These tests use only the Python standard library (``unittest``) so they run
without any third-party dependencies::

    python3 -m unittest discover -s tests
"""

import os
import sys
import json
import time
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trace_span import Span, SpanRecorder, SpanError


class TestSpanBasics(unittest.TestCase):
    def test_span_open(self):
        s = Span(name="test", started_at=time.time())
        self.assertTrue(s.is_open)
        self.assertIsNone(s.duration_ms)
        self.assertFalse(s.ok)

    def test_span_duration_ms_from_timestamps(self):
        t0 = time.time()
        s = Span(name="test", started_at=t0, ended_at=t0 + 0.5)
        self.assertAlmostEqual(s.duration_ms, 500.0, delta=1.0)

    def test_span_ok_true(self):
        t0 = time.time()
        s = Span(name="test", started_at=t0, ended_at=t0 + 0.1)
        self.assertTrue(s.ok)

    def test_span_ok_false_with_error(self):
        t0 = time.time()
        s = Span(name="test", started_at=t0, ended_at=t0 + 0.1, error="oops")
        self.assertFalse(s.ok)

    def test_span_set(self):
        s = Span(name="test", started_at=time.time())
        s.set("tokens", 100)
        self.assertEqual(s.attrs["tokens"], 100)

    def test_span_set_returns_self(self):
        s = Span(name="test", started_at=time.time())
        self.assertIs(s.set("k", "v"), s)

    def test_span_set_chaining(self):
        s = Span(name="test", started_at=time.time())
        s.set("a", 1).set("b", 2)
        self.assertEqual(s.attrs, {"a": 1, "b": 2})

    def test_span_to_dict(self):
        t0 = time.time()
        s = Span(
            name="llm_call",
            started_at=t0,
            ended_at=t0 + 0.2,
            tags={"model": "claude"},
        )
        d = s.to_dict()
        self.assertEqual(d["name"], "llm_call")
        self.assertEqual(d["tags"], {"model": "claude"})
        self.assertAlmostEqual(d["duration_ms"], 200.0, delta=1.0)
        self.assertTrue(d["ok"])

    def test_to_dict_is_json_serializable(self):
        t0 = time.time()
        s = Span(name="x", started_at=t0, ended_at=t0 + 0.1, tags={"k": 1})
        # Must not raise.
        json.dumps(s.to_dict())

    def test_to_dict_copies_mutable_fields(self):
        s = Span(name="x", started_at=time.time(), tags={"k": "v"})
        d = s.to_dict()
        d["tags"]["k"] = "mutated"
        self.assertEqual(s.tags["k"], "v")

    def test_span_repr(self):
        t0 = time.time()
        s = Span(name="test", started_at=t0, ended_at=t0 + 0.1)
        r = repr(s)
        self.assertIn("test", r)
        self.assertIn("ms", r)

    def test_open_span_repr_says_open(self):
        s = Span(name="test", started_at=time.time())
        self.assertIn("open", repr(s))


class TestContextManager(unittest.TestCase):
    def test_records(self):
        rec = SpanRecorder()
        with rec.span("llm_call"):
            pass
        self.assertEqual(rec.count(), 1)

    def test_yields_span(self):
        rec = SpanRecorder()
        with rec.span("test") as s:
            self.assertIsInstance(s, Span)
            self.assertEqual(s.name, "test")

    def test_sets_attrs(self):
        rec = SpanRecorder()
        with rec.span("test") as s:
            s.set("x", 42)
        self.assertEqual(rec.spans()[0].attrs["x"], 42)

    def test_tags(self):
        rec = SpanRecorder()
        with rec.span("llm", tags={"model": "claude"}):
            pass
        self.assertEqual(rec.spans()[0].tags["model"], "claude")

    def test_tags_are_copied(self):
        rec = SpanRecorder()
        tags = {"model": "claude"}
        with rec.span("llm", tags=tags):
            pass
        tags["model"] = "changed"
        self.assertEqual(rec.spans()[0].tags["model"], "claude")

    def test_duration_positive(self):
        rec = SpanRecorder()
        with rec.span("sleep"):
            time.sleep(0.01)
        self.assertGreater(rec.spans()[0].duration_ms, 0)

    def test_duration_uses_monotonic_clock(self):
        # Even though we can't move the wall clock here, the recorded span
        # should carry monotonic readings so its duration is independent of
        # started_at / ended_at.
        rec = SpanRecorder()
        with rec.span("op") as s:
            time.sleep(0.01)
        self.assertIsNotNone(s._perf_start)
        self.assertIsNotNone(s._perf_end)
        # Corrupt the wall-clock timestamps; duration must stay sane.
        s.started_at = 10_000_000.0
        s.ended_at = 0.0  # would be negative if duration used timestamps
        self.assertGreater(s.duration_ms, 0)

    def test_not_open_after(self):
        rec = SpanRecorder()
        with rec.span("test") as s:
            pass
        self.assertFalse(s.is_open)

    def test_exception_records_error(self):
        rec = SpanRecorder()
        try:
            with rec.span("failing"):
                raise ValueError("something broke")
        except ValueError:
            pass
        s = rec.spans()[0]
        self.assertEqual(s.error, "something broke")
        self.assertFalse(s.ok)

    def test_does_not_suppress(self):
        rec = SpanRecorder()
        with self.assertRaises(RuntimeError):
            with rec.span("test"):
                raise RuntimeError("not suppressed")
        # Span is still recorded despite the exception.
        self.assertEqual(rec.count(), 1)


class TestManualStartFinish(unittest.TestCase):
    def test_start_finish(self):
        rec = SpanRecorder()
        s = rec.start("manual")
        self.assertTrue(s.is_open)
        rec.finish(s)
        self.assertFalse(s.is_open)
        self.assertEqual(rec.count(), 1)

    def test_finish_with_error(self):
        rec = SpanRecorder()
        s = rec.start("failing")
        rec.finish(s, error="timed out")
        self.assertEqual(rec.spans()[0].error, "timed out")
        self.assertFalse(rec.spans()[0].ok)

    def test_finish_twice_raises(self):
        rec = SpanRecorder()
        s = rec.start("test")
        rec.finish(s)
        with self.assertRaises(SpanError):
            rec.finish(s)

    def test_manual_duration_positive(self):
        rec = SpanRecorder()
        s = rec.start("op")
        time.sleep(0.01)
        rec.finish(s)
        self.assertGreater(s.duration_ms, 0)


class TestQueries(unittest.TestCase):
    def test_spans_returns_list_copy(self):
        rec = SpanRecorder()
        with rec.span("a"):
            pass
        with rec.span("b"):
            pass
        out = rec.spans()
        self.assertEqual(len(out), 2)
        out.clear()  # mutating the returned list must not affect the recorder
        self.assertEqual(rec.count(), 2)

    def test_by_name(self):
        rec = SpanRecorder()
        for name in ("search", "llm", "search"):
            with rec.span(name):
                pass
        self.assertEqual(len(rec.by_name("search")), 2)

    def test_by_name_no_match(self):
        rec = SpanRecorder()
        with rec.span("a"):
            pass
        self.assertEqual(rec.by_name("missing"), [])

    def test_errors_query(self):
        rec = SpanRecorder()
        try:
            with rec.span("ok"):
                pass
            with rec.span("bad"):
                raise ValueError("oops")
        except ValueError:
            pass
        errs = rec.errors()
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0].name, "bad")

    def test_total_duration_ms(self):
        rec = SpanRecorder()
        for _ in range(3):
            with rec.span("op"):
                time.sleep(0.005)
        total = rec.total_duration_ms()
        individual = sum(s.duration_ms for s in rec.spans())
        self.assertAlmostEqual(total, individual, delta=0.001)
        self.assertGreater(total, 0)

    def test_total_duration_empty(self):
        rec = SpanRecorder()
        self.assertEqual(rec.total_duration_ms(), 0.0)

    def test_count(self):
        rec = SpanRecorder()
        self.assertEqual(rec.count(), 0)
        with rec.span("a"):
            pass
        self.assertEqual(rec.count(), 1)

    def test_clear(self):
        rec = SpanRecorder()
        with rec.span("a"):
            pass
        rec.clear()
        self.assertEqual(rec.count(), 0)


class TestPersistence(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)

    def tearDown(self):
        Path(self.path).unlink(missing_ok=True)

    def test_save_load_roundtrip(self):
        rec = SpanRecorder()
        with rec.span("llm_call", tags={"model": "claude"}) as s:
            s.set("tokens", 50)
        rec.save(self.path)
        loaded = SpanRecorder.load(self.path)
        self.assertEqual(loaded.count(), 1)
        self.assertEqual(loaded.spans()[0].name, "llm_call")
        self.assertEqual(loaded.spans()[0].tags, {"model": "claude"})
        self.assertEqual(loaded.spans()[0].attrs, {"tokens": 50})

    def test_loaded_span_has_duration(self):
        rec = SpanRecorder()
        with rec.span("op"):
            time.sleep(0.01)
        rec.save(self.path)
        loaded = SpanRecorder.load(self.path)
        # Duration is reconstructed from wall-clock timestamps on load.
        self.assertIsNotNone(loaded.spans()[0].duration_ms)
        self.assertGreaterEqual(loaded.spans()[0].duration_ms, 0)

    def test_jsonl_live_logging(self):
        rec = SpanRecorder(self.path)
        with rec.span("step1"):
            pass
        with rec.span("step2"):
            pass
        lines = Path(self.path).read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        names = [json.loads(line)["name"] for line in lines]
        self.assertEqual(names, ["step1", "step2"])

    def test_load_skips_blank_lines(self):
        Path(self.path).write_text(
            json.dumps({"name": "a", "started_at": 1.0, "ended_at": 2.0})
            + "\n\n   \n"
            + json.dumps({"name": "b", "started_at": 3.0, "ended_at": 4.0})
            + "\n"
        )
        loaded = SpanRecorder.load(self.path)
        self.assertEqual(loaded.count(), 2)
        self.assertEqual([s.name for s in loaded.spans()], ["a", "b"])

    def test_save_then_count_unchanged(self):
        rec = SpanRecorder()
        with rec.span("a"):
            pass
        rec.save(self.path)
        self.assertEqual(rec.count(), 1)


class TestRepr(unittest.TestCase):
    def test_recorder_repr(self):
        rec = SpanRecorder()
        self.assertIn("SpanRecorder", repr(rec))

    def test_recorder_repr_with_spans(self):
        rec = SpanRecorder()
        with rec.span("a"):
            pass
        r = repr(rec)
        self.assertIn("count=1", r)


if __name__ == "__main__":
    unittest.main()
