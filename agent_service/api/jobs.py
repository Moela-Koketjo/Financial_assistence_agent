"""In-process job store for long-running statement imports."""

import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Keep the most recent jobs only — this store is memory, not history
_MAX_JOBS = 50


@dataclass
class Job:
    """One statement import, tracked from acceptance to completion."""

    id: str
    filename: str
    status: str = "processing"          # processing | done | failed
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    result: Optional[dict] = None
    error: Optional[str] = None
    error_code: Optional[str] = None    # duplicate | parse | internal

    def as_dict(self) -> dict:
        """Return the job as a plain JSON-serialisable dict."""
        return asdict(self)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def create(filename: str) -> Job:
    """Register a new job in the processing state and return it."""
    job = Job(id=uuid.uuid4().hex, filename=filename)
    with _lock:
        _jobs[job.id] = job
        _trim_locked()
    logger.info("Job %s accepted for %s", job.id, filename)
    return job


def get(job_id: str) -> Optional[Job]:
    """Return a job by id, or None if it is unknown or has been evicted."""
    with _lock:
        return _jobs.get(job_id)


def mark_done(job_id: str, result: dict) -> None:
    """Mark a job finished and attach its import summary."""
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.status = "done"
            job.result = result
    logger.info("Job %s done: %s", job_id, result)


def mark_failed(job_id: str, error: str, error_code: str) -> None:
    """Mark a job failed and attach a user-facing reason."""
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.status = "failed"
            job.error = error
            job.error_code = error_code
    logger.warning("Job %s failed (%s): %s", job_id, error_code, error)


def _trim_locked() -> None:
    """Evict the oldest jobs once the store exceeds _MAX_JOBS. Caller holds the lock."""
    while len(_jobs) > _MAX_JOBS:
        oldest = min(_jobs.values(), key=lambda j: j.created_at)
        _jobs.pop(oldest.id, None)
