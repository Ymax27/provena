# Multi-Agent Aggregation

Real-world AI pipelines rarely use a single agent. A planner decomposes a task,
an executor runs tools, a reviewer checks the output. Each agent makes
autonomous decisions, but your governance requirements span the whole pipeline:

- Which agent retrieved which data?
- How was context passed from one agent to another?
- Did any agent introduce stale or unsourced information?
- Is the entire pipeline's chain of custody cryptographically intact?

Provena's `TrailAggregator` answers these questions by stitching together the
independent audit trails of every agent into a unified governance view.

## Installation

`TrailAggregator` is part of Provena's core package -- no extra dependencies
required:

```bash
pip install provena
```

## Core Concepts

Each agent owns its own `ContextTrail`, which maintains an independent
SHA-256 hash-chained log. The `TrailAggregator` does not merge or share trails;
it holds references to them and provides cross-trail operations:

| Concept | Description |
|---|---|
| **Trail** | An independent `ContextTrail` owned by one agent |
| **Label** | A unique string identifying a trail in the aggregator |
| **Handoff** | A recorded link from one trail's record to another's |
| **Run ID** | A string grouping a set of handoffs into a single workflow run |
| **Evidence Gap** | A detected governance problem: broken chain, stale context, missing provenance, or unlinked handoff |

## Quick Start

```python
from provena import ContextTrail, ProvenanceMetadata
from provena.aggregator import TrailAggregator
from datetime import datetime, timezone

# Each agent has its own trail
planner = ContextTrail(backend="memory")
executor = ContextTrail(backend="memory")

# Collect them into one aggregator
agg = TrailAggregator()
agg.add("planner", planner)
agg.add("executor", executor)

# Log to each trail independently
planner.log("Research task: find k8s deployment best practices", source="retriever")
r_exec = executor.log("kubectl apply -f deployment.yaml", source="tool", source_name="kubectl")

# Check the pipeline summary in one call
print(agg.summary()["total"])          # 2
print(agg.summary()["trail_count"])    # 2

agg.close()  # Closes all registered trails
```

## Registering and Managing Trails

### `add(label, trail)`

Register a named trail. Each label must be unique:

```python
agg = TrailAggregator()
agg.add("planner", planner_trail)
agg.add("executor", executor_trail)
agg.add("reviewer", reviewer_trail)

print(agg.labels)       # ("planner", "executor", "reviewer")
print(agg.trail_count)  # 3
```

!!! warning "Duplicate labels raise an error"
    Calling `agg.add("planner", ...)` a second time raises `ValueError`. Each
    label must be unique within the aggregator.

### `get_trail(label)`

Retrieve a registered trail by label. Returns `None` if the label is unknown:

```python
trail = agg.get_trail("planner")  # ContextTrail or None
```

### `remove(label)`

Deregister a trail by label. The trail is not closed; you remain responsible
for its lifecycle:

```python
agg.remove("planner")
print(agg.labels)  # ("executor", "reviewer")
```

## Summary

`agg.summary()` aggregates provenance, freshness, and source statistics across
all registered trails:

```python
s = agg.summary()

print(s["total"])        # Total records across all trails
print(s["trail_count"])  # Number of registered trails
print(s["handoffs"])     # Number of recorded handoff edges
print(s["all_signed"])   # True only if every trail uses HMAC signing
print(s["provenance"])   # {"VALID": 4, "MISSING": 2, ...}
print(s["freshness"])    # {"FRESH": 5, "STALE": 1, ...}
print(s["sources"])      # {"retriever": 3, "tool": 2, "agent": 1}
```

The `per_trail` key holds a per-label copy of each trail's own `summary()`:

```python
print(s["per_trail"]["planner"]["total"])    # Records in planner's trail
print(s["per_trail"]["executor"]["total"])   # Records in executor's trail
```

## Querying Across Trails

`agg.query()` returns records from all trails sorted by timestamp. Every record
gains a `_trail` field indicating its origin:

```python
records = agg.query()
for r in records:
    print(f"[{r['_trail']}] {r['source']} | {r['content_hash'][:12]}")
```

### Filtering

All filters are optional and can be combined:

```python
# Records from a specific agent only
records = agg.query(trail_label="executor")

# Records with a specific source type
records = agg.query(source="tool")

# Records missing provenance metadata
records = agg.query(provenance_status="MISSING")

# Records with stale freshness status
records = agg.query(freshness_status="STALE")

# Time-range filter (datetime objects with timezone)
from datetime import datetime, timezone
cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
records = agg.query(start=cutoff)

# Limit total records returned (default 100)
records = agg.query(limit=25)
```

### Run ID Filtering

Once handoffs are recorded (see below), you can retrieve only the records
involved in a specific workflow run:

```python
records = agg.query(run_id="deploy-001")
# Returns only records linked by handoffs tagged "deploy-001"
```

## Recording Handoffs

A **handoff** links a specific record in one agent's trail to a specific record
in another's. It answers the question: "which output from agent A was given as
input to agent B?"

### `record_handoff(from_trail, from_record_id, to_trail, to_record_id, run_id="")`

```python
r_planner = planner.log("Use rolling update strategy", source="tool", source_name="planner_tool")
r_executor = executor.log("kubectl apply -f deployment.yaml", source="tool", source_name="kubectl")

edge = agg.record_handoff(
    from_trail="planner",
    from_record_id=r_planner.id,   # (1)!
    to_trail="executor",
    to_record_id=r_executor.id,
    run_id="deploy-001",           # (2)!
)
print(edge)  # HandoffEdge(planner#2 -> executor#1)
```

1. Use the record's `.id` attribute -- the persisted database ID. In buffered
   mode, `trail.log()` returns `id=-1` (provisional) until the buffer is
   flushed. Call `trail.flush()` first, then use `trail.last_record["id"]`.
2. The `run_id` groups related handoffs into one workflow run.

The returned `HandoffEdge` is a frozen dataclass with fields:
`from_trail`, `from_record_id`, `to_trail`, `to_record_id`, `run_id`.

### Handoff validation rules

Provena validates handoff arguments strictly:

| Rule | Raises |
|---|---|
| Duplicate label already registered | `ValueError: already registered` |
| `from_record_id < 1` or `to_record_id < 1` | `ValueError: must be >= 1` |
| IDs are not strict `int` (e.g. `True`, `1.5`, `nan`) | `TypeError: strict integers` |
| Same trail and same record ID (`from` == `to`) | `ValueError: Self-referential` |
| More than 100,000 handoffs recorded | `RuntimeError: capacity exceeded` |

!!! warning "Buffered mode and provisional IDs"
    In buffered mode, `trail.log()` returns `id=-1` (a placeholder) until the
    write buffer is flushed to storage. Passing `-1` to `record_handoff` raises
    `ValueError`. Always call `trail.flush()` before reading record IDs for
    handoff registration.

    ```python
    planner = ContextTrail(backend="memory", buffered=True)
    rec = planner.log("data", source="retriever")
    # rec.id == -1 here -- do NOT pass to record_handoff

    planner.flush()
    real_id = planner.last_record["id"]
    agg.record_handoff("planner", real_id, "executor", 1)
    ```

### Querying handoffs

```python
# All handoffs
print(len(agg.handoffs))  # tuple of HandoffEdge

# Handoffs for a specific run
run_edges = agg.handoffs_for_run("deploy-001")
print(len(run_edges))  # 2
```

## Verifying Chain Integrity

`agg.verify_chain()` verifies the hash chain of **every** registered trail and
returns an `AggregateVerdict`:

```python
verdict = agg.verify_chain()

print(verdict.all_intact)        # True if all chains are intact
print(verdict.total_records)     # Sum of records across all trails

for tv in verdict.trail_verdicts:
    print(f"{tv.label}: intact={tv.verdict.intact}")
    # planner: intact=True
    # executor: intact=True
    # reviewer: intact=True
```

`AggregateVerdict` fields:

| Field | Type | Description |
|---|---|---|
| `all_intact` | `bool` | `True` only if every per-trail chain is intact |
| `trail_verdicts` | `tuple[TrailVerdict, ...]` | Per-label `ChainVerdict` wrappers |
| `total_records` | `int` | Total records verified across all trails |

Each `TrailVerdict` wraps the label and the `ChainVerdict` returned by
`trail.verify_chain()` for that trail. See the
[Chain Verification guide](verification.md) for details on `ChainVerdict`.

## Timeline: Chronological Cross-Agent View

`agg.timeline()` merges records from all trails into a single list sorted by
timestamp, with handoff edges interleaved as synthetic entries:

```python
timeline = agg.timeline()

for entry in timeline:
    if entry.get("_type") == "handoff":
        print(f"  HANDOFF: {entry['from_trail']} -> {entry['to_trail']} (run={entry['run_id']})")
    else:
        print(f"  [{entry['_trail']}] {entry['source']}: {entry['content_hash'][:12]}")
```

### Timeline record fields

**Regular records** (from a trail) include all `ContextTrail.query()` fields
plus `_trail` (the label of the trail they belong to).

**Handoff entries** are synthetic dicts with:

| Field | Value |
|---|---|
| `_type` | `"handoff"` |
| `_trail` | `"<from_trail> -> <to_trail>"` (display string) |
| `from_trail` | Source trail label |
| `from_record_id` | Record ID in the source trail |
| `to_trail` | Destination trail label |
| `to_record_id` | Record ID in the destination trail |
| `run_id` | The run identifier (empty string if not set) |
| `timestamp` | Timestamp of the source record (when available) |

!!! info "Timeline ordering"
    Records are sorted by their `timestamp` string. Handoff entries inherit the
    timestamp of the source record they are linked to. If the source record is
    not found, the handoff entry is appended without a timestamp (which sorts
    it last).

### Filtering the timeline

```python
from datetime import datetime, timezone

timeline = agg.timeline(
    start=datetime(2026, 1, 1, tzinfo=timezone.utc),
    end=datetime(2026, 12, 31, tzinfo=timezone.utc),
    limit=500,                           # default 200
)
```

## Detecting Evidence Gaps

`agg.detect_gaps()` scans all registered trails and all recorded handoffs and
returns a list of `EvidenceGap` instances:

```python
gaps = agg.detect_gaps()

for gap in gaps:
    print(f"[{gap.gap_type}] trail={gap.trail} record={gap.record_id}: {gap.details}")
```

`EvidenceGap` fields:

| Field | Type | Description |
|---|---|---|
| `trail` | `str` | Label of the trail where the gap was found |
| `gap_type` | `str` | One of: `broken_chain`, `stale_context`, `missing_provenance`, `unlinked_handoff` |
| `details` | `str` | Human-readable explanation |
| `record_id` | `int \| None` | ID of the affected record (when applicable) |

### Gap types

| `gap_type` | Triggered when |
|---|---|
| `broken_chain` | A trail's `verify_chain()` returns `intact=False` |
| `stale_context` | A record has `freshness_status="STALE"` |
| `missing_provenance` | A record has `provenance_status="MISSING"` |
| `unlinked_handoff` | A handoff references a trail label or record ID that does not exist |

!!! tip "Stale and missing provenance scanning is exhaustive"
    `detect_gaps()` pages through all stale and missing-provenance records in
    batches of 1,000 internally. It will report every gap, even in trails with
    thousands of records.

## Complete Example: Planner → Executor → Reviewer

This example reproduces the pattern tested in `TestMultiAgentWorkflow`:

```python
from datetime import datetime, timezone
from provena import ContextTrail, ProvenanceMetadata
from provena.aggregator import TrailAggregator

# Use the context manager so all trails are closed automatically
with TrailAggregator() as agg:
    # --- Create one trail per agent ---
    planner  = ContextTrail(backend="memory")
    executor = ContextTrail(backend="memory")
    reviewer = ContextTrail(backend="memory")

    agg.add("planner",  planner)
    agg.add("executor", executor)
    agg.add("reviewer", reviewer)

    # --- Planner gathers context with provenance ---
    prov = ProvenanceMetadata(
        source_url="https://docs.k8s.io",
        created_at=datetime.now(timezone.utc),
    )
    planner.log(
        "Deploy to k8s with 3 replicas",
        source="retriever",
        provenance=prov,
    )
    r_plan = planner.log(  # (1)!
        "Use rolling update strategy",
        source="tool",
        source_name="planner_tool",
    )

    # --- Executor acts on the planner's output ---
    r_exec = executor.log(
        "kubectl apply -f deployment.yaml",
        source="tool",
        source_name="kubectl",
    )
    # Record the handoff: planner record → executor record
    agg.record_handoff("planner", r_plan.id, "executor", r_exec.id, "deploy-001")

    # --- Reviewer validates the executor's output ---
    r_review = reviewer.log(
        "Deployment verified: 3/3 pods running",
        source="agent",
        source_name="verifier",
    )
    # Record the handoff: executor record → reviewer record
    agg.record_handoff("executor", r_exec.id, "reviewer", r_review.id, "deploy-001")

    # --- Aggregate governance summary ---
    s = agg.summary()
    print(f"Total records:  {s['total']}")        # 4
    print(f"Trails:         {s['trail_count']}")  # 3
    print(f"Handoffs:       {s['handoffs']}")     # 2
    print(f"Provenance:     {s['provenance']}")   # {"VALID": 1, "MISSING": 3}
    print(f"Sources:        {s['sources']}")      # {"retriever": 1, "tool": 2, "agent": 1}

    # --- Verify every chain ---
    verdict = agg.verify_chain()
    assert verdict.all_intact
    print(f"All chains intact: {verdict.total_records} records verified")

    # --- Query records involved in deploy-001 ---
    deploy_records = agg.query(run_id="deploy-001")
    print(f"Deploy-001 records: {len(deploy_records)}")  # >= 2

    # --- Cross-agent timeline ---
    timeline = agg.timeline()
    for entry in timeline:
        if entry.get("_type") == "handoff":
            print(f"  -> HANDOFF {entry['from_trail']} to {entry['to_trail']}")
        else:
            print(f"  [{entry['_trail']}] {entry['source']}")

    # --- Evidence gap report ---
    gaps = agg.detect_gaps()
    for gap in gaps:
        print(f"  GAP [{gap.gap_type}] {gap.trail}: {gap.details}")
    # GAP [missing_provenance] planner: No provenance metadata on 'planner_tool'
    # GAP [missing_provenance] executor: No provenance metadata on 'kubectl'
    # GAP [missing_provenance] reviewer: No provenance metadata on 'verifier'

# All three trails are closed automatically here
```

1. `trail.log()` returns a `TrailRecord` with the persisted `id` field. Use
   this ID immediately after logging — do not cache it past a `close()` call.

## Lifecycle and Context Manager

`TrailAggregator` supports the context manager protocol. The `__exit__` method
calls `agg.close()`, which closes every registered trail:

```python
with TrailAggregator() as agg:
    # Register and use trails
    ...
# All trails are closed here, even if an exception occurred
```

`agg.close()` continues even if one trail's `close()` raises. All trails
get a chance to shut down. If any trail failed to close, the first exception is
re-raised after all trails have been processed; additional exceptions are logged
as warnings.

## Limitations

| Limitation | Detail |
|---|---|
| **No cross-trail hash linking** | Each trail maintains its own hash chain. The aggregator does not link chains across agents — if you need a single global chain, use one shared `ContextTrail` instead. |
| **Handoff capacity** | A maximum of 100,000 handoff edges can be recorded per aggregator instance. Exceeds that raises `RuntimeError`. |
| **In-memory only** | The aggregator's handoff list is held in memory and is not persisted to storage. Restarting the process loses recorded handoffs. |
| **Run ID filtering operates on handoffs** | `query(run_id=...)` only returns records linked by handoffs tagged with that `run_id`. Records in the same workflow that were not connected via a recorded handoff will not appear. |
| **No automatic gap remediation** | `detect_gaps()` identifies gaps but does not fix them. You must add provenance, re-log content, or update your workflow to resolve gaps. |

## See Also

- [Tracking Context](tracking.md) — how to log records with `trail.log()` and `@trail.track()`
- [Chain Verification](verification.md) — per-trail chain integrity details
- [Provenance Validation](provenance.md) — how `VALID`, `INCOMPLETE`, and `MISSING` are assigned
- [Freshness Checking](freshness.md) — how `FRESH`, `STALE`, and `UNKNOWN` are determined
