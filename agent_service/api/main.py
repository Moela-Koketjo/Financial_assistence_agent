"""FastAPI app exposing the finance agent — statements, dashboard data, and chat."""

import logging
from collections.abc import Generator

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from agent.llm import describe_error
from agent.tools import ask
from api import jobs, memory
from api.service import (
    DuplicateStatementError,
    ParseError,
    import_statement,
    statement_period_of,
)
from db.database import SessionLocal
from db.queries import (
    confirm_transaction,
    get_bank_fees,
    get_categories,
    get_income,
    get_statements_list,
    get_summary,
    get_transaction,
    get_transactions_needing_review,
    rebuild_monthly_summary,
    update_transaction_category,
)
from settings import settings

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME)

_ALLOWED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg")


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency — one database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChatRequest(BaseModel):
    """Chat message from the UI, tied to a session for follow-up memory."""

    session_id: str
    message: str
    month: int
    year: int


class CategoryUpdate(BaseModel):
    """New category assignment for a transaction."""

    category_id: int


@app.get("/health")
def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}


def _run_import(job_id: str, data: bytes, filename: str) -> None:
    """Run the import pipeline off the request path, with its own DB session."""
    db = SessionLocal()
    try:
        jobs.mark_done(job_id, import_statement(db, data, filename))
    except DuplicateStatementError as exc:
        db.rollback()
        jobs.mark_failed(job_id, str(exc), "duplicate")
    except ParseError as exc:
        db.rollback()
        jobs.mark_failed(job_id, str(exc), "parse")
    except Exception:
        db.rollback()
        logger.exception("Import job %s crashed", job_id)
        jobs.mark_failed(job_id, "Unexpected error while importing the statement.", "internal")
    finally:
        db.close()


@app.post("/statements", status_code=202)
def upload_statement(file: UploadFile, background_tasks: BackgroundTasks) -> dict:
    """Accept a statement for import and return a job to poll — does not block."""
    filename = file.filename or ""
    if not filename.lower().endswith(_ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=422, detail="Only PDF, PNG, and JPEG files are supported.")
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded file is empty.")

    job = jobs.create(filename)
    background_tasks.add_task(_run_import, job.id, data, filename)
    return {"job_id": job.id, "status": job.status}


@app.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    """Return the current state of an import job."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job id.")
    return job.as_dict()


@app.get("/statements")
def list_statements(db: Session = Depends(get_db_session)) -> list[dict]:
    """List all imported statements, newest first."""
    return get_statements_list(db)


@app.get("/categories")
def list_categories(db: Session = Depends(get_db_session)) -> list[dict]:
    """List all categories with colours."""
    return get_categories(db)


@app.get("/summary")
def month_summary(month: int, year: int, db: Session = Depends(get_db_session)) -> list[dict]:
    """Spending breakdown by category for one month."""
    return get_summary(db, month, year)


@app.get("/income")
def month_income(month: int, year: int, db: Session = Depends(get_db_session)) -> dict:
    """Total income (CR transactions) for one month."""
    return get_income(db, month, year)


@app.get("/bank-fees")
def bank_fees(year: int, db: Session = Depends(get_db_session)) -> list[dict]:
    """Monthly bank fee totals for a year."""
    return get_bank_fees(db, year)


@app.get("/trend")
def spending_trend(months: int | None = None, db: Session = Depends(get_db_session)) -> list[dict]:
    """Per-month category summaries for the last N imported statements, oldest first."""
    num = months or settings.DEFAULT_MONTHS_TREND
    statements = list(reversed(get_statements_list(db)[:num]))
    return [
        {
            "month": s["statement_month"],
            "year": s["statement_year"],
            "rows": get_summary(db, s["statement_month"], s["statement_year"]),
        }
        for s in statements
    ]


@app.get("/review")
def review_queue(db: Session = Depends(get_db_session)) -> list[dict]:
    """Transactions with unconfirmed LLM categorizations."""
    return get_transactions_needing_review(db)


@app.post("/transactions/{transaction_id}/confirm")
def confirm(transaction_id: int, db: Session = Depends(get_db_session)) -> dict:
    """Mark a transaction's category as user-confirmed."""
    confirm_transaction(db, transaction_id)
    db.commit()
    return {"status": "confirmed", "transaction_id": transaction_id}


@app.patch("/transactions/{transaction_id}/category")
def recategorize(
    transaction_id: int,
    body: CategoryUpdate,
    db: Session = Depends(get_db_session),
) -> dict:
    """Change a transaction's category and rebuild its month's summary."""
    tx = get_transaction(db, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    update_transaction_category(db, transaction_id, body.category_id)
    period = statement_period_of(db, tx["date"])
    if period:
        rebuild_monthly_summary(db, period[0], period[1])
    db.commit()
    return {"status": "updated", "transaction_id": transaction_id, "category_id": body.category_id}


@app.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db_session)) -> dict:
    """Answer a question using the session's chat memory and the database."""
    periods = get_statements_list(db)
    gemini_chat = memory.get_chat(
        body.session_id, body.month, body.year, periods, get_categories(db)
    )
    try:
        answer = ask(db, gemini_chat, body.message, body.month, body.year, body.session_id)
    except Exception as exc:
        logger.error("[%s] chat failed — %s", body.session_id[:8], describe_error(exc))
        logger.debug("chat failure detail", exc_info=True)
        raise HTTPException(status_code=502, detail=f"The agent could not answer: {describe_error(exc)}")
    return {"answer": answer}


@app.delete("/chat/{session_id}")
def reset_chat(session_id: str) -> dict:
    """Clear a session's conversation memory."""
    memory.clear(session_id)
    return {"status": "cleared", "session_id": session_id}
