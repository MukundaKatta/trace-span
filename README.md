# trace-span

[![CI](https://github.com/MukundaKatta/trace-span/actions/workflows/ci.yml/badge.svg)](https://github.com/MukundaKatta/trace-span/actions/workflows/ci.yml)

Lightweight span/timing context manager for agent steps — JSONL export, no dependencies.

Zero dependencies. Python 3.10+. MIT.

`trace-span` lets you wrap each step of an LLM-agent run (model calls, tool
calls, web searches, retries) in a timed span, attach tags and attributes,
capture errors automatically, and export everything to JSONL for later
analysis. Durations are measured with a monotonic clock, so they stay accurate
even if the system clock is adjusted mid-run.

## Install

```bash
pip install trace-span
```

## Usage

```python
from trace_span import SpanRecorder

recorder = SpanRecorder()

with recorder.span("llm_call", tags={"model": "claude-sonnet-4-5"}) as span:
    response = client.messages.create(...)
    span.set("tokens_out", response.usage.output_tokens)

with recorder.span("web_search") as span:
    result = search(query)
    span.set("result_count", len(result))

print(recorder.total_duration_ms())
```

## Error capture

```python
try:
    with recorder.span("tool_call") as span:
        result = risky_tool()
except Exception:
    pass  # span records the error automatically

errors = recorder.errors()  # spans that failed
```

## Queries

```python
recorder.spans()           # all completed spans
recorder.by_name("llm")    # spans by name
recorder.errors()          # failed spans
recorder.count()           # total span count
recorder.total_duration_ms()
```

## JSONL export

```python
# Live: append to file as spans complete
recorder = SpanRecorder("logs/run.jsonl")

# Save all at end
recorder.save("run.jsonl")

# Load for analysis
rec2 = SpanRecorder.load("run.jsonl")
```

## Manual start/finish (async-friendly)

```python
span = recorder.start("async_op")
# ... await something ...
recorder.finish(span)
recorder.finish(span, error="timed out")
```

## Span object

```python
span.name           # "llm_call"
span.duration_ms    # 342.1 (None if still open)
span.ok             # True if finished without error
span.is_open        # True while inside context manager
span.tags           # {"model": "claude"}
span.attrs          # {"tokens_out": 150}
span.error          # None or error message
span.to_dict()      # serializable dict
```

## API reference

### `SpanRecorder(path=None)`

Collects spans from a run. If `path` is given, each completed span is appended
to that JSONL file as it finishes (the parent directory must already exist).

| Method | Description |
| --- | --- |
| `span(name, *, tags=None)` | Context manager that yields a `Span`; records it on exit (even if an exception propagates). |
| `start(name, *, tags=None)` | Start a span manually (async/callback friendly). Returns the open `Span`. |
| `finish(span, *, error=None)` | End a manually started span and record it. Raises `SpanError` if already finished. |
| `spans()` | All completed spans, in order (returns a copy). |
| `by_name(name)` | Completed spans matching `name`. |
| `errors()` | Completed spans that ended with an error. |
| `count()` | Number of recorded spans. |
| `total_duration_ms()` | Sum of all span durations, in milliseconds. |
| `clear()` | Drop all recorded spans (in memory). |
| `save(path)` | Write all spans to a JSONL file. |
| `SpanRecorder.load(path)` | Classmethod; rebuild a recorder from a JSONL file. |

### `Span`

Created by the recorder; you usually only read from it or call `set()`.

| Member | Description |
| --- | --- |
| `name` | Span name. |
| `started_at` / `ended_at` | Unix wall-clock timestamps (`ended_at` is `None` while open). |
| `duration_ms` | Duration in ms, or `None` if still open. Measured with a monotonic clock for live spans. |
| `ok` | `True` if finished without an error. |
| `is_open` | `True` while the span is unfinished. |
| `tags` / `attrs` | Metadata set at start / during the span. |
| `error` | Error message, or `None`. |
| `set(key, value)` | Set an attribute; returns `self` for chaining. |
| `to_dict()` | JSON-serializable dict. |

### `SpanError`

Raised on invalid span operations (e.g. finishing a span twice).

## Development

The library has no runtime or test dependencies. Run the test suite with the
standard library only:

```bash
python3 -m unittest discover -s tests
```

CI runs the same suite across Python 3.10–3.13 on every push and pull request.

## License

MIT
