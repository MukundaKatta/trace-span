# trace-span

Lightweight span/timing context manager for agent steps — JSONL export, no dependencies.

Zero dependencies. Python 3.10+. MIT.

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

## License

MIT
