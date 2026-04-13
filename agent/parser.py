import io
import json
import logging

from google import genai
from PIL import Image

from agent.prompts import PARSE_STATEMENT_PROMPT
from settings import settings

logger = logging.getLogger(__name__)

client = genai.Client(api_key=settings.GOOGLE_API_KEY)


def _to_image(uploaded_file) -> Image.Image:
    """Convert an UploadedFile (PDF or image) to a PIL Image."""
    name: str = getattr(uploaded_file, "name", "")
    data: bytes = uploaded_file.read()
    if name.lower().endswith(".pdf"):
        from pdf2image import convert_from_bytes
        pages = convert_from_bytes(data)
        return pages[0]
    return Image.open(io.BytesIO(data))


def parse(uploaded_file) -> list[dict]:
    """Parse a bank statement PDF or image and return a list of transaction dicts."""
    try:
        image = _to_image(uploaded_file)
        response = client.models.generate_content(
            model=settings.FLASH_MODEL,
            contents=[PARSE_STATEMENT_PROMPT, image],
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
    logger.info("agent.parser imported OK — client model: %s", settings.FLASH_MODEL)
    logger.info("PARSE_STATEMENT_PROMPT length: %d chars", len(PARSE_STATEMENT_PROMPT))
