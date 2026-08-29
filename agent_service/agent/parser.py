import io
import json
import logging

from PIL import Image

from agent.llm import call_with_retry, client
from agent.prompts import PARSE_STATEMENT_PROMPT
from settings import settings

logger = logging.getLogger(__name__)

# Render PDF pages at ~200 DPI (72 DPI base) so statement text stays legible
_RENDER_SCALE = 2.8


def _to_images(data: bytes, filename: str) -> list[Image.Image]:
    """Convert raw file bytes (PDF or image) to a list of PIL Images, one per page."""
    if not filename.lower().endswith(".pdf"):
        return [Image.open(io.BytesIO(data))]

    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    page_count = min(len(pdf), settings.STATEMENT_MAX_PAGES)
    if len(pdf) > page_count:
        logger.warning("Statement has %d pages — parsing first %d", len(pdf), page_count)
    return [pdf[i].render(scale=_RENDER_SCALE).to_pil() for i in range(page_count)]


def parse(data: bytes, filename: str) -> list[dict]:
    """Parse bank statement bytes (PDF or image) and return a list of transaction dicts."""
    try:
        images = _to_images(data, filename)
        logger.info("Parsing %s — %d page(s)", filename, len(images))
        response = call_with_retry(
            lambda: client.models.generate_content(
                model=settings.PARSE_MODEL,
                contents=[PARSE_STATEMENT_PROMPT, *images],
            ),
            what=f"parse {filename}",
        )
        text: str = (
            response.text
            .strip()
            .removeprefix("```json")
            .removesuffix("```")
            .strip()
        )
        return json.loads(text)
    except Exception:
        logger.exception("Failed to parse bank statement")
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("agent.parser imported OK — client model: %s", settings.PARSE_MODEL)
    logger.info("PARSE_STATEMENT_PROMPT length: %d chars", len(PARSE_STATEMENT_PROMPT))
