"""A serial, in-process job queue for SolidWorks builds."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable


class SerialJobQueue:
    """Run submitted job identifiers one at a time in a daemon thread.

    The queue is intentionally in-memory: it serializes work inside one
    process, while SQLite remains the durable record of jobs and consumption.
    ``stop`` waits for the currently running item by default, so callers do not
    close the durable store while a worker may still write to it.
    """

    def __init__(
        self,
        processor: Callable[[str], None],
        *,
        name: str = "autosolid-build",
    ) -> None:
        self._processor = processor
        self._name = name
        self._items: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._thread: threading.Thread | None = None
        self._active_job: str | None = None
        self._stop_requested = False
        self._stopped = False

    def submit(self, job_id: str) -> bool:
        """Enqueue ``job_id``; repeated or stale identifiers are ignored later."""

        with self._lock:
            if self._stopped:
                return False
            self._ensure_started_locked()
            self._items.put(job_id)
        return True

    def is_active(self, job_id: str) -> bool:
        """Return whether this queue is currently processing ``job_id``."""

        with self._lock:
            return self._active_job == job_id

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Wait until no item is being processed; return whether it is idle."""

        with self._idle:
            return self._idle.wait_for(
                lambda: self._active_job is None,
                timeout=timeout,
            )

    def _ensure_started_locked(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name=self._name,
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            job_id = self._items.get()
            if job_id is None:
                self._items.task_done()
                return
            with self._lock:
                if self._stopped:
                    # Do not start queued work during an ordered shutdown. The
                    # item stays durably ``queued`` in SQLite for an explicit
                    # retry after restart.
                    self._items.task_done()
                    return
                self._active_job = job_id
            try:
                self._processor(job_id)
            except Exception:  # pragma: no cover - the service records failures
                # A processor bug must not kill the serial worker. The job
                # remains in its last durable state for an explicit retry.
                pass
            finally:
                with self._idle:
                    self._active_job = None
                    self._idle.notify_all()
                self._items.task_done()

    def stop(self, timeout: float | None = None) -> None:
        """Stop accepting work and wait for the active item.

        With the default ``timeout=None`` this blocks until the current item
        finishes and the worker exits. A caller that supplies a timeout is
        responsible for not closing shared resources while the thread is still
        alive; the API uses the blocking default.
        """

        with self._lock:
            self._stopped = True
            if not self._stop_requested:
                self._stop_requested = True
                # Wake a worker that is idle in ``Queue.get``. If a job is
                # already active, the worker exits after that job completes.
                self._items.put(None)
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
