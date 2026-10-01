"""Concurrent logging coverage for ContextTrail and WriteBuffer."""

from __future__ import annotations

import threading

from provena.trail import ContextTrail


def _log_many(
    trail: ContextTrail, thread_count: int, per_thread: int
) -> list[BaseException]:
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def worker(worker_id: int) -> None:
        try:
            for i in range(per_thread):
                record = trail.log(
                    f"worker-{worker_id}-{i}",
                    source="retriever",
                    source_name=f"w{worker_id}",
                )
                if record is None:
                    raise AssertionError(f"log returned None for worker {worker_id}")
        except BaseException as exc:
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


class TestConcurrentTrailWrites:
    def test_memory_trail_concurrent_logs_keep_chain(self):
        trail = ContextTrail(backend="memory")
        try:
            errors = _log_many(trail, thread_count=8, per_thread=25)
            assert errors == []
            verdict = trail.verify_chain()
            assert verdict.intact
            assert verdict.total_records == 200
            ids = [row["id"] for row in trail._backend.all_records()]
            assert ids == list(range(1, 201))
        finally:
            trail.close()

    def test_buffered_trail_concurrent_logs_keep_chain(self):
        trail = ContextTrail(
            backend="memory",
            buffered=True,
            buffer_size=40,
            flush_interval=3600,
        )
        try:
            errors = _log_many(trail, thread_count=8, per_thread=40)
            assert errors == []
            trail.flush()
            assert trail._buffer is not None
            assert trail._buffer.pending == 0
            verdict = trail.verify_chain()
            assert verdict.intact
            assert verdict.total_records == 320
            ids = [row["id"] for row in trail._backend.all_records()]
            assert ids == list(range(1, 321))
        finally:
            trail.close()
