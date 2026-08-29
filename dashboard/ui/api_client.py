"""HTTP client the Streamlit UI uses to talk to the FastAPI backend."""

import logging

import httpx

from settings import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(120.0, connect=5.0)


class ApiError(Exception):
    """Raised when the API returns an error response."""


def _request(method: str, path: str, **kwargs) -> httpx.Response:
    """Send one request to the API and raise ApiError on failure."""
    url = f"{settings.API_URL}{path}"
    try:
        response = httpx.request(method, url, timeout=_TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(f"Could not reach the API at {settings.API_URL} — is it running?") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise ApiError(str(detail))
    return response


def upload_statement(data: bytes, filename: str) -> dict:
    """Submit a statement for import; returns {job_id, status} immediately."""
    files = {"file": (filename, data)}
    return _request("POST", "/statements", files=files).json()


def get_job(job_id: str) -> dict:
    """Fetch the current state of an import job."""
    return _request("GET", f"/jobs/{job_id}").json()


def list_statements() -> list[dict]:
    """Fetch all imported statements."""
    return _request("GET", "/statements").json()


def list_categories() -> list[dict]:
    """Fetch all categories."""
    return _request("GET", "/categories").json()


def get_summary(month: int, year: int) -> list[dict]:
    """Fetch the category breakdown for a month."""
    return _request("GET", "/summary", params={"month": month, "year": year}).json()


def get_income(month: int, year: int) -> dict:
    """Fetch total income for a month."""
    return _request("GET", "/income", params={"month": month, "year": year}).json()


def get_bank_fees(year: int) -> list[dict]:
    """Fetch monthly bank fee totals for a year."""
    return _request("GET", "/bank-fees", params={"year": year}).json()


def get_trend(months: int | None = None) -> list[dict]:
    """Fetch per-month summaries for the trend chart."""
    params = {"months": months} if months else {}
    return _request("GET", "/trend", params=params).json()


def get_review_queue() -> list[dict]:
    """Fetch transactions needing user review."""
    return _request("GET", "/review").json()


def confirm_transaction(transaction_id: int) -> dict:
    """Confirm a transaction's category."""
    return _request("POST", f"/transactions/{transaction_id}/confirm").json()


def update_category(transaction_id: int, category_id: int) -> dict:
    """Change a transaction's category."""
    return _request(
        "PATCH",
        f"/transactions/{transaction_id}/category",
        json={"category_id": category_id},
    ).json()


def send_chat(session_id: str, message: str, month: int, year: int) -> str:
    """Send a chat message and return the agent's answer."""
    body = {"session_id": session_id, "message": message, "month": month, "year": year}
    return _request("POST", "/chat", json=body).json()["answer"]
