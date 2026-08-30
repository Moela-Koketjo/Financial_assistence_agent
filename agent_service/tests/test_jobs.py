"""Background import job store."""

from api import jobs


def test_job_starts_processing_and_completes():
    job = jobs.create("statement.pdf")
    assert job.status == "processing"
    jobs.mark_done(job.id, {"transaction_count": 60, "month": 2, "year": 2026})
    stored = jobs.get(job.id)
    assert stored.status == "done"
    assert stored.result["transaction_count"] == 60
    assert stored.error is None


def test_failure_records_a_reason_and_a_code():
    job = jobs.create("bad.pdf")
    jobs.mark_failed(job.id, "Could not parse any transactions.", "parse")
    stored = jobs.get(job.id)
    assert stored.status == "failed"
    assert stored.error_code == "parse"
    assert stored.result is None


def test_unknown_job_is_none():
    assert jobs.get("does-not-exist") is None


def test_store_is_capped_so_it_cannot_grow_forever():
    """Job state is progress tracking, not durable history."""
    made = [jobs.create(f"f{i}.pdf") for i in range(jobs._MAX_JOBS + 15)]
    assert len(jobs._jobs) <= jobs._MAX_JOBS
    assert jobs.get(made[-1].id) is not None       # newest survives


def test_job_serialises_for_the_api():
    job = jobs.create("x.pdf")
    payload = jobs.get(job.id).as_dict()
    assert set(payload) >= {"id", "status", "filename", "created_at", "result", "error"}
