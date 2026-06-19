"""Background processing jobs for the web app.

Processing is model-heavy and memory-bound, so all jobs share a single worker thread (one job
runs at a time across the whole app). Progress events from ``batch.run_folder`` are pushed onto a
thread-safe queue that the progress WebSocket drains.
"""

from __future__ import annotations

import queue
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from document_parser import batch

# One global worker → at most one processing job at a time (the models are heavy).
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="docparse-job")
_jobs: dict[str, "Job"] = {}


@dataclass
class Job:
    id: str
    class_id: str
    queue: queue.Queue = field(default_factory=queue.Queue)
    status: str = "queued"  # queued | running | done | error
    error: str | None = None


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def start_processing(
    class_id: str, class_dir: Path, engine: str | None, force: bool
) -> Job:
    """Queue a batch run for one class folder; returns the Job (poll its queue for events)."""
    job = Job(id=uuid.uuid4().hex[:12], class_id=class_id)
    _jobs[job.id] = job

    def run() -> None:
        job.status = "running"
        try:
            batch.run_folder(
                class_dir, engine_override=engine, force=force, progress=job.queue.put
            )
        except Exception as e:  # surface to the UI rather than dying silently
            job.status = "error"
            job.error = str(e)
            job.queue.put({"type": "error", "message": str(e)})
        else:
            job.status = "done"
        finally:
            job.queue.put({"type": "job_done", "status": job.status, "error": job.error})

    _executor.submit(run)
    return job
