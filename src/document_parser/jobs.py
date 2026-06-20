"""Background processing jobs for the web app.

Processing is model-heavy and memory-bound, so all jobs share a single worker thread (one job
runs at a time across the whole app). Progress events from ``batch.run_folder`` are appended to a
per-job ``events`` history; the progress WebSocket replays that history on (re)connect and then
streams new events, so a client that navigates away and comes back sees the full live log of an
in-flight job (the job itself keeps running regardless of any connected socket).
"""

from __future__ import annotations

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
    # Append-only event log (doc_start/page/doc_done/.../job_done). Readers track their own cursor,
    # so it survives socket reconnects. CPython list append/index is GIL-atomic, which is all the
    # single-producer (worker thread) / async-reader access here needs.
    events: list[dict] = field(default_factory=list)
    status: str = "queued"  # queued | running | done | error
    error: str | None = None


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def list_active() -> list[dict]:
    """Jobs that are queued or running (for the web app's 'what's running' indicator)."""
    return [
        {"id": j.id, "class_id": j.class_id, "status": j.status}
        for j in _jobs.values()
        if j.status in ("queued", "running")
    ]


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
                class_dir, engine_override=engine, force=force, progress=job.events.append
            )
        except Exception as e:  # surface to the UI rather than dying silently
            job.status = "error"
            job.error = str(e)
            job.events.append({"type": "error", "message": str(e)})
        else:
            job.status = "done"
        finally:
            job.events.append({"type": "job_done", "status": job.status, "error": job.error})

    _executor.submit(run)
    return job
