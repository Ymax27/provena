# Retention

`RetentionEngine` deletes trail records older than a retention window and
can archive them first. The default floor is 180 days, the EU AI Act
minimum for the logs this engine is meant to keep. A shorter
`retention_days` raises `ValueError`.

## Programmatic use

```python
from provena import ContextTrail
from provena.retention import RetentionEngine

trail = ContextTrail(storage_path="audit.db")
engine = RetentionEngine(trail, retention_days=365)

engine.preview()
# {"would_delete": 12, "retention_days": 365, "provenance": {...}, "freshness": {...}}

result = engine.execute(archive_path="archive.json", dry_run=True)
result = engine.execute(archive_path="archive.json")
```

`execute` writes the expired rows (and their annotations) to `archive_path`
before deleting them. It then logs a `provena:retention` record describing
the purge, so the deletion itself stays on the trail. `dry_run=True` reports
what would be removed and does not write or delete anything.

`preview()` counts expired records and breaks them down by provenance and
freshness status without changing storage.

## CLI

```bash
pip install provena[cli]

provena --db audit.db retain --max-age 365 --dry-run
provena --db audit.db retain --max-age 365 --archive backup.json
```

`--max-age` is `retention_days`. Values below 180 are rejected. `--archive`
is the JSON file passed to `execute(archive_path=...)`.
